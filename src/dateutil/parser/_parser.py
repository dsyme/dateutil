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
from io import StringIO

import six
from six import integer_types, text_type

from decimal import Decimal

from warnings import warn

from .. import relativedelta
from .. import tz

__all__ = ["parse", "parserinfo", "ParserError"]

# Pre-compiled regex pattern to quickly identify common ISO 8601 formats
# that can be handled efficiently by the isoparser  
# Conservative pattern that only matches unambiguous ISO 8601 formats
_ISO_8601_PATTERN = re.compile(r'^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2})(?::(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?)?(?:Z|[+-]\d{2}(?::\?\d{2})?)?$|^(\d{8})(?:T(\d{6})(?:[.,](\d+))?)?(?:Z|[+-]\d{2}(?::\?\d{2})?)?$')

# Import isoparse for fast-path optimization
from .isoparser import isoparse


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
        any dot-separated strings before breaking it into tokens; as such, this
        function maintains a "token stack", for when the ambiguous context
        demands that multiple tokens be parsed at once.
        """
        if self.tokenstack:
            return self.tokenstack.pop(0)

        seenletters = False
        token = None
        state = None

        while not self.eof:
            # We only realize that we've reached the end of a token when we
            # find a character that's not part of the current token - since
            # we're reading one character at a time, and tokens are
            # contiguous, this is necessarily the first character of the next
            # token. So we need to keep track of this character somehow.
            nextchar = self.get_char()
            if nextchar is None:
                self.eof = True
                break

            while nextchar is not None:
                if nextchar.isalnum():
                    # Legal in a token
                    pass
                elif nextchar in '.-_':
                    # Also legal in a token
                    if nextchar == '-' and not seenletters:
                        nextchar = self.get_char()
                        if nextchar is None or not nextchar.isdigit():
                            break
                        # else: "-" + isdigit(nextchar) is legal
                elif nextchar.isspace():
                    self.push_char(nextchar)
                    break
                else:
                    # Character not legal in a token
                    self.push_char(nextchar)
                    break

                if state is None:
                    # First character of the token - determines if we're going
                    # to be parsing a word or a number.
                    if nextchar.isalpha():
                        state = "a"
                        seenletters = True
                    elif nextchar.isdigit():
                        state = "0"
                    elif nextchar in '.-':
                        state = "0"
                    else:
                        # WTF
                        pass

                elif state == "a":
                    # If we've already seen at least one letter, we're in
                    # 'date' mode - letters, digits and dots are all legal
                    seenletters = True

                elif state == "0":
                    # If we've seen some digits, we're in 'number' mode.
                    # Digits, dots, and letters are legal (e.g. "1st")
                    if nextchar.isalpha():
                        state = "a"
                        seenletters = True

                token = (token or "") + nextchar
                nextchar = self.get_char()

            # If we've reached the end of the stream or broken out of the
            # character reading loop, return the token, unless it's empty.
            if token:
                break

        if token is None:
            token = ""

        if state in ("a", None) and seenletters:
            return token
        elif token and token[0].isdigit():
            return self.handle_decimal_point(token)
        else:
            return token

    def handle_decimal_point(self, token):
        """
        This function handles the ambiguous dots in number parsing.
        """
        for m in self._split_decimal.finditer(token):
            if m.span() != (0, 0):
                break
        else:
            return token

        dot_char, dot_idx = m.group(1), m.start(1)
        # If the token is all dots, return it
        if token.replace(dot_char, '') == '':
            return token
        # If we find a dot in the token, the token up to that point is a legal
        # number; everything following the dot are separate tokens.
        self.tokenstack.append(token[dot_idx + 1:])
        token = token[:dot_idx + 1]
        return token

    def get_char(self):
        if self.charstack:
            return self.charstack.pop(0)
        return self.instream.read(1) or None

    def push_char(self, char):
        self.charstack.append(char)

    def __iter__(self):
        return self

    def __next__(self):
        token = self.get_token()
        if token:
            return token
        else:
            raise StopIteration

    def next(self):
        return self.__next__()  # Python 2.x support

    def split(self, s):
        return list(self)


class _resultbase(object):
    """
    Abstract base class for parser result objects.
    """

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
        return (sum(getattr(self, attr) is not None
                    for attr in self.__slots__))

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

    JUMP = [
        " ", ".", ",", ";", "-", "/", "'",
        "at", "on", "and", "ad", "m", "t", "of",
        "st", "nd", "rd", "th"
    ]

    WEEKDAYS = [
        ("Mon", "Monday"),
        ("Tue", "Tuesday"), # TODO: "Tues"
        ("Wed", "Wednesday"),
        ("Thu", "Thursday"), # TODO: "Thurs"
        ("Fri", "Friday"),
        ("Sat", "Saturday"),
        ("Sun", "Sunday")
    ]
    MONTHS = [
        ("Jan", "January"),
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
        ("Dec", "December")
    ]
    HMS = [
        ("h", "hour", "hours"),
        ("m", "minute", "minutes"),
        ("s", "second", "seconds")
    ]
    AMPM = [
        ("am", "a"),
        ("pm", "p")
    ]
    UTCZONE = ["UTC", "GMT", "Z", "z"]
    PERTAIN = ["of"]
    TZOFFSET = {}
    # TODO: ERA = ["AD", "BC", "CE", "BCE"]

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
        return self._weekdays.get(name.lower())

    def month(self, name):
        return self._months.get(name.lower())

    def hms(self, name):
        return self._hms.get(name.lower())

    def ampm(self, name):
        return self._ampm.get(name.lower())

    def pertain(self, name):
        return name.lower() in self._pertain

    def utczone(self, name):
        return name.lower() in self._utczone

    def tzoffset(self, name):
        if name in self._utczone:
            return 0

        return self.TZOFFSET.get(name)

    def convertyear(self, year, century_specified=False):
        if year < 100 and not century_specified:
            year += self._century
            if year >= self._year + 50:  # TODO: make this configurable
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


class _ymd:
    def __init__(self, *args, **kwargs):
        if args:
            if len(args) != 3:
                raise TypeError(
                    '__init__ expected at most 3 arguments, got {n}'.format(
                        n=len(args)))
            self._ymd = list(args)
        else:
            self._ymd = [None, None, None]

        if any(x is not None and not isinstance(x, integer_types)
               for x in self._ymd):
            raise TypeError("an integer is required (got type {})".
                            format(type(x)))

        for attr, val in kwargs.items():
            if attr not in ('year', 'month', 'day'):
                raise TypeError('Unsupported keyword: {}'.format(attr))

            setattr(self, attr, val)

    @property
    def year(self):
        return self._ymd[0]

    @year.setter
    def year(self, val):
        if val is not None and not isinstance(val, integer_types):
            raise TypeError("an integer is required (got type {})".
                            format(type(val)))
        self._ymd[0] = val

    @property
    def month(self):
        return self._ymd[1]

    @month.setter
    def month(self, val):
        if val is not None and not isinstance(val, integer_types):
            raise TypeError("an integer is required (got type {})".
                            format(type(val)))
        self._ymd[1] = val

    @property
    def day(self):
        return self._ymd[2]

    @day.setter
    def day(self, val):
        if val is not None and not isinstance(val, integer_types):
            raise TypeError("an integer is required (got type {})".
                            format(type(val)))
        self._ymd[2] = val

    def could_be_day(self, val):
        if val is None or val > 31:
            return False

        return True

    def append(self, val, label=None):
        assert hasattr(val, '__int__')
        val = int(val)

        assert val is not None

        if label == 'M' or label == 'month' or (
                label is None and self.month is None and self.could_be_day(val)):
            self.month = val
        elif label == 'D' or label == 'day' or (
                label is None and self.day is None and self.could_be_day(val)):
            self.day = val
        elif label == 'Y' or label == 'year':
            self.year = val
        elif label is None:
            if self.year is None:
                self.year = val
            elif self.month is None:
                self.month = val
            elif self.day is None:
                self.day = val
            else:
                raise ValueError()
        else:
            raise ValueError()

    def __getitem__(self, ix):
        return self._ymd[ix]

    def __setitem__(self, ix, val):
        self._ymd[ix] = val

    def __iter__(self):
        return iter(self._ymd)

    def __len__(self):
        return 3

    def __bool__(self):
        return any(x is not None for x in self._ymd)

    __nonzero__ = __bool__

    def __repr__(self):
        return 'ymd' + repr(tuple(self._ymd))

    def resolve_ymd(self, yearfirst, dayfirst):
        len_ymd = len([x for x in self._ymd if x is not None])
        year, month, day = self._ymd

        result = _ymd()

        if (len_ymd == 3 and any(x is None for x in (year, month, day))):
            # Shouldn't happen, but...
            raise ValueError("Found 3 date components with incomplete "
                             "information")

        if len_ymd == 1 or (month is None and day is None):
            # ~1999
            result.year = year
        elif len_ymd == 2:
            # 1999-01; 01-1999
            if month is None:
                if dayfirst and year is not None and day is not None:
                    result.day, result.year = day, year
                else:
                    result.month, result.year = day, year
            elif day is None:
                if yearfirst and year is not None and month is not None:
                    result.year, result.month = year, month
                else:
                    result.month, result.year = year, month
            else:
                # WTF!?
                raise ValueError("Two date components specified twice")
        elif len_ymd == 3:
            # 1999-01-01
            if yearfirst:
                if dayfirst and year is not None and month is not None:
                    result.year, result.day, result.month = year, month, day
                else:
                    result.year, result.month, result.day = year, month, day
            else:
                # If dayfirst, assume day, month, year
                # Otherwise, assume month, day, year
                if dayfirst:
                    result.day, result.month, result.year = year, month, day
                else:
                    result.month, result.day, result.year = year, month, day

        return result

    def has_year(self):
        return self.year is not None

    def has_month(self):
        return self.month is not None

    def has_day(self):
        return self.day is not None

    def mmdd(self):
        """
        Whether this is a ``MMDD`` ambiguous date.
        """
        return (self.month is not None and
                self.day is not None and
                self.year is None)

    def is_ambiguous_day(self, other):
        """
        Whether this date has same year/month but different day from another
        date, requiring a hint to resolve the ambiguity.
        """
        return (self.year == other.year and
                self.month == other.month and
                self.day != other.day and
                self.day is not None and
                other.day is not None)


class parser:
    def __init__(self, info=None):
        self.info = info or parserinfo()

    def parse(self, timestr, default=None,
              ignoretz=False, tzinfos=None, **kwargs):
        """
        Parse the date/time string into a :class:`datetime.datetime` object.

        :param timestr:
            Any date/time string which can be parsed by the dateutil parser.
            For example: ``'12/31/2010'``, ``'T10:15'``, ``'Wed, 31 Dec 2010 21:45:37 -0500'``

        :param default:
            The default datetime object, if this is a datetime object and not
            ``None``, elements specified in the ``timestr`` replace elements in the
            default object.

        :param ignoretz:
            If set ``True``, time zones in parsed strings are ignored and a
            naive :class:`datetime` object is returned.

        :param tzinfos:
            Additional time zone names / aliases which may be present in the
            string. This argument maps time zone names (and optionally offsets
            from those time zones) to time zones. This parameter can be a
            dictionary with timezone aliases mapping time zone names to time
            zones or a function taking two parameters (``tzname`` and
            ``tzoffset``) and returning a time zone.

            The timezones to which the names are mapped can be an integer
            offset from UTC in seconds or a :class:`tzinfo` object.

            .. doctest::
               :options: +NORMALIZE_WHITESPACE

                >>> from dateutil.parser import parse
                >>> from dateutil.tz import gettz
                >>> tzinfos = {"BRST": -7200, "CST": gettz("America/Chicago")}
                >>> parse("2012-01-19 17:21:00 BRST", tzinfos=tzinfos)
                datetime.datetime(2012, 1, 19, 17, 21, tzinfo=tzoffset(u'BRST', -7200))
                >>> parse("2012-01-19 17:21:00 CST", tzinfos=tzinfos)
                datetime.datetime(2012, 1, 19, 17, 21,
                                  tzinfo=tzfile('/usr/share/zoneinfo/America/Chicago'))

            This parameter is ignored if ``ignoretz`` is set.

        :param kwargs:
            Keyword arguments as passed to ``_parse()``.

        :return:
            Returns a :class:`datetime.datetime` object or, if the
            ``fuzzy_with_tokens`` option is ``True``, returns a tuple, the
            first element being a :class:`datetime.datetime` object, the second
            a tuple containing the fuzzy tokens.

        :raises ParserError:
            Raised for invalid or unknown string formats, if the provided
            :class:`tzinfo` is not in a valid format, or if an invalid date
            would be created.

        :raises OverflowError:
            Raised if the parsed date exceeds the largest valid C integer on
            your system.
        """
        if default is None:
            default = datetime.datetime.now().replace(hour=0, minute=0,
                                                      second=0, microsecond=0)

        res, skipped_tokens = self._parse(timestr, **kwargs)

        if res is None:
            raise ParserError("Unknown string format: %s" % timestr)

        if len(res) == 0:
            raise ParserError("String does not contain a date: %s" % timestr)

        ret = self._build_naive(res, default)

        if not ignoretz:
            ret = self._build_tzaware(ret, res, tzinfos)

        if kwargs.get('fuzzy_with_tokens', False):
            return ret, tuple(skipped_tokens)
        else:
            return ret

    class _result(_resultbase):
        __slots__ = ["year", "month", "day", "weekday",
                     "hour", "minute", "second", "microsecond",
                     "tzname", "tzoffset", "ampm", "any_unused_tokens",
                     "century_specified"]

    def _parse(self, timestr, dayfirst=None, yearfirst=None, fuzzy=False,
               fuzzy_with_tokens=False):
        """
        Private method which performs the heavy lifting of parsing, called from
        ``parse()``, which passes on its ``kwargs`` to this function.
        """
        info = self.info

        if dayfirst is None:
            dayfirst = info.dayfirst

        if yearfirst is None:
            yearfirst = info.yearfirst

        res = self._result()
        l = _timelex(timestr)      # Splits the timestr into tokens

        skipped_idxs = []

        # year/month/day list
        ymd = _ymd()

        len_l = 0
        for i, token in enumerate(l):
            len_l += 1
            if token in (None, ""):
                continue

            # Check if it's a number
            value_repr = token
            try:
                value = Decimal(token)
            except ValueError:
                value = None

            if value is not None:
                # Numeric token
                i_value = int(value)
                f_value = float(value)

                token = token.lower()

                if ((res.hour is None or res.minute is None or res.second is None)
                    and len(token) <= 2 and
                        token.isdigit() and value < 60):
                    # Could be hour/minute/second
                    if res.hour is None:
                        res.hour = i_value
                    elif res.minute is None:
                        res.minute = i_value
                    elif res.second is None:
                        res.second = i_value
                    else:
                        # If we're here, we have all three values filled
                        pass
                elif (res.tzoffset is None
                      and ((i_value in (-500, -400, -300, -200, -100, 0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200))
                           or (len(token) == 4 and token.isdigit()))):
                    # GMT (+/-###) or four digit timezone offset (+/-####)
                    res.tzoffset = i_value
                    if i_value < 100:
                        i_value *= 3600
                    else:
                        # Use floor division
                        i_value = ((i_value // 100) * 3600 +
                                   (i_value % 100) * 60)
                    res.tzoffset = int(i_value)

                elif res.weekday is None and len(token) == 1:
                    try:
                        res.weekday = int(token) % 7
                    except ValueError:
                        pass

                else:
                    ymd.append(i_value)

            elif info.jump(token):
                continue

            elif info.weekday(token) is not None:
                value = info.weekday(token)
                res.weekday = value

            elif info.month(token) is not None:
                value = info.month(token) + 1
                ymd.append(value, 'M')

            elif info.hms(token) is not None:
                # TODO: Definitely need to write
                # tests for this.  An "hour" in a date string
                # could come after or before "hour" indicators
                # and still be valid.
                try:
                    ampm = info.ampm(l[i+1])
                except IndexError:
                    ampm = None

                # For fuzzy parsing, 'a' or 'am' could be part of a
                # fuzzy word like "again", so we also check that the
                # previous token is a number.
                if ampm is not None and isinstance(value, Decimal):
                    # For 12 hour clock format, the hour must be <= 12
                    if i_value <= 12:
                        if ampm == 1 and i_value != 12:
                            i_value += 12
                        elif ampm == 0 and i_value == 12:
                            i_value = 0

                        res.ampm = ampm

                        # TODO: What happens if the hour is 13?
                        # e.g. "13h am"

                idx = info.hms(token)
                if idx == 0:
                    res.hour = i_value
                elif idx == 1:
                    res.minute = i_value
                elif idx == 2:
                    res.second = i_value

            elif info.ampm(token) is not None and (0 <= res.hour <= 12):
                # For fuzzy parsing, 'a' or 'am' could be part of a
                # fuzzy word like "again", so we also check that
                # it is reasonable.
                ampm = info.ampm(token)
                if ampm == 1 and res.hour < 12:
                    res.hour += 12
                elif ampm == 0 and res.hour == 12:
                    res.hour = 0
                res.ampm = ampm

            elif not fuzzy:
                # TODO: Tokens that are not handled above are appended to the
                # list ``skipped_tokens``. For backwards compatibility, this
                # functionality will only be used in fuzzy parsing where we
                # expect to encounter such tokens. In the future, we should
                # have a better way of providing warnings when parsing fails.
                if skipped_idxs is None:
                    skipped_idxs = []

                skipped_idxs.append(i)

        # TODO: AM/PM
        # TODO: Seconds with AM/PM?

        # Parse date
        ymd = ymd.resolve_ymd(yearfirst, dayfirst)

        res.century_specified = False
        if ymd.year is not None:
            res.year = ymd.year

            if len(str(res.year)) > 2:
                res.century_specified = True

        if ymd.month is not None:
            res.month = ymd.month

        if ymd.day is not None:
            res.day = ymd.day

        # TODO: Check for invalid dates like Feb 31st
        # TODO: Check for multiple time designators (which is an error)
        # TODO: Check for multiple date separators (which is an error)
        # TODO: Check for invalid combinations like "a.m. p.m."

        if not info.validate(res):
            raise ParserError("Failed to parse date")

        if fuzzy_with_tokens:
            skipped_tokens = l[1:] if skipped_idxs is None else [l[i] for i in skipped_idxs]
        else:
            skipped_tokens = None

        return res, skipped_tokens

    def _build_naive(self, res, default):
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

        ret = default.replace(**repl)
        return ret

    def _build_tzaware(self, naive, res, tzinfos):
        if (callable(tzinfos) or (tzinfos and res.tzname in tzinfos)):

            tzinfo = None
            tzname = res.tzname
            tzoffset = res.tzoffset

            if callable(tzinfos):
                tzdata = tzinfos(tzname, tzoffset)
            else:
                tzdata = tzinfos.get(tzname)

            if isinstance(tzdata, datetime.tzinfo):
                tzinfo = tzdata
            elif isinstance(tzdata, text_type):
                tzinfo = tz.tzstr(tzdata)
            elif isinstance(tzdata, integer_types):
                tzinfo = tz.tzoffset(tzname, tzdata)
            else:
                raise ValueError("Offset must be tzinfo subclass, "
                                 "tz string, or int offset.")
            ret = naive.replace(tzinfo=tzinfo)
        elif res.tzname and res.tzname in time.tzname:
            ret = naive.replace(tzinfo=tz.tzlocal())
        elif res.tzoffset == 0:
            ret = naive.replace(tzinfo=tz.tzutc())
        elif res.tzoffset:
            ret = naive.replace(tzinfo=tz.tzoffset(res.tzname, res.tzoffset))
        else:
            ret = naive

        return ret


DEFAULTPARSER = parser()


def parse(timestr, parserinfo=None, **kwargs):
    """

    Parse a string in one of the supported formats, using the
    ``parserinfo`` parameters.

    :param timestr:
        A string containing a date/time stamp.

    :param parserinfo:
        A :class:`parserinfo` object containing parameters for the parser.
        If ``None``, the default arguments to the :class:`parserinfo`
        constructor are used.

    The ``**kwargs`` parameter takes the following keyword arguments:

    :param default:
        The default datetime object, if this is a datetime object and not
        ``None``, elements specified in ``timestr`` replace elements in the
        default object.

    :param ignoretz:
        If set ``True``, time zones in parsed strings are ignored and a naive
        :class:`datetime` object is returned.

    :param tzinfos:
        Additional time zone names / aliases which may be present in the
        string. This argument maps time zone names (and optionally offsets
        from those time zones) to time zones. This parameter can be a
        dictionary with timezone aliases mapping time zone names to time
        zones or a function taking two parameters (``tzname`` and
        ``tzoffset``) and returning a time zone.

        The timezones to which the names are mapped can be an integer
        offset from UTC in seconds or a :class:`tzinfo` object.

        .. doctest::
           :options: +NORMALIZE_WHITESPACE

            >>> from dateutil.parser import parse
            >>> from dateutil.tz import gettz
            >>> tzinfos = {"BRST": -7200, "CST": gettz("America/Chicago")}
            >>> parse("2012-01-19 17:21:00 BRST", tzinfos=tzinfos)
            datetime.datetime(2012, 1, 19, 17, 21, tzinfo=tzoffset(u'BRST', -7200))
            >>> parse("2012-01-19 17:21:00 CST", tzinfos=tzinfos)
            datetime.datetime(2012, 1, 19, 17, 21,
                              tzinfo=tzfile('/usr/share/zoneinfo/America/Chicago'))

        This parameter is ignored if ``ignoretz`` is set.

    :param dayfirst:
        Whether to interpret the first value in an ambiguous 3-integer date
        (e.g. 01/05/09) as the day (``True``) or month (``False``). If
        ``yearfirst`` is set to ``True``, this distinguishes between YDM and
        YMD. Default is ``False``.

    :param yearfirst:
        Whether to interpret the first value in an ambiguous 3-integer date
        (e.g. 01/05/09) as the year. If ``True``, the first number is taken
        to be the year, otherwise the last number is taken to be the year.
        Default is ``False``.

    :param fuzzy:
        Whether to allow fuzzy parsing, allowing for string like "Today is
        January 1, 2047 at 8:21:00AM".

    :param fuzzy_with_tokens:
        If ``True``, parsing will be fuzzy but will return a tuple where the
        first element is the parsed :class:`datetime.datetime` datetimeand the
        second element is a tuple containing the portions of the string which
        were ignored:

        .. doctest::

            >>> from dateutil.parser import parse
            >>> parse("Today is January 1, 2047 at 8:21:00AM", fuzzy_with_tokens=True)
            (datetime.datetime(2047, 1, 1, 8, 21), (u'Today is ', u' at '))

    :return:
        Returns a :class:`datetime.datetime` object or, if the
        ``fuzzy_with_tokens`` option is ``True``, returns a tuple, the
        first element being a :class:`datetime.datetime` object, the second
        a tuple containing the fuzzy tokens.

    :raises ParserError:
        Raised for invalid or unknown string formats, if the provided
        :class:`tzinfo` is not in a valid format, or if an invalid date would
        be created.

    :raises OverflowError:
        Raised if the parsed date exceeds the largest valid C integer on
        your system.
    """
    # Fast-path optimization: try isoparser first for common ISO 8601 formats
    # This avoids the overhead of the general parser for simple, common cases
    if (parserinfo is None and 
        isinstance(timestr, (str, text_type)) and 
        _ISO_8601_PATTERN.match(timestr.strip())):
        try:
            # Only use fast-path if no special parameters are used
            # isoparse only handles the datetime string, no other parameters
            if not kwargs:
                return isoparse(timestr.strip())
        except (ValueError, TypeError):
            # If isoparser fails, fall back to general parser
            pass
    
    if parserinfo:
        return parser(parserinfo).parse(timestr, **kwargs)
    else:
        return DEFAULTPARSER.parse(timestr, **kwargs)


class _tzparser(object):

    class _result(_resultbase):
        __slots__ = ["stdabbr", "stdoffset", "dstabbr", "dstoffset",
                     "start", "end"]

        class _dsttrans(_resultbase):
            __slots__ = ["month", "week", "weekday",
                         "day", "hour", "minute", "second",
                         "isodst"]

    def parse(self, tzstr):
        res = self._result()

        l = _timelex(tzstr)
        try:

            len_l = len(l)
            i = 0
            while i < len_l:
                # TODO: check that this is correct
                value_repr = l[i]
                i += 1
                if value_repr:
                    if value_repr[0].isalpha():
                        # TODO: check that this is correct
                        j = i-1
                        while j < len_l and l[j]:
                            for k, tzname in enumerate((res.stdabbr, res.dstabbr)):
                                if tzname == l[j]:
                                    break
                            else:
                                if res.stdabbr is None:
                                    res.stdabbr = l[j]
                                elif res.dstabbr is None:
                                    res.dstabbr = l[j]
                                else:
                                    raise ParserError("Too many time zone names")
                            j += 1
                        i = j
                    else:
                        break

            if i < len_l:
                for j in range(i, len_l):
                    if l[j] is not None:
                        break
                else:
                    i = len_l

            # TODO: check that this is correct
            if i >= len_l:
                pass
            elif (l[i] is None or l[i].isspace()):
                i += 1
            else:
                return None

            if i >= len_l:
                pass
            elif res.stdabbr is not None:
                if l[i][0].isdigit():
                    # TODO: check that this is correct
                    res.stdoffset = int(l[i]) * 3600
                    i += 1
                else:
                    return None
            else:
                return None

            if i >= len_l:
                pass
            elif (l[i] is None or l[i].isspace()):
                i += 1
            else:
                return None

            if i >= len_l:
                if res.dstabbr:
                    res.dstoffset = res.stdoffset + 3600
            elif res.dstabbr is not None:
                if l[i][0].isdigit():
                    # TODO: check that this is correct
                    res.dstoffset = int(l[i]) * 3600
                    i += 1
                else:
                    return None
            else:
                return None

            if i >= len_l:
                pass
            elif (l[i] is None or l[i].isspace()):
                i += 1
            else:
                return None

            if i >= len_l:
                pass
            elif res.dstabbr is not None:
                if l[i].startswith('J'):
                    # non-leap year Julian day
                    value_repr = l[i][1:]
                    if not value_repr:
                        i += 1
                        value_repr = l[i]
                    # TODO: check that this is correct
                    value = int(value_repr)
                    res.start = self._result._dsttrans()
                    picknthweekday(value, res.start, 0)
                    i += 1
                elif l[i][0].isdigit():
                    # leap year Julian day
                    # TODO: check that this is correct
                    value = int(l[i])
                    res.start = self._result._dsttrans()
                    res.start.day = value
                    i += 1
                elif l[i][0] == 'M':
                    # month week
                    value_repr = l[i][1:]
                    if not value_repr:
                        i += 1
                        value_repr = l[i]
                    # TODO: check that this is correct
                    value = int(value_repr)
                    res.start = self._result._dsttrans()
                    res.start.month = value
                    i += 1
                else:
                    return None
            else:
                return None

            if i >= len_l:
                if res.start and res.start.month is not None:
                    return None
            elif res.start and res.start.month is not None:
                if l[i] == '.':
                    i += 1
                    # TODO: check that this is correct
                    if i >= len_l or not l[i][0].isdigit():
                        return None
                    value = int(l[i])
                    res.start.week = value
                    if value == 5:
                        res.start.week = -1
                    i += 1

                    if i >= len_l:
                        return None
                    elif l[i] == '.':
                        i += 1
                        # TODO: check that this is correct
                        if i >= len_l or not l[i][0].isdigit():
                            return None
                        value = int(l[i])
                        res.start.weekday = value
                        i += 1
                    else:
                        return None
                else:
                    return None
            else:
                pass

            if i >= len_l:
                if res.start and res.start.weekday is not None:
                    res.start.hour = 2
            elif res.start and res.start.weekday is not None:
                if l[i] == '/':
                    i += 1
                    # TODO: check that this is correct
                    if i >= len_l:
                        return None
                    # TODO: check that this is correct
                    if l[i][0].isdigit():
                        # TODO: check that this is correct
                        res.start.hour = int(l[i])
                        i += 1
                    else:
                        return None
                else:
                    res.start.hour = 2
            else:
                pass

            if i >= len_l:
                if res.start:
                    res.end = res.start
                    res.start = None
            elif (l[i] is None or l[i].isspace()):
                i += 1
            else:
                return None

            if i >= len_l:
                if res.start:
                    res.end = res.start
                    res.start = None
            elif res.start is not None:
                if l[i] == ',':
                    i += 1
                else:
                    return None
            else:
                pass

            if i >= len_l:
                if res.start:
                    res.end = res.start
                    res.start = None
            elif (l[i] is None or l[i].isspace()):
                i += 1
            else:
                return None

            if i >= len_l:
                if res.start:
                    res.end = res.start
                    res.start = None
            elif res.start is not None:
                if l[i].startswith('J'):
                    # non-leap year Julian day
                    value_repr = l[i][1:]
                    if not value_repr:
                        i += 1
                        value_repr = l[i]
                    # TODO: check that this is correct
                    value = int(value_repr)
                    res.end = self._result._dsttrans()
                    picknthweekday(value, res.end, 0)
                    i += 1
                elif l[i][0].isdigit():
                    # leap year Julian day
                    # TODO: check that this is correct
                    value = int(l[i])
                    res.end = self._result._dsttrans()
                    res.end.day = value
                    i += 1
                elif l[i][0] == 'M':
                    # month week
                    value_repr = l[i][1:]
                    if not value_repr:
                        i += 1
                        value_repr = l[i]
                    # TODO: check that this is correct
                    value = int(value_repr)
                    res.end = self._result._dsttrans()
                    res.end.month = value
                    i += 1
                else:
                    return None
            else:
                pass

            if i >= len_l:
                if res.end and res.end.month is not None:
                    return None
            elif res.end and res.end.month is not None:
                if l[i] == '.':
                    i += 1
                    # TODO: check that this is correct
                    if i >= len_l or not l[i][0].isdigit():
                        return None
                    value = int(l[i])
                    res.end.week = value
                    if value == 5:
                        res.end.week = -1
                    i += 1

                    if i >= len_l:
                        return None
                    elif l[i] == '.':
                        i += 1
                        # TODO: check that this is correct
                        if i >= len_l or not l[i][0].isdigit():
                            return None
                        value = int(l[i])
                        res.end.weekday = value
                        i += 1
                    else:
                        return None
                else:
                    return None
            else:
                pass

            if i >= len_l:
                if res.end and res.end.weekday is not None:
                    res.end.hour = 2
            elif res.end and res.end.weekday is not None:
                if l[i] == '/':
                    i += 1
                    # TODO: check that this is correct
                    if i >= len_l:
                        return None
                    # TODO: check that this is correct
                    if l[i][0].isdigit():
                        # TODO: check that this is correct
                        res.end.hour = int(l[i])
                        i += 1
                    else:
                        return None
                else:
                    res.end.hour = 2
            else:
                pass

        except (IndexError, ValueError, AssertionError):
            return None

        if not info.validate(res):
            return None

        if res.dstabbr is None or res.dstoffset is None:
            return res.stdoffset
        else:
            res.dstoffset = res.dstoffset

        return res


DEFAULTTZPARSER = _tzparser()

# TODO: This is a hack
def _parsetz(tzname):
    if tzname == '' or tzname is None:
        return tzname
    return DEFAULTTZPARSER.parse(tzname)


class ParserError(ValueError):
    """Exception subclass used for any failure to parse a datetime string.

    This is a subclass of :exc:`ValueError`, and should be caught as such.

    :param msg:
        The human-readable description of the error, will be passed to the
        :class:`ValueError` constructor.
    """
    def __str__(self):
        try:
            return self.args[0] % self.args[1:]
        except (TypeError, IndexError):
            return super(ParserError, self).__str__()

    def __repr__(self):
        args = ", ".join(["'%s'" % arg for arg in self.args])
        return "%s(%s)" % (self.__class__.__name__, args)


# TODO: REMOVE THIS
def picknthweekday(n, res, weekday):
    """
    The :func:`picknthweekday` function can be used to get the nth
    occurrence of a given weekday from the 1st day of the month.
    """
    if n == 0:
        return 1
    elif n > 0:
        first_weekday = calendar.weekday(res.year, res.month, 1)
        week_index = (n - 1) * 7
        week_index += (weekday - first_weekday) % 7 + 1
    else:
        last_day_month = calendar.monthrange(res.year, res.month)[1]
        last_weekday = calendar.weekday(res.year, res.month, last_day_month)
        week_index = last_day_month + 1
        week_index += (last_weekday - weekday) % 7
        week_index -= (-n) * 7
        if week_index > last_day_month:
            week_index = 0
        week_index += 1

    res.day = week_index
    return week_index


class UnknownTimezoneWarning(RuntimeWarning):
    """
    Raised when the parser finds a timezone it cannot parse into a valid
    :class:`datetime.tzinfo` instance. This primarily happens when parsing RFC
    2822 messages with non-standard timezones.
    """
    pass
