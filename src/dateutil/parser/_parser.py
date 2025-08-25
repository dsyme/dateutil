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
  <http://www.cl.cam.ac.uk/~mgk25/iso-time.html>`_
- `W3C Date and Time Formats <http://www.w3.org/TR/NOTE-datetime>`_
- `Time Formats (Planetary Rings Node) <http://pds-rings.seti.org:8080/toolshelp/time_formats.html>`_
- `CPAN ParseDate module
  <http://search.cpan.org/~muir/Time-modules-2013.0912/lib/Time/ParseDate.pm>`_
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
from io import StringIO

import six
from six import integer_types, text_type

from decimal import Decimal

from warnings import warn

from .. import relativedelta
from .. import tz

__all__ = ["parse", "parserinfo", "ParserError"]

# Pre-compiled regex pattern for timezone parsing optimization
_TZPARSER_SPLIT_PATTERN = re.compile(r'([,:.]|[a-zA-Z]+|[0-9]+)')


# TODO: pandas.core.tools.datetimes imports this explicitly.  Might be worth
# making public and/or figuring out if there is something we can
# do to make that test faster.

def _timelex_split_decimal(s):
    """
    Helper function for `_timelex.split`.
    
    Splits the provided string on a decimal delimiter (.), but only if it's 
    not preceded by another decimal delimiter.

    :param s:
        A string, as returned by `_timelex.split`

    :return:
        A list of strings.
    """
    if '.' not in s:
        return [s]

    # Check if there are multiple consecutive periods and return the string
    # unchanged if there are.
    if '..' in s:
        return [s]

    split_result = s.split('.')

    # If there are only two components, then we can split this way. If there
    # are more, then it's not a decimal
    if len(split_result) == 2:
        # Split ["12", "34"] -> ["12", ".", "34"]
        return [split_result[0], '.', split_result[1]]
    else:
        return [s]


class _timelex(object):
    # Sentinel for when we don't want to return a token
    _split_decimal = re.compile(r'([\.,])')

    def __init__(self, instream):
        if six.PY2:
            # In Python 2, we can't duck type properly because unicode has
            # a 'decode' function, and we'd be double-decoding
            if isinstance(instream, (bytes, bytearray)):
                instream = instream.decode()
        else:
            if getattr(instream, 'decode', None) is not None:
                instream = instream.decode()

        if isinstance(instream, text_type):
            instream = StringIO(instream)
        elif getattr(instream, 'read', None) is None:
            raise TypeError("Parser must be a string or character stream, not "
                            "{itype}".format(itype=instream.__class__.__name__))

        self.instream = instream
        self.charstack = []
        self.tokenstack = []
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
        any dot-separated strings before deciding whether to split it.

        :return:
            A tuple of (token_type, token_value), where token_type is one of
            "a" for alphabetic, "n" for numeric, or None (if EOF).
        """
        seenletters = False
        token = None
        state = None

        while not self.eof:
            # We only realize that we've reached the end of a token when we
            # find a character that's not of the same type - so we'll always
            # read one character too many.
            nextchar = self._get_char()
            if nextchar is None:
                self.eof = True
                break

            elif not state:
                # First character of the token - determines if we're starting
                # to parse a word, a number or something else.
                token = nextchar

                if self.isword(nextchar):
                    state = 'a'
                elif self.isnum(nextchar):
                    state = '0'
                elif self.isspace(nextchar):
                    token = ' '
                    break  # emit token
                else:
                    break  # emit token

            elif state == 'a':
                # If we've already started reading a word, we keep reading
                # letters until we find something that's not a letter.
                if self.isword(nextchar):
                    token += nextchar
                elif nextchar == '.':
                    # We need to lokahead to determine if this is a dot
                    # separated sequence or a decimal
                    after_nextchar = self._get_char()
                    if after_nextchar is None:
                        # EOF case
                        self.eof = True
                        self._push_char(nextchar)
                        break
                    elif self.isword(after_nextchar):
                        # Both before and after the dot are letters, so we
                        # continue tokenizing the word
                        token += nextchar + after_nextchar
                        seenletters = True
                    elif self.isnum(after_nextchar):
                        # We've got a dot between a word and a number.
                        # Append the dot to the word token, put the number
                        # back.
                        token += nextchar
                        self._push_char(after_nextchar)
                        break
                    else:
                        # The dot is followed by something that's neither a
                        # letter nor a number. Put the dot and the other
                        # character back, and end the current token.
                        self._push_char(after_nextchar)
                        self._push_char(nextchar)
                        break
                else:
                    # end of token
                    self._push_char(nextchar)
                    break

            elif state == '0':
                # If we've already started reading a number, we keep reading
                # numbers until we find something that's not a number.
                if self.isnum(nextchar):
                    token += nextchar
                elif nextchar == '.' or (nextchar == ',' and len(token) >= 2):
                    # We need to lookahead to determine if this is a dot
                    # separated sequence or a decimal
                    after_nextchar = self._get_char()
                    if after_nextchar is None:
                        # EOF case
                        self.eof = True
                        self._push_char(nextchar)
                        break
                    elif self.isnum(after_nextchar):
                        # Both before and after the separator are numbers
                        token += nextchar + after_nextchar
                    elif self.isword(after_nextchar) and nextchar == '.':
                        # We've got a dot between a number and a word.
                        # This concludes the number token, and we put the
                        # dot and the word character back so that they can
                        # be tokenized separately.
                        self._push_char(after_nextchar)
                        self._push_char(nextchar)
                        break
                    else:
                        # The separator is followed by something that's
                        # neither a letter nor a number. Put the separator
                        # and the other character back, and end the current
                        # token.
                        self._push_char(after_nextchar)
                        self._push_char(nextchar)
                        break
                else:
                    # end of token
                    self._push_char(nextchar)
                    break

        if (state in ('a', '0') and (seenletters or token.count('.') > 1 or
                                     token[-1] in '.,')):
            l = self._split_decimal.split(token)
            token = l[0]
            for tok in l[1:]:
                if tok:
                    self.tokenstack.append((state, tok))

        if state == '0.' and token.count('.') == 0:
            token = token.replace(',', '.')

        return (state, token)

    def __iter__(self):
        return self

    def __next__(self):
        token = self.get_token()
        if token[0] is None:
            raise StopIteration

        return token

    def next(self):
        return self.__next__()

    def split(self, s):
        self.__init__(s)
        return list(self)

    def _get_char(self):
        if self.charstack:
            return self.charstack.pop(0)
        else:
            c = self.instream.read(1)
            if c:
                return c
            else:
                return None

    def _push_char(self, c):
        self.charstack.insert(0, c)

    def isword(self, nextchar):
        """ Whether or not the next character is part of a word """
        return nextchar.isalpha()

    def isnum(self, nextchar):
        """ Whether the next character is part of a number """
        return nextchar.isdecimal()

    def isspace(self, nextchar):
        """ Whether the next character is whitespace """
        return nextchar.isspace()


class _resultbase(object):

    def __init__(self):
        for attr in self.__slots__:
            setattr(self, attr, None)

    def _repr(self, classname):
        l = []
        for attr in self.__slots__:
            value = getattr(self, attr)
            if value is not None:
                l.append("%s=%s" % (attr, repr(value)))
        return "%s(%s)" % (classname, ", ".join(l))

    def __len__(self):
        return len([x for x in self.__slots__ if getattr(self, x) is not None])

    def __repr__(self):
        return self._repr(self.__class__.__name__)


class parserinfo(object):
    """
    Class which handles what inputs are accepted. Subclass this to customize
    the language and acceptable values for each parameter.

    :param dayfirst:
        Whether to interpret the first value in an ambiguous 3-integer date
        (e.g. 01/05/09) as the day (``True``) or month (``False``). If
        ``yearfirst`` is set to ``True``, this distinguishes between YDM
        and YMD. Default is ``False``.

    :param yearfirst:
        Whether to interpret the first value in an ambiguous 3-integer date
        (e.g. 01/05/09) as the year. If ``True``, the first number is taken
        to be the year, otherwise the last number is taken to be the year.
        Default is ``False``.
    """

    # m from a.m/p.m, t from ISO T separator
    JUMP = [" ", ".", ",", ";", "-", "/", "'",
            "at", "on", "and", "ad", "m", "t", "of",
            "st", "nd", "rd", "th"]

    WEEKDAYS = [("Mon", "Monday"),
                ("Tue", "Tuesday"),
                ("Wed", "Wednesday"),
                ("Thu", "Thursday"),
                ("Fri", "Friday"),
                ("Sat", "Saturday"),
                ("Sun", "Sunday")]
    MONTHS = [("Jan", "January"),
              ("Feb", "February"),
              ("Mar", "March"),
              ("Apr", "April"),
              ("May", "May"),
              ("Jun", "June"),
              ("Jul", "July"),
              ("Aug", "August"),
              ("Sep", "Sept", "September"),
              ("Oct", "October"),
              ("Nov", "November"),
              ("Dec", "December")]
    HMS = [("h", "hour", "hours"),
           ("m", "minute", "minutes"),
           ("s", "second", "seconds")]
    AMPM = [("am", "a"),
            ("pm", "p")]
    UTCZONE = ["UTC", "GMT", "Z", "z"]
    PERTAIN = ["of"]
    TZOFFSET = {}
    # TODO: ERA = ["AD", "BC", "CE", "BCE", "AH"]

    def __init__(self, dayfirst=False, yearfirst=False):
        self._jump = self._convert(self.JUMP)
        self._weekdays = self._convert(self.WEEKDAYS)
        self._months = self._convert(self.MONTHS)
        self._hms = self._convert(self.HMS)
        self._ampm = self._convert(self.AMPM)
        self._utczone = self._convert(self.UTCZONE)
        self._pertain = self._convert(self.PERTAIN)

        self.dayfirst = dayfirst
        self.yearfirst = yearfirst

        self._year = time.localtime().tm_year
        self._century = self._year // 100 * 100

    def _convert(self, lst):
        dct = {}
        for i, v in enumerate(lst):
            if isinstance(v, tuple):
                for v in v:
                    dct[v.lower()] = i
            else:
                dct[v.lower()] = i
        return dct

    def jump(self, name):
        return name.lower() in self._jump

    def weekday(self, name):
        try:
            return self._weekdays[name.lower()]
        except KeyError:
            pass
        return None

    def month(self, name):
        try:
            return self._months[name.lower()] + 1
        except KeyError:
            pass
        return None

    def hms(self, name):
        try:
            return self._hms[name.lower()]
        except KeyError:
            return None

    def ampm(self, name):
        try:
            return self._ampm[name.lower()]
        except KeyError:
            return None

    def pertain(self, name):
        return name.lower() in self._pertain

    def utczone(self, name):
        return name.lower() in self._utczone

    def tzoffset(self, name):
        if name in self._utczone:
            return 0

        return self.TZOFFSET.get(name)

    def convertyear(self, year, century_specified=False):
        """ Convert year to four digit format, if not already. """
        # Function contract is that the year is always positive
        assert year >= 0

        if year < 100 and not century_specified:
            # assume current century, at most 50 years from now
            year += self._century
            if abs(year - self._year) >= 50:
                if year < self._year:
                    year += 100
                else:
                    year -= 100
        return year

    def validate(self, res):
        # move to info
        if res.year is not None:
            res.year = self.convertyear(res.year, res.century_specified)

        if ((res.tzoffset == 0 and not res.tzname) or
                (res.tzname == 'Z' or res.tzname == 'z')):
            res.tzname = "UTC"
            res.tzoffset = 0
        elif res.tzoffset != 0 and res.tzname and self.utczone(res.tzname):
            res.tzoffset = 0

        return True


class _ymd(list):
    def __init__(self, *args, **kwargs):
        super(_ymd, self).__init__(*args, **kwargs)
        self.century_specified = False
        self.dstridx = None
        self.mstridx = None
        self.ystridx = None

    @property
    def has_year(self):
        return self.ystridx is not None

    @property
    def has_month(self):
        return self.mstridx is not None

    @property
    def has_day(self):
        return self.dstridx is not None

    def could_be_day(self, value):
        if self.has_day:
            return False
        return 1 <= value <= 31

    def append(self, val, label=None):
        if hasattr(val, '__len__'):
            if val.isdigit() and len(val) > 2:
                self.century_specified = True
                if label not in (None, 'Y'):  # pragma: no cover
                    raise ValueError(label)
                label = 'Y'
        elif val > 100:
            self.century_specified = True
            if label not in (None, 'Y'):  # pragma: no cover
                raise ValueError(label)
            label = 'Y'

        super(_ymd, self).append(int(val))

        if label == 'M':  # pragma: no cover
            if self.has_month:
                raise ValueError()
            self.mstridx = len(self) - 1
        elif label == 'D':  # pragma: no cover
            if self.has_day:
                raise ValueError()
            self.dstridx = len(self) - 1
        elif label == 'Y':
            if self.has_year:
                raise ValueError()
            self.ystridx = len(self) - 1

    def _resolve_from_stridxs(self, strids):
        """
        Try to resolve the identities of year/month/day elements using
        ystridx, mstridx, and dstridx, if enough of these are specified.
        """
        if len(self) == 3 and len(strids) == 2:
            # we can back out the remaining stridx value
            missing = [x for x in range(3) if x not in strids.values()]
            key = [x for x in ['y', 'm', 'd'] if x not in strids]
            assert len(missing) == len(key) == 1
            key = key[0]
            val = missing[0]
            strids[key] = val

        assert len([x for x in strids.values() if x is not None]) > 1, \
            "Not enough info to resolve"

    def resolve_ymd(self, yearfirst, dayfirst):
        len_ymd = len(self)
        year, month, day = (None, None, None)

        strids = (('y', self.ystridx),
                  ('m', self.mstridx),
                  ('d', self.dstridx))

        strids = dict([x for x in strids if x[1] is not None])
        if (len(self) == len(strids) > 0 or
                (len(self) == 3 and len(strids) == 2)):
            self._resolve_from_stridxs(strids)

        if len_ymd > 3:
            raise ValueError("More than 3 YMD values")
        elif len_ymd == 1 or (self.mstridx is not None and len_ymd == 2):
            # One member, or two members with a month string
            if self.mstridx is not None:
                month = self[self.mstridx]
                # since mstridx is defined, it's not 0
                if len_ymd == 2 or self.ystridx is not None:
                    year = self[self.ystridx] if self.ystridx is not None else self[0]
                else:
                    day = self[0]
            elif len_ymd > 1 or self.ystridx is not None:
                year = self[self.ystridx] if self.ystridx is not None else self[0]

        elif len_ymd == 2:
            # Two members with numbers
            if self.has_year:
                year = self[self.ystridx]
                # FIXME: cover this case in tests
                other = self[1 - self.ystridx]  # pragma: no cover
                if self.could_be_day(other):  # pragma: no cover
                    day = other  # pragma: no cover
                else:  # pragma: no cover
                    month = other  # pragma: no cover
            elif self.has_month:
                month = self[self.mstridx]
                other = self[1 - self.mstridx]  # pragma: no cover
                if self.could_be_day(other):  # pragma: no cover
                    day = other  # pragma: no cover
                else:  # pragma: no cover
                    year = other  # pragma: no cover
            elif self.has_day:
                day = self[self.dstridx]  # pragma: no cover
                other = self[1 - self.dstridx]  # pragma: no cover
                # FIXME: cover this case in tests
                if self.could_be_day(other):  # pragma: no cover
                    month = other  # pragma: no cover
                else:  # pragma: no cover
                    year = other  # pragma: no cover
            else:
                if self[0] > 31:
                    # 99-01 or 99-Jan
                    year = self[0]
                    month = self[1]
                elif self[1] > 31:
                    # 01-99
                    month = self[0]
                    year = self[1]
                elif dayfirst and self[1] <= 12:
                    # 13-01
                    day = self[0]
                    month = self[1]
                elif self[0] > 12:
                    # 13-01
                    day = self[0]
                    month = self[1]
                else:
                    # 01-13
                    month = self[0]
                    day = self[1]

        elif len_ymd == 3:
            # Three members
            if self.has_year:
                year = self[self.ystridx]
                if len(strids) > 1:
                    month = self.get(strids.get('m'), None)
                    day = self.get(strids.get('d'), None)
                else:
                    other = [self[i] for i in range(len(self))
                             if i != self.ystridx]
                    if self.mstridx is not None:
                        month = self[self.mstridx]
                        other.remove(month)
                        day = other[0]
                    elif self.dstridx is not None:
                        day = self[self.dstridx]  # pragma: no cover
                        other.remove(day)  # pragma: no cover
                        month = other[0]  # pragma: no cover
                    elif other[0] > 12 and other[1] <= 12:
                        day = other[0]
                        month = other[1]
                    elif other[1] > 12 and other[0] <= 12:
                        day = other[1]
                        month = other[0]
                    elif dayfirst and other[1] <= 31:
                        day = other[0]
                        month = other[1]
                    elif other[0] <= 31:
                        # if both are valid days, assume d,m
                        day = other[1]
                        month = other[0]
                    else:  # pragma: no cover
                        # TODO: add note about leapyear?
                        day = None  # pragma: no cover
                        month = None  # pragma: no cover

            elif self.mstridx is not None:
                month = self[self.mstridx]
                other = [self[i] for i in range(len(self)) if i != self.mstridx]
                if self.ystridx is not None:
                    year = self[self.ystridx]
                    other.remove(year)
                    day = other[0]
                elif self.dstridx is not None:
                    day = self[self.dstridx]
                    other.remove(day)
                    year = other[0]
                elif other[0] > 31 and other[1] <= 31:
                    year = other[0]
                    day = other[1]
                elif other[1] > 31 and other[0] <= 31:
                    year = other[1]
                    day = other[0]
                elif other[0] > 12 and other[1] <= 12:
                    day = other[0]
                    year = other[1]
                elif other[1] > 12 and other[0] <= 12:
                    day = other[1]
                    year = other[0]
                elif yearfirst and other[0] <= 31:
                    year = other[0]
                    day = other[1]
                elif not yearfirst and other[1] <= 31:
                    year = other[1]
                    day = other[0]
                else:
                    if dayfirst == yearfirst:
                        # FIXME: this seems arbitrary
                        year = other[1]  # pragma: no cover
                        day = other[0]  # pragma: no cover
                    elif dayfirst:
                        year = other[1]  # pragma: no cover
                        day = other[0]  # pragma: no cover
                    else:
                        year = other[0]  # pragma: no cover
                        day = other[1]  # pragma: no cover

            elif self.dstridx is not None:  # pragma: no cover
                # Covered case-by-case below
                day = self[self.dstridx]  # pragma: no cover
                other = [self[i] for i in range(len(self))  # pragma: no cover
                         if i != self.dstridx]  # pragma: no cover
                if self.ystridx is not None:  # pragma: no cover
                    year = self[self.ystridx]  # pragma: no cover
                    other.remove(year)  # pragma: no cover
                    month = other[0]  # pragma: no cover
                elif other[0] > 31 and other[1] <= 12:  # pragma: no cover
                    year = other[0]  # pragma: no cover
                    month = other[1]  # pragma: no cover
                elif other[1] > 31 and other[0] <= 12:  # pragma: no cover
                    year = other[1]  # pragma: no cover
                    month = other[0]  # pragma: no cover
                elif other[0] > 12 and other[1] <= 31:  # pragma: no cover
                    month = other[0]  # pragma: no cover
                    year = other[1]  # pragma: no cover
                elif other[1] > 12 and other[0] <= 31:  # pragma: no cover
                    month = other[1]  # pragma: no cover
                    year = other[0]  # pragma: no cover
                elif yearfirst and other[0] <= 12:  # pragma: no cover
                    year = other[0]  # pragma: no cover
                    month = other[1]  # pragma: no cover
                elif not yearfirst and other[1] <= 12:  # pragma: no cover
                    year = other[1]  # pragma: no cover
                    month = other[0]  # pragma: no cover
                else:  # pragma: no cover
                    if dayfirst == yearfirst:  # pragma: no cover
                        year = other[1]  # pragma: no cover
                        month = other[0]  # pragma: no cover
                    elif dayfirst:  # pragma: no cover
                        year = other[1]  # pragma: no cover
                        month = other[0]  # pragma: no cover
                    else:  # pragma: no cover
                        year = other[0]  # pragma: no cover
                        month = other[1]  # pragma: no cover

            elif (self[0] > 31 or self.ystridx == 0) and self[1] <= 12 and self[2] <= 31:
                # 99-01-01
                if yearfirst or self[0] > 31:
                    year = self[0]
                    month = self[1]
                    day = self[2]
                else:  # pragma: no cover
                    day = self[0]  # pragma: no cover
                    month = self[1]  # pragma: no cover
                    year = self[2]  # pragma: no cover

            elif self[0] > 12 and (self[1] <= 12 or self[2] <= 12) and self[2] <= 31:
                # 13-01-01
                if self[1] <= 12:
                    day = self[0]
                    month = self[1]
                    year = self[2]
                else:  # pragma: no cover
                    day = self[0]  # pragma: no cover
                    month = self[2]  # pragma: no cover
                    year = self[1]  # pragma: no cover

            elif self[1] > 31 and self[0] <= 12 and self[2] <= 12:
                # 01-99-01
                month = self[0]  # pragma: no cover
                year = self[1]  # pragma: no cover
                day = self[2]  # pragma: no cover

            elif self[1] > 12 and self[2] <= 31:
                # 01-13-01
                if dayfirst and self[2] <= 12:
                    day = self[0]
                    month = self[2]
                    year = self[1]
                elif self[0] <= 12:
                    month = self[0]
                    day = self[1]
                    year = self[2]
                else:  # pragma: no cover
                    day = self[0]  # pragma: no cover
                    month = self[1]  # pragma: no cover
                    year = self[2]  # pragma: no cover

            elif self[2] > 31:
                # 01-01-99
                if dayfirst and self[1] <= 12:
                    day = self[0]
                    month = self[1]
                    year = self[2]
                elif yearfirst:
                    year = self[0]  # pragma: no cover
                    month = self[1]  # pragma: no cover
                    day = self[2]  # pragma: no cover
                elif self[0] <= 12:
                    month = self[0]
                    day = self[1]
                    year = self[2]
                else:  # pragma: no cover
                    day = self[0]  # pragma: no cover
                    month = self[1]  # pragma: no cover
                    year = self[2]  # pragma: no cover

            elif self[0] > 12:
                # 13-01-01
                day = self[0]
                month = self[1]
                year = self[2]
            elif self[1] > 12:
                # 01-13-01
                if dayfirst:
                    day = self[0]
                    month = self[2]
                    year = self[1]
                else:
                    month = self[0]
                    day = self[1]
                    year = self[2]
            elif self[2] > 12:
                # 01-01-13
                if dayfirst:
                    day = self[0]
                    month = self[1]
                    year = self[2]
                elif yearfirst:
                    year = self[0]
                    month = self[1]
                    day = self[2]
                else:
                    month = self[0]
                    day = self[1]
                    year = self[2]
            else:
                # 01-01-01
                if dayfirst:
                    day = self[0]
                    month = self[1]
                    year = self[2]
                elif yearfirst:
                    year = self[0]
                    month = self[1]
                    day = self[2]
                else:
                    # FIXME: this is not very intelligent, since it
                    # moves the year to self[2] == 2003, 2004, ...
                    # It would be better to use 2-digit year logic
                    # and only if year is not in range 1930-2030 to
                    # move it.
                    month = self[0]
                    day = self[1]
                    year = self[2]

        return year, month, day


class parser(object):
    def __init__(self, info=None):
        if info is None:
            info = parserinfo()
        self.info = info

    def parse(self, timestr, default=None,
              ignoretz=False, tzinfos=None, **kwargs):
        """
        Parse the date/time string into a :class:`datetime.datetime` object.

        :param timestr:
            Any date/time string using the supported formats.

        :param default:
            The default datetime object to use. This is used to fill in any
            gaps in the parsed date/time. If not provided, the current date
            and time in the local timezone are used.

        :param ignoretz:
            If set ``True``, time zones in parsed strings are ignored and a
            naive :class:`datetime.datetime` object is returned.

        :param tzinfos:
            Additional time zone names / aliases which may be present in the
            string. This argument maps time zone names (and optionally offsets
            from those time zones) to time zones. This parameter can be a
            dictionary with timezone names as keys and the corresponding
            timezone as values or a function taking timezone name and offset as
            arguments and returning a timezone. The timezones to which the names
            are mapped can be an integer offset, tzinfo object or an icalendar
            timezone. Common timezone names which are already mapped are:

            - ``"EST"`` → ``tzoffset("EST", -5)``
            - ``"EDT"`` → ``tzoffset("EDT", -4)``
            - ``"CST"`` → ``tzoffset("CST", -6)``
            - ``"CDT"`` → ``tzoffset("CDT", -5)``
            - ``"MST"`` → ``tzoffset("MST", -7)``
            - ``"MDT"`` → ``tzoffset("MDT", -6)``
            - ``"PST"`` → ``tzoffset("PST", -8)``
            - ``"PDT"`` → ``tzoffset("PDT", -7)``

            The ``tzinfos`` parameter can be an empty dictionary to "reset"
            this behavior. Alternatively, with the ``default_tzinfos``
            parameter, you can override the default time zone names while
            keeping the existing behavior for other names.

        :param **kwargs:
            Keyword arguments as passed to ``_parse()``.

        :return:
            Returns a :class:`datetime.datetime` object or, if the
            ``fuzzy_with_tokens`` option is ``True``, returns a tuple, the
            first element being a :class:`datetime.datetime` object, the second
            a tuple containing the fuzzy tokens.

        :raises ValueError:
            Raised for invalid or unknown string format, if the provided
            :class:`tzinfo` is not in a valid format, or if an invalid date
            would be created.

        :raises TypeError:
            Raised for non-string or character stream input.

        :raises OverflowError:
            Raised if the parsed date exceeds the largest valid C integer on
            your system.
        """

        if default is None:
            default = datetime.datetime.now().replace(hour=0, minute=0,
                                                      second=0, microsecond=0)

        res, skipped_tokens = self._parse(timestr, **kwargs)

        if res is None:
            raise ValueError("Unknown string format: %s", timestr)

        if len(res) == 0:
            raise ValueError("String does not contain a date: %s", timestr)

        try:
            ret = self._build_naive_datetime(res, default)
            if not ignoretz:
                ret = self._build_tzaware_datetime(ret, res, tzinfos)
        except ValueError as ve:
            raise ValueError("%s: %s", ve, timestr)

        if not kwargs.get('fuzzy_with_tokens', False):
            return ret
        else:
            return (ret, skipped_tokens)

    class _result(_resultbase):
        __slots__ = ["year", "month", "day", "weekday",
                     "hour", "minute", "second", "microsecond",
                     "tzname", "tzoffset", "ampm", "any_unused_tokens"]
        __repr__ = _resultbase._repr
        century_specified = False

    def _parse(self, timestr, dayfirst=None, yearfirst=None, fuzzy=False,
               fuzzy_with_tokens=False):
        """
        Private method which performs the heavy lifting of parsing, called from
        ``parse()``, which passes on its ``kwargs`` to this function.
        """
        if fuzzy_with_tokens:
            fuzzy = True

        info = self.info

        if dayfirst is None:
            dayfirst = info.dayfirst

        if yearfirst is None:
            yearfirst = info.yearfirst

        res = self._result()
        l = _timelex.split(timestr)         # Splits the timestr into tokens

        skipped_idxs = []

        # year/month/day list
        ymd = _ymd()

        len_l = len(l)
        i = 0
        while i < len_l:

            # Check if this is a number
            value_repr = l[i]
            try:
                value = float(value_repr)
            except ValueError:
                value = None

            if value is not None:
                # Numeric token
                i = self._parse_numeric_token(l, i, info, ymd, res, fuzzy)

            else:
                # Check weekday
                weekday = info.weekday(l[i])
                if weekday is not None:
                    res.weekday = weekday

                # Check month name
                elif info.month(l[i]) is not None:
                    ymd.append(info.month(l[i]), 'M')

                    if i + 1 < len_l:
                        if l[i + 1] in ('-', '/'):
                            # Jan-01[-99]
                            sep = l[i + 1]
                            ymd.append(l[i + 2])

                            if i + 3 < len_l and l[i + 3] == sep:
                                # Jan-01-99
                                ymd.append(l[i + 4])
                                i += 2

                            i += 2

                        elif (i + 4 < len_l and l[i + 1] == l[i + 3] == ' ' and
                                info.pertain(l[i + 2])):
                            # Jan of 01
                            # In this case, 01 is clearly year
                            if l[i + 4].isdigit():
                                # Convert it here to become unambiguous
                                try:
                                    value = int(l[i + 4])
                                except ValueError:
                                    # What are some malformed cases?
                                    #    1. l[i + 4] is not a digit
                                    # let's just leave this
                                    pass
                                else:
                                    year = str(info.convertyear(value))
                                    ymd.append(year, 'Y')

                            i += 4

                # Check am/pm
                elif info.ampm(l[i]) is not None:
                    # For fuzzy parsing, 'a' or 'am' could be a token
                    # These are not necessarily time tokens
                    ampm = info.ampm(l[i])
                    val_is_ampm = self._ampm_valid(res.hour, ampm,
                                                   fuzzy)

                    if val_is_ampm:
                        res.ampm = ampm

                    elif fuzzy:
                        skipped_idxs.append(i)

                # Check for a timezone name
                elif self._could_be_tzname(res.hour, res.tzname, res.tzoffset, l[i]):
                    res.tzname = l[i]
                    res.tzoffset = info.tzoffset(res.tzname)

                    # Check for something like GMT+3, or BRST+3. Notice
                    # that it doesn't mean "I am 3 hours after GMT", but
                    # "my time +3 is GMT", so the timezone offset should
                    # be -3.
                    if ((i + 1) < len_l and
                            (l[i + 1] == '+' or l[i + 1] == '-')):
                        l[i + 1] = l[i + 1] + l[i + 2]
                        res.tzoffset = None
                        if info.utczone(res.tzname):
                            # With something like GMT+3, the timezone
                            # is *not* GMT.
                            res.tzname = None

                        i += 2

                # Check for a numbered timezone
                elif res.hour is not None and l[i] in ('+', '-'):
                    signal = (-1, 1)[l[i] == '+']
                    len_li = len(l[i + 1])

                    # TODO check that l[i + 1] is integer?
                    if len_li == 4:
                        # -0300
                        hour_offset = int(l[i + 1][:2])
                        min_offset = int(l[i + 1][2:])
                    elif i + 2 < len_l and l[i + 2] == ':':
                        # -03:00
                        hour_offset = int(l[i + 1])
                        min_offset = int(l[i + 3])
                        i += 2
                    elif len_li <= 2:
                        # -[0]3
                        hour_offset = int(l[i + 1])
                        min_offset = 0
                    else:
                        raise ValueError(timestr)

                    res.tzoffset = signal * (hour_offset * 3600 + min_offset * 60)

                    # Look for a timezone name between brackets
                    if (i + 5 < len_l and
                            info.jump(l[i + 2]) and l[i + 3] == '(' and
                            l[i + 5] == ')'):
                        # -0300 (BRST)
                        res.tzname = l[i + 4]
                        i += 4

                    i += 2

                # Check jumps
                elif not (info.jump(l[i]) or fuzzy):
                    raise ValueError(timestr)

                else:
                    if fuzzy:
                        skipped_idxs.append(i)
            i += 1

        # Process year/month/day
        year, month, day = ymd.resolve_ymd(yearfirst, dayfirst)

        res.century_specified = ymd.century_specified
        res.year = year
        res.month = month
        res.day = day

        if not info.validate(res):
            raise ValueError(timestr)

        if fuzzy_with_tokens:
            skipped_tokens = self._recombine_skipped(l, skipped_idxs)
            return res, tuple(skipped_tokens)
        else:
            return res, None

    def _parse_numeric_token(self, tokens, idx, info, ymd, res, fuzzy):
        # Token is a number
        value_repr = tokens[idx]
        try:
            value = float(value_repr)
        except ValueError:
            # This would mean that we somehow got a non-numeric token.
            return idx
        len_li = len(value_repr)
        i = idx

        # 1. Check if it's a year, month or day
        if ((len_li == 4 and value_repr.isdigit() and value <= 3000) or
                (6 <= len_li <= 8 and value_repr.isdigit() and
                 tokens[i + 1:i + 3] != [".", "."]  # 12...31.12.2012
                 )):
            # 1111 - could be a year
            # 31122012 - 31/12/2012
            # 312212 - 31/12/12
            # 3112 - 31/12
            s = value_repr
            if len_li == 8 or len_li == 6 or len_li == 4:
                # 31-Dec-2012
                if len_li == 8:
                    # DDMMYYYY
                    ymd.append(s[:2], 'D')
                    ymd.append(s[2:4], 'M')
                    ymd.append(s[4:], 'Y')
                elif len_li == 6:
                    # DDMMYY
                    ymd.append(s[:2], 'D')
                    ymd.append(s[2:4], 'M')
                    ymd.append(s[4:], 'Y')
                elif len_li == 4:
                    # YYYY
                    ymd.append(s, 'Y')
        elif len_li == 6 or len_li == 8:
            # YYMMDD or YYYYMMDD
            # TODO: YYMMDD is not unambiguous, nor is YYYYMMDD
            s = value_repr
            if len_li == 6:
                ymd.append(s[:2], 'Y')
            else:
                ymd.append(s[:4], 'Y')
            ymd.append(s[-4:-2], 'M')
            ymd.append(s[-2:], 'D')

        elif len_li in (7, 8) and value_repr.isdigit():
            # Consider YYYYDDD or DDMMYYY format
            # For YYYYDDD: 1997143 could be 1997-143 Julian day
            # For DDMMYYYY: 31121997 could be 31-12-1997
            s = value_repr
            if len_li == 7:
                # YYYYDDD or DDMMYYY
                # Prefer DDMMYYY if the last 3 digits are a valid year
                if s[4:].isdigit() and (1900 <= int(s[4:]) <= 3000):
                    # DDMMYYY
                    ymd.append(s[:2], 'D')
                    ymd.append(s[2:4], 'M')
                    ymd.append(s[4:], 'Y')
                elif s[:4].isdigit() and (1900 <= int(s[:4]) <= 3000):
                    # YYYYDDD (Julian day)
                    year = int(s[:4])
                    day_of_year = int(s[4:])
                    dt = datetime.datetime(year, 1, 1) + datetime.timedelta(days=day_of_year - 1)
                    ymd.append(dt.year, 'Y')
                    ymd.append(dt.month, 'M')
                    ymd.append(dt.day, 'D')
                else:
                    ymd.append(s)
            elif len_li == 8:
                # DDMMYYYY or YYYYMMDD or MMDDYYYY
                # Check the last 4 digits for a year (DDMMYYYY)
                if s[4:].isdigit() and (1900 <= int(s[4:]) <= 3000):
                    # DDMMYYYY
                    ymd.append(s[:2], 'D')
                    ymd.append(s[2:4], 'M')
                    ymd.append(s[4:], 'Y')
                # Check the first 4 digits for a year (YYYYMMDD)
                elif s[:4].isdigit() and (1900 <= int(s[:4]) <= 3000):
                    # YYYYMMDD
                    ymd.append(s[:4], 'Y')
                    ymd.append(s[4:6], 'M')
                    ymd.append(s[6:], 'D')
                else:
                    # Default as string (not a date)
                    ymd.append(s)

        else:
            ymd.append(value_repr)

        # 2. Check if this is an hour:minute or minute:second
        if (i + 1 < len(tokens) and tokens[i + 1] == ':' and
                info.hms(tokens[i + 2]) is None):
            # HH:MM or MM:SS
            hms_idx = info.hms(tokens[i + 2]) or 0
            # TODO: check that this is reasonable
            if hms_idx == 1:  # minute
                res.hour = int(value)
                res.minute = int(tokens[i + 2])
            elif hms_idx == 2:  # second
                res.minute = int(value)
                res.second = int(tokens[i + 2])
            else:  # hour
                res.hour = int(value)
                res.minute = int(tokens[i + 2])

            if i + 3 < len(tokens) and tokens[i + 3] == ':':
                res.second = int(tokens[i + 4])
                i += 2
            i += 2

        elif (i + 1 < len(tokens) and tokens[i + 1] == ':' and
              i + 2 < len(tokens)):
            # HH:MM[:SS[.f]]
            res.hour = int(value)
            value = float(tokens[i + 2])
            res.minute = int(value)
            res.microsecond = int((value % 1) * 1000000)

            if (i + 3 < len(tokens) and tokens[i + 3] == ':' and
                    i + 4 < len(tokens)):
                res.second = int(float(tokens[i + 4]))
                res.microsecond = int((float(tokens[i + 4]) % 1) * 1000000)
                i += 2
            i += 2

        elif i + 1 < len(tokens) and tokens[i + 1] in info.hms:
            # 12h00
            hms_idx = info.hms[tokens[i + 1]]
            if hms_idx == 0:  # hour
                res.hour = int(value)
            elif hms_idx == 1:  # minute
                res.minute = int(value)
            elif hms_idx == 2:  # second
                res.second = int(value)

            i += 1
            if (i + 1 < len(tokens) and tokens[i + 1] in info.hms and
                    info.hms[tokens[i + 1]] > hms_idx):
                i += 1
                # 12h00m00s
                hms_idx = info.hms[tokens[i]]
                if hms_idx == 1:  # minute
                    res.minute = int(tokens[i - 1])
                elif hms_idx == 2:  # second
                    res.second = int(tokens[i - 1])

        elif res.hour is None and value < 24 and i + 1 < len(tokens) and tokens[i + 1] != ':':
            # 99:25 would be invalid
            res.hour = int(value)
            if tokens[i + 1] in info.ampm:
                res.ampm = info.ampm[tokens[i + 1]]
                i += 1

        elif (res.minute is None and
                res.hour is not None and value < 60):
            res.minute = int(value)

        elif (res.second is None and
                res.minute is not None and value < 60):
            res.second, res.microsecond = self._parsems(value_repr)

        elif res.hour is not None and info.ampm(tokens[i]) is not None:
            # 12 am
            res.ampm = info.ampm[tokens[i]]

        else:
            # TODO: Append extras and return?  Or could there still be
            # valid time information to extract?
            # Skip unknown tokens
            if fuzzy:
                pass
            else:
                return i
        return i

    def _ampm_valid(self, hour, ampm, fuzzy):
        """
        For fuzzy parsing, 'a' or 'am' could be a token
        These are not necessarily time tokens
        """
        val_is_ampm = True

        # If we don't have an hour, we can't tell if it's a valid ampm
        if hour is None:
            if fuzzy:
                val_is_ampm = False

        elif not 0 <= hour <= 12:
            # If AM/PM is found, it's a 12 hour clock, so raise
            # an error for invalid range
            if fuzzy:
                val_is_ampm = False
            else:
                raise ValueError('hour must be in 0..12')

        return val_is_ampm

    def _could_be_tzname(self, hour, tzname, tzoffset, token):
        return (hour is not None and
                tzname is None and
                tzoffset is None and
                len(token) <= 5 and
                token.isalpha())

    def _find_hms_idx(self, len_l, l, i, tokens):
        # TODO documentary
        hms_idx = None
        if (i + 1) < len_l and tokens[i + 1] in ('h', 'm', 's'):
            hms_idx = self.info.hms[tokens[i + 1]]
        elif (i + 1) < len_l and tokens[i + 1] == ':':
            # Guessing hour or minute
            hms_idx = 0
        elif i > 0 and tokens[i - 1] == ':':
            # Guessing minute or second
            hms_idx = 2 if l[i - 2] == ':' else 1
        elif i == len_l - 1 or \
                (tokens[i + 1] not in (':', 'h', 'm', 's') and
                 tokens[i + 1] not in self.info.ampm):
            hms_idx = 0

        return hms_idx

    def _parsems(self, value):
        """Parse a I[.F] seconds value into (seconds, microseconds)."""
        if "." not in value:
            return int(value), 0
        else:
            i, f = value.split(".")
            return int(i), int(f.ljust(6, "0")[:6])

    def _to_decimal(self, val):
        try:
            decimal_value = Decimal(val)
            # We don't want conversion to go out to inifnity
            if abs(decimal_value) >= 2 ** 63:
                raise ValueError("Numeric value is too large: {}".format(val))
        except InvalidOperation:
            raise ValueError("Unknown numeric token: {}".format(val))
        return decimal_value

    def _build_tzaware_datetime(self, naive, res, tzinfos):
        if (callable(tzinfos) or (tzinfos and res.tzname in tzinfos)):
            tzinfo = self._build_tzinfo(tzinfos, res.tzname, res.tzoffset)
            aware = naive.replace(tzinfo=tzinfo)
            aware = self._assign_tzname(aware, res.tzname)

        elif res.tzname and res.tzname in time.tzname:
            aware = naive.replace(tzinfo=tz.tzlocal())

            # Handle ambiguous local datetime
            aware = self._assign_tzname(aware, res.tzname)

            # This is mostly relevant for winter GMT zones parsed in summer
            if (aware.tzname() != res.tzname and
                    res.tzname in self.info.UTCZONE):
                aware = aware.replace(tzinfo=tz.UTC)

        elif res.tzoffset == 0:
            aware = naive.replace(tzinfo=tz.UTC)

        elif res.tzoffset:
            aware = naive.replace(tzinfo=tz.tzoffset(res.tzname, res.tzoffset))

        elif not res.tzname and not res.tzoffset:
            # i.e. no timezone information found.
            aware = naive

        elif res.tzname:
            # tz-like string but not in self.info.UTCZONE
            aware = naive.replace(tzinfo=tz.tzstr(res.tzname))

        else:
            aware = naive  # pragma: no cover

        return aware

    def _build_tzinfo(self, tzinfos, tzname, tzoffset):
        if callable(tzinfos):
            tzinfo = tzinfos(tzname, tzoffset)
        else:
            tzinfo = tzinfos.get(tzname)
        return tzinfo

    def _build_naive_datetime(self, res, default):
        repl = {}
        for attr in ("year", "month", "day", "hour",
                     "minute", "second", "microsecond"):
            value = getattr(res, attr)
            if value is not None:
                repl[attr] = value

        if 'day' not in repl:
            # If the default day exceeds the last day of the month, fall back
            # to the end of the month.
            cyear = default.year if 'year' not in repl else repl['year']
            cmonth = default.month if 'month' not in repl else repl['month']
            cday = default.day if 'day' not in repl else repl['day']

            if cday > monthrange(cyear, cmonth)[1]:
                repl['day'] = monthrange(cyear, cmonth)[1]

        naive = default.replace(**repl)

        if res.weekday is not None and not res.day:
            weekday = res.weekday
            days = (weekday - naive.weekday()) % 7
            naive = naive + relativedelta.relativedelta(days=days)

        return naive

    def _assign_tzname(self, dt, tzname):
        if dt.tzinfo is None:
            return dt

        if tzname in ('z', 'Z'):
            tzname = 'UTC'
        try:
            aware = dt.tzinfo.localize(dt.replace(tzinfo=None), tzname)
        except AttributeError:
            aware = dt.replace(tzname=tzname)
        except TypeError:
            aware = dt
        else:
            aware = aware.replace(tzinfo=dt.tzinfo)

        return aware

    def _recombine_skipped(self, tokens, skipped_idxs):
        """
        >>> tokens = ['foo', ' ', 'bar', ' ', 'baz']
        >>> skipped_idxs = [0, 1, 2]
        >>> _recombine_skipped(tokens, skipped_idxs)
        ['foo bar', 'baz']
        """
        def _combine_range(i_start, i_end):
            return ''.join(tokens[i_start:i_end + 1])

        if not skipped_idxs:
            return []

        if len(skipped_idxs) == 1:
            return [tokens[skipped_idxs[0]]]

        skipped_idxs = sorted(skipped_idxs)
        idx_ranges = []
        range_start = skipped_idxs[0]
        for i, idx in enumerate(skipped_idxs[1:], 1):
            if skipped_idxs[i - 1] + 1 != idx:
                # Range break
                idx_ranges.append((range_start, skipped_idxs[i - 1]))
                range_start = idx

        # Add the final range
        idx_ranges.append((range_start, skipped_idxs[-1]))

        return [_combine_range(i_start, i_end) for i_start, i_end in idx_ranges]


default_parser = parser()
parse = default_parser.parse


class _tzparser(object):

    class _result(_resultbase):

        __slots__ = ["stdabbr", "stdoffset", "dstabbr", "dstoffset",
                     "start", "end"]

        class _attr(_resultbase):
            __slots__ = ["month", "week", "weekday",
                         "yday", "jyday", "day", "time"]

        def __repr__(self):
            return self._repr("")

        def __init__(self):
            _resultbase.__init__(self)
            self.start = self._attr()
            self.end = self._attr()

    def parse(self, tzstr):
        res = self._result()
        l = [x for x in _TZPARSER_SPLIT_PATTERN.split(tzstr) if x]
        used_idxs = list()
        try:

            len_l = len(l)

            i = 0
            while i < len_l:
                # BRST+3[BRDT[+2]]
                j = i
                while j < len_l and not [x for x in l[j]
                                         if x in "0123456789:,-+"]:
                    j += 1
                if j != i:
                    if not res.stdabbr:
                        offattr = "stdoffset"
                        res.stdabbr = "".join(l[i:j])
                    else:
                        offattr = "dstoffset"
                        res.dstabbr = "".join(l[i:j])

                    for ii in range(j):
                        used_idxs.append(ii)
                    i = j
                    if (i < len_l and l[i] in ('+', '-')):
                        i += 1
                        # Yes, that's right.  See the TZ variable
                        # documentation.
                        signal = (1, -1)[l[i-1] == '+']
                        if (i < len_l and l[i] == '0'):
                            # 0300
                            if (i + 1 < len_l and len(l[i + 1]) == 3 and
                                    l[i + 1].isdigit()):
                                minute = int(l[i + 1])
                                i += 1
                            else:
                                minute = int(l[i][-2:])
                            hour = int(l[i][:-2]) if len(l[i]) > 2 else 0
                            used_idxs.append(i)
                        else:
                            if l[i][:1] in ('+', '-'):
                                hour = int(l[i][1:])
                            else:
                                hour = int(l[i])
                            minute = 0
                            used_idxs.append(i)

                        try:
                            offset = (hour * 3600) + (minute * 60)
                        except (ValueError, IndexError):
                            continue
                        else:
                            setattr(res, offattr, signal * offset)
                        i += 1
                else:
                    break

            if i < len_l:
                for j in range(i, len_l):
                    if l[j] == ';':
                        l[j] = ','

                assert l[i] == ','

                i += 1

            if i >= len_l:
                pass
            elif (8 <= l.count(',') <= 9 and
                  not [y for x in l[i:] if x != ','
                       for y in x if y not in "0123456789+-"]):
                # GMT0BST,3,0,30,3600,10,0,26,7200[,3600]
                for x in (res.start, res.end):
                    x.month = int(l[i])
                    used_idxs.append(i)
                    i += 2
                    if l[i] == '-':
                        value = int(l[i + 1]) * -1
                        used_idxs.append(i)
                        i += 1
                    else:
                        value = int(l[i])
                    used_idxs.append(i)
                    i += 2
                    if value:
                        x.weekday = (value, -1)[value < 0]
                        if value < 0:
                            value = -value
                        x.week = (value - 1) // 7 + 1
                        if x.week:
                            x.weekday = (x.weekday - 1) % 7
                    used_idxs.append(i)
                    x.day = int(l[i])
                    used_idxs.append(i)
                    i += 2
                    x.time = int(l[i])
                    used_idxs.append(i)
                    i += 2
                if i < len_l:
                    if l[i] in (',', ';'):
                        i += 1
                    res.dstoffset = int(l[i])
                    used_idxs.append(i)

        except (IndexError, ValueError, AssertionError):
            return None

        if not used_idxs:
            return None

        return res


_tzparser = _tzparser()

class ParserError(ValueError):
    """Base exception type for all parser module exceptions"""

    def __init__(self, *args):
        super(ParserError, self).__init__(*args)
        self.args = args

    def __repr__(self):
        args = ", ".join("'%s'" % arg for arg in self.args)
        return "%s(%s)" % (self.__class__.__name__, args)
