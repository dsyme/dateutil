# -*- coding: utf-8 -*-
"""
This module offers a generic date/time string parser which is able to parse
most known formats to represent a date and/or time.

This module attempts to be forgiving with regards to unlikely input formats,
returning a datetime object even for dates which are ambiguous. If an element
of a date/time stamp is omitted, the following rules are applied:

- If AM or PM is left unspecified, a 24-hour clock is assumed, however, an hour
  on a 12-hour clock (``0 <= hour <= 12``) *must* be specified if AM or PM is
  specified.
- If a time zone is omitted, a timezone-naive datetime is returned.

If any other elements are missing, they are taken from the
:class:`datetime.datetime` object passed to the parameter ``default``. If this
results in a day number exceeding the valid number of days per month, the
value falls back to the end of the month.

Additional resources about date/time string formats can be found below:

- `A summary of the international standard date and time notation
  <https://www.cl.cam.ac.uk/~mgk25/iso-time.html>`_
- `W3C Date and Time Formats <https://www.w3.org/TR/NOTE-datetime>`_
- `Time Formats (Planetary Rings Node) <https://pds-rings.seti.org:443/tools/time_formats.html>`_
- `CPAN ParseDate module
  <https://metacpan.org/pod/release/MUIR/Time-modules-2013.0912/lib/Time/ParseDate.pm>`_
- `Java SimpleDateFormat Class
  <https://docs.oracle.com/javase/6/docs/api/java/text/SimpleDateFormat.html>`_
"""
from __future__ import unicode_literals

import datetime
import re
import string
import time
import warnings

from calendar import monthrange
from collections import deque
from io import StringIO

import six
from six import integer_types, text_type

from decimal import Decimal

from warnings import warn

from .. import relativedelta
from .. import tz

__all__ = ["parse", "parserinfo", "ParserError"]


# TODO: pandas.core.tools.datetimes imports this explicitly.  Might be worth
# making public and/or figuring out if there is something we can
# take off their plate.
class _timelex(object):
    # Fractional seconds are sometimes split by a comma
    _split_decimal = re.compile("([.,])")
    

    def __init__(self, instream):
        if isinstance(instream, (bytes, bytearray)):
            instream = instream.decode()

        if isinstance(instream, text_type):
            instream = StringIO(instream)
        elif getattr(instream, 'read', None) is None:
            raise TypeError('Parser must be a string or character stream, not '
                            '{itype}'.format(itype=instream.__class__.__name__))

        self.instream = instream
        self.charstack = deque()  # Use deque for efficient popleft
        self.tokenstack = deque()  # Use deque for efficient popleft
        self.eof = False

    def get_token(self):
        """
        This function breaks the time string into lexical units (tokens), which
        can be parsed by the parser. Lexical units are demarcated by changes in
        the character set, so any continuous string of letters is considered
        one unit, any continuous string of numbers is considered one unit.

        The main complication arises from the fact that dots ('.') can be used
        both as separators (e.g. "Sep.20.2009") or decimal points (e.g.
        "4:30:21.447"). As such, it is necessary to read the full context of
        any dot-separated strings before breaking it into tokens; as such, this
        function maintains a "token stack", for when the ambiguous context
        demands that multiple tokens be parsed at once.
        """
        if self.tokenstack:
            return self.tokenstack.popleft()

        seenletters = False
        token_chars = []  # Use list for efficient character accumulation
        state = None

        while not self.eof:
            # We only realize that we've reached the end of a token when we
            # find a character that's not part of the current token - since
            # that character may be part of the next token, it's stored in the
            # charstack.
            if self.charstack:
                nextchar = self.charstack.popleft()
            else:
                nextchar = self.instream.read(1)
                while nextchar == '\x00':
                    nextchar = self.instream.read(1)

            if not nextchar:
                self.eof = True
                break
            elif not state:
                # First character of the token - determines if we're starting
                # to parse a word, a number or something else.
                token_chars.append(nextchar)
                if nextchar.isalpha():  # Direct call for initial check 
                    state = 'a'
                elif nextchar.isdigit():  # Direct call for initial check
                    state = '0'
                elif nextchar.isspace():  # Direct call for initial check
                    return ' '  # Return immediately for whitespace
                else:
                    return nextchar  # Return immediately for punctuation
            elif state == 'a':
                # If we've already started reading a word, we keep reading
                # letters until we find something that's not part of a word.
                seenletters = True
                if nextchar.isalpha():
                    token_chars.append(nextchar)
                elif nextchar == '.':
                    token_chars.append(nextchar)
                    state = 'a.'
                else:
                    self.charstack.append(nextchar)
                    break  # emit token
            elif state == '0':
                # If we've already started reading a number, we keep reading
                # numbers until we find something that doesn't fit.
                if nextchar.isdigit():
                    token_chars.append(nextchar)
                elif nextchar == '.' or (nextchar == ',' and len(token_chars) >= 2):
                    token_chars.append(nextchar)
                    state = '0.'
                else:
                    self.charstack.append(nextchar)
                    break  # emit token
            elif state == 'a.':
                # If we've seen some letters and a dot separator, continue
                # parsing, and the tokens will be broken up later.
                seenletters = True
                if nextchar == '.' or nextchar.isalpha():
                    token_chars.append(nextchar)
                elif nextchar.isdigit() and token_chars[-1] == '.':
                    token_chars.append(nextchar)
                    state = '0.'
                else:
                    self.charstack.append(nextchar)
                    break  # emit token
            elif state == '0.':
                # If we've seen at least one dot separator, keep going, we'll
                # break up the tokens later.
                if nextchar == '.' or nextchar.isdigit():
                    token_chars.append(nextchar)
                elif nextchar.isalpha() and token_chars[-1] == '.':
                    token_chars.append(nextchar)
                    state = 'a.'
                else:
                    self.charstack.append(nextchar)
                    break  # emit token

        # Convert character list to string
        if not token_chars:
            return None
        token = ''.join(token_chars)

        if (state in ('a.', '0.') and (seenletters or token.count('.') > 1 or
                                       token[-1] in '.,'))):
            l = self._split_decimal.split(token)
            token = l[0]
            for tok in l[1:]:
                if tok:
                    self.tokenstack.append(tok)

        if state == '0.' and token.count('.') == 0:
            token = token.replace(',', '.')

        return token


    def __iter__(self):
        return self

    def __next__(self):
        token = self.get_token()
        if token is None:
            raise StopIteration

        return token

    def next(self):
        return self.__next__()  # Python 2.x support

    @classmethod
    def split(cls, s):
        return list(cls(s))

    @classmethod
    def isword(cls, nextchar):
        """ Whether or not the next character is part of a word """
        return nextchar.isalpha()

    @classmethod
    def isnum(cls, nextchar):
        """ Whether the next character is part of a number """
        return nextchar.isdigit()

    @classmethod
    def isspace(cls, nextchar):
        """ Whether the next character is whitespace """
        return nextchar.isspace()