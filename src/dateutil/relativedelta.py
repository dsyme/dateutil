# -*- coding: utf-8 -*-
import datetime
import calendar

import operator
from math import copysign

from six import integer_types
from warnings import warn

from ._common import weekday

MO, TU, WE, TH, FR, SA, SU = weekdays = tuple(weekday(x) for x in range(7))

__all__ = ["relativedelta", "MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class relativedelta(object):
    """
    The relativedelta type is designed to be applied to an existing datetime and
    can replace specific components of that datetime, or represents an interval
    of time.

    It is based on the specification of the excellent work done by M.-A. Lemburg
    in his
    `mx.DateTime <https://www.egenix.com/products/python/mxBase/mxDateTime/>`_ extension.
    However, notice that this type does *NOT* implement the same algorithm as
    his work. Do *NOT* expect it to behave like mx.DateTime's counterpart.

    There are two different ways to build a relativedelta instance. The
    first one is passing it two date/datetime classes::

        relativedelta(datetime1, datetime2)

    The second one is passing it any number of the following keyword arguments::

        relativedelta(arg1=x,arg2=y,arg3=z...)

        year, month, day, hour, minute, second, microsecond:
            Absolute information (argument is singular); adding or subtracting a
            relativedelta with absolute information does not perform an arithmetic
            operation, but rather REPLACES the corresponding value in the
            original datetime with the value(s) in relativedelta.

        years, months, weeks, days, hours, minutes, seconds, microseconds:
            Relative information, may be negative (argument is plural); adding
            or subtracting a relativedelta with relative information performs
            the corresponding arithmetic operation on the original datetime value
            with the information in the relativedelta.

        weekday:
            One of the weekday instances (MO, TU, etc) available in the
            relativedelta module. These instances may receive a parameter N,
            specifying the Nth weekday, which could be positive or negative
            (like MO(+1) or MO(-2)). Not specifying it is the same as specifying
            +1. You can also use an integer, where 0=MO. This argument is always
            relative e.g. if the calculated date is already Monday, using MO(1)
            or MO(-1) won't change the day. To effectively make it absolute, use
            it in combination with the day argument (e.g. day=1, MO(1) for first
            Monday of the month).

        leapdays:
            Will add given days to the date found, if year is a leap
            year, and the date found is post 28 of february.

        yearday, nlyearday:
            Set the yearday or the non-leap year day (jump leap days).
            These are converted to day/month/leapdays information.

    There are relative and absolute forms of the keyword
    arguments. The plural is relative, and the singular is
    absolute. For each argument in the order below, the absolute form
    is applied first (by setting each attribute to that value) and
    then the relative form (by adding the value to the attribute).

    The order of attributes considered when this relativedelta is
    added to a datetime is:

    1. Year
    2. Month
    3. Day
    4. Hours
    5. Minutes
    6. Seconds
    7. Microseconds

    Finally, weekday is applied, using the rule described above.

    For example

    >>> from datetime import datetime
    >>> from dateutil.relativedelta import relativedelta, MO
    >>> dt = datetime(2018, 4, 9, 13, 37, 0)
    >>> delta = relativedelta(hours=25, day=1, weekday=MO(1))
    >>> dt + delta
    datetime.datetime(2018, 4, 2, 14, 37)

    First, the day is set to 1 (the first of the month), then 25 hours
    are added, to get to the 2nd day and 14th hour, finally the
    weekday is applied, but since the 2nd is already a Monday there is
    no effect.

    """

    def __init__(self, dt1=None, dt2=None,
                 years=0, months=0, days=0, leapdays=0, weeks=0,
                 hours=0, minutes=0, seconds=0, microseconds=0,
                 year=None, month=None, day=None, weekday=None,
                 yearday=None, nlyearday=None,
                 hour=None, minute=None, second=None, microsecond=None):

        if dt1 and dt2:
            # datetime is a subclass of date. So both must be date
            if not (isinstance(dt1, datetime.date) and
                    isinstance(dt2, datetime.date)):
                raise TypeError("relativedelta only diffs datetime/date")

            # We allow two dates, or two datetimes, or a datetime and a date
            if (isinstance(dt1, datetime.datetime) and
                    isinstance(dt2, datetime.datetime)):
                self._has_time = 1
            elif (isinstance(dt1, datetime.datetime) and
                  isinstance(dt2, datetime.date)):
                if dt1.hour or dt1.minute or dt1.second or dt1.microsecond:
                    self._has_time = 1
                else:
                    self._has_time = 0
            elif (isinstance(dt1, datetime.date) and
                  isinstance(dt2, datetime.datetime)):
                if dt2.hour or dt2.minute or dt2.second or dt2.microsecond:
                    self._has_time = 1
                else:
                    self._has_time = 0
            else:
                self._has_time = 0

            delta = dt1 - dt2
            self.seconds = delta.seconds + delta.days * 86400
            self.days = delta.days
            self.microseconds = delta.microseconds
            self.years = 0
            self.months = 0
            self.leapdays = 0
            self.hours = 0
            self.minutes = 0
            self.year = None
            self.month = None
            self.day = None
            self.weekday = None
            self.hour = None
            self.minute = None
            self.second = None
            self.microsecond = None

            # Can't compare datetime to date, unless
            # the time part of datetime is zero
            if isinstance(dt1, datetime.datetime) and isinstance(dt2, datetime.date):
                dt2 = datetime.datetime.fromordinal(dt2.toordinal())
            elif isinstance(dt1, datetime.date) and isinstance(dt2, datetime.datetime):
                dt1 = datetime.datetime.fromordinal(dt1.toordinal())

            dtdiff = dt1 - dt2
            if dtdiff.days:
                self.days = dtdiff.days
                self.seconds = dtdiff.seconds
                self.microseconds = dtdiff.microseconds
            else:
                # Negative timedelta only has days information, so it's
                # possible to have some false positives. That's why this
                # is an 'if' and not an 'elif'.
                if dtdiff.seconds:
                    self.seconds = dtdiff.seconds
                if dtdiff.microseconds:
                    self.microseconds = dtdiff.microseconds

            # If it's the same date, then ignore the months and years
            if dt1.toordinal() == dt2.toordinal():
                return

            # Get year and month delta
            months = (dt1.year - dt2.year) * 12 + dt1.month - dt2.month
            self._set_months(months)
            dtstart = dt2
            dtend = dt1
            if months < 0:
                dtstart, dtend = dt1, dt2
                months = -months
            delta = relativedelta(years=months//12, months=months%12)
            year = dtstart.year + delta.years
            month = dtstart.month + delta.months
            if month > 12:
                year += 1
                month -= 12
            elif month < 1:
                year -= 1
                month += 12
            dtstart = dtstart.replace(year=year, month=month)
            if dtstart > dtend:
                months -= 1
                self._set_months(months)
            elif (dtstart == dtend and
                  self.seconds == 0 and
                  self.microseconds == 0):
                # We were on the second right on the border, so decrement
                # it, because the above comparison will fail in this case.
                months -= 1
                self._set_months(months)
        else:
            # Check for non-integer values in integer fields
            for attr in ("years", "months"):
                value = locals()[attr]
                if not isinstance(value, integer_types):
                    value_type = type(value).__name__
                    msg = "Non-integer value passed for {attr}: {value_type}"
                    raise TypeError(msg.format(attr=attr, value_type=value_type))

            # Relative information
            self.years = years
            self.months = months
            self.days = days + weeks*7
            self.leapdays = leapdays
            self.hours = hours
            self.minutes = minutes
            self.seconds = seconds
            self.microseconds = microseconds

            # Absolute information
            self.year = year
            self.month = month
            self.day = day
            self.weekday = weekday
            self.hour = hour
            self.minute = minute
            self.second = second
            self.microsecond = microsecond

            if any(x is not None and int(x) != x for x in (year, month, day, hour,
                                                           minute, second,
                                                           microsecond)):
                # For now we'll deprecate floats - later it'll be an error.
                warn("Non-integer absolute values will raise an error "
                     "in future versions. "
                     "Use integer values to avoid this warning.",
                     DeprecationWarning)

            if isinstance(weekday, integer_types):
                self.weekday = weekdays[weekday]

            # Year day information
            if nlyearday:
                if yearday:
                    raise ValueError("Can't specify both yearday and nlyearday")
                yearday = nlyearday

            if yearday:
                self.yearday = yearday
                if yearday > 59:
                    self.leapdays = -1

                # Convert to day/month/leapdays information
                yday = yearday
                if yday < 0:
                    yday += 366

                # Guess whether we're dealing with a leap year, then
                # increment year and day number by 1 if this is a leap year and
                # we're past Feb 28th
                year = self.year or 1
                if calendar.isleap(year):
                    leapdays = 1
                    leapadj = 1
                else:
                    leapdays = 0
                    leapadj = 0
                if yday > (31 + 28 + leapadj):
                    # Past Feb. 28th
                    yday -= leapdays
                elif yday > (31 + 28):
                    # Past Feb. 28th, but before the potential Feb. 29th, so
                    # we may be past the leap day, but we might not be. We
                    # could be extremely ridiculous and check if the day number
                    # the user gives corresponds to Feb 29th on a leap year,
                    # but there's no point since Feb 29th is always the 60th
                    # day of the year anyway.
                    if calendar.isleap(year):
                        yday -= leapdays

                try:
                    mmdd = calendar._monthlen[leapdays]
                    for mm in range(1, 13):
                        if yday <= mmdd[mm]:
                            self.month = mm
                            if mm == 1:
                                self.day = yday
                            else:
                                self.day = yday-mmdd[mm-1]
                            break
                except:
                    raise ValueError("invalid year day (%d)" % yearday)
            else:
                self.yearday = None

        self._has_time = any([hours, minutes, seconds, microseconds,
                              hour is not None, minute is not None,
                              second is not None, microsecond is not None])

    def _set_months(self, months):
        self.months = months % 12
        self.years = months // 12

    @property
    def weeks(self):
        return int(self.days / 7.0)

    @weeks.setter
    def weeks(self, value):
        self.days = value * 7

    def normalized(self, **kwargs):
        """
        Return a version of this object represented entirely using integer
        values for the relative attributes.

        >>> relativedelta(days=1.5, hours=2).normalized()
        relativedelta(days=+1, hours=+14)

        :return:
            A :class:`dateutil.relativedelta.relativedelta` object.
        """
        # Cascade the normalization
        days = self.days
        hours = self.hours
        minutes = self.minutes
        seconds = self.seconds
        microseconds = self.microseconds

        # Get rid of the fractional part from microseconds, seconds,
        # minutes, hours and days
        microseconds_f, microseconds = _sign(microseconds) * divmod(abs(microseconds), 1)
        microseconds = int(microseconds)

        seconds_f = seconds + microseconds_f / 1e6
        seconds_f, seconds = _sign(seconds_f) * divmod(abs(seconds_f), 1)
        seconds = int(seconds)

        minutes_f = minutes + seconds_f / 60
        minutes_f, minutes = _sign(minutes_f) * divmod(abs(minutes_f), 1)
        minutes = int(minutes)

        hours_f = hours + minutes_f / 60
        hours_f, hours = _sign(hours_f) * divmod(abs(hours_f), 1)
        hours = int(hours)

        days_f = days + hours_f / 24
        days_f, days = _sign(days_f) * divmod(abs(days_f), 1)
        days = int(days)

        # TODO: the rest of this should have some correspondence to the
        #   "date arithmetic" page of the documentation.
        return self.__class__(years=self.years, months=self.months,
                              days=days, hours=hours, minutes=minutes,
                              seconds=seconds, microseconds=microseconds,
                              leapdays=self.leapdays, year=self.year,
                              month=self.month, day=self.day,
                              weekday=self.weekday, hour=self.hour,
                              minute=self.minute, second=self.second,
                              microsecond=self.microsecond)

    def __add__(self, other):
        if isinstance(other, relativedelta):
            # Optimize relativedelta + relativedelta: minimize conditional expressions
            result_attrs = {
                'years': other.years + self.years,
                'months': other.months + self.months,
                'days': other.days + self.days,
                'hours': other.hours + self.hours,
                'minutes': other.minutes + self.minutes,
                'seconds': other.seconds + self.seconds,
                'microseconds': other.microseconds + self.microseconds,
            }
            
            # Handle absolute attributes, preferring other over self
            for attr in ('year', 'month', 'day', 'weekday', 'hour', 'minute', 'second', 'microsecond'):
                other_val = getattr(other, attr)
                if other_val is not None:
                    result_attrs[attr] = other_val
                else:
                    self_val = getattr(self, attr)
                    if self_val is not None:
                        result_attrs[attr] = self_val
                        
            # Handle leapdays special case  
            if other.leapdays or self.leapdays:
                result_attrs['leapdays'] = other.leapdays or self.leapdays
                
            return self.__class__(**result_attrs)
        if isinstance(other, datetime.timedelta):
            # Optimize relativedelta + timedelta: only update changed fields
            return self._create_from_attrs(
                days=self.days + other.days,
                seconds=self.seconds + other.seconds,
                microseconds=self.microseconds + other.microseconds)
        if not isinstance(other, datetime.date):
            return NotImplemented
        elif self._has_time and not isinstance(other, datetime.datetime):
            other = datetime.datetime.fromordinal(other.toordinal())
        year = (self.year or other.year)+self.years
        month = self.month or other.month
        if self.months:
            assert 1 <= abs(self.months) <= 12
            month += self.months
            if month > 12:
                year += 1
                month -= 12
            elif month < 1:
                year -= 1
                month += 12
        day = min(calendar.monthrange(year, month)[1],
                  self.day or other.day)
        repl = {"year": year, "month": month, "day": day}
        for attr in ["hour", "minute", "second", "microsecond"]:
            value = getattr(self, attr)
            if value is not None:
                repl[attr] = value
        days = self.days
        if self.leapdays and month > 2 and calendar.isleap(year):
            days += self.leapdays
        ret = (other.replace(**repl)
               + datetime.timedelta(days=days,
                                    hours=self.hours,
                                    minutes=self.minutes,
                                    seconds=self.seconds,
                                    microseconds=self.microseconds))
        if self.weekday:
            weekday, nth = self.weekday.weekday, self.weekday.n or 1
            jumpdays = (abs(nth) - 1) * 7
            if nth > 0:
                jumpdays += (7 - ret.weekday() + weekday) % 7
            else:
                jumpdays += (ret.weekday() - weekday) % 7
                jumpdays *= -1
            ret += datetime.timedelta(days=jumpdays)
        return ret

    def __radd__(self, other):
        return self.__add__(other)

    def __rsub__(self, other):
        return self.__neg__().__radd__(other)

    def __sub__(self, other):
        if not isinstance(other, relativedelta):
            return NotImplemented   # In case the other object defines __rsub__
        
        # Create a new relativedelta by setting changed attributes and using helper for defaults
        result_attrs = {
            'years': self.years - other.years,
            'months': self.months - other.months,
            'days': self.days - other.days,
            'hours': self.hours - other.hours,
            'minutes': self.minutes - other.minutes,
            'seconds': self.seconds - other.seconds,
            'microseconds': self.microseconds - other.microseconds,
        }
        
        # Add non-None attributes, preferring self over other
        for attr in ('year', 'month', 'day', 'weekday', 'hour', 'minute', 'second', 'microsecond'):
            self_val = getattr(self, attr)
            if self_val is not None:
                result_attrs[attr] = self_val
            else:
                other_val = getattr(other, attr)
                if other_val is not None:
                    result_attrs[attr] = other_val
                    
        # Handle leapdays special case
        if self.leapdays or other.leapdays:
            result_attrs['leapdays'] = self.leapdays or other.leapdays
            
        return self.__class__(**result_attrs)

    def __abs__(self):
        return self._create_from_attrs(
            years=abs(self.years),
            months=abs(self.months),
            days=abs(self.days),
            hours=abs(self.hours),
            minutes=abs(self.minutes),
            seconds=abs(self.seconds),
            microseconds=abs(self.microseconds))

    def __neg__(self):
        return self._create_from_attrs(
            years=-self.years,
            months=-self.months,
            days=-self.days,
            hours=-self.hours,
            minutes=-self.minutes,
            seconds=-self.seconds,
            microseconds=-self.microseconds)

    def _create_from_attrs(self, years=None, months=None, days=None, hours=None,
                          minutes=None, seconds=None, microseconds=None,
                          leapdays=None, year=None, month=None, day=None,
                          weekday=None, hour=None, minute=None, second=None,
                          microsecond=None, **kwargs):
        """Optimized factory method to create relativedelta with explicit attributes."""
        # Use existing values as defaults to reduce conditional expressions
        return self.__class__(
            years=years if years is not None else self.years,
            months=months if months is not None else self.months,
            days=days if days is not None else self.days,
            hours=hours if hours is not None else self.hours,
            minutes=minutes if minutes is not None else self.minutes,
            seconds=seconds if seconds is not None else self.seconds,
            microseconds=microseconds if microseconds is not None else self.microseconds,
            leapdays=leapdays if leapdays is not None else self.leapdays,
            year=year if year is not None else self.year,
            month=month if month is not None else self.month,
            day=day if day is not None else self.day,
            weekday=weekday if weekday is not None else self.weekday,
            hour=hour if hour is not None else self.hour,
            minute=minute if minute is not None else self.minute,
            second=second if second is not None else self.second,
            microsecond=microsecond if microsecond is not None else self.microsecond,
            **kwargs)

    def __bool__(self):
        # Early return optimization: check non-zero numeric values first 
        # since they're more common and faster to evaluate
        if (self.years or self.months or self.days or self.hours or 
            self.minutes or self.seconds or self.microseconds or self.leapdays):
            return True
            
        # Then check absolute values (None checks are slower)
        return (self.year is not None or self.month is not None or 
                self.day is not None or self.weekday is not None or 
                self.hour is not None or self.minute is not None or 
                self.second is not None or self.microsecond is not None)
    # Compatibility with Python 2.x
    __nonzero__ = __bool__

    def __mul__(self, other):
        try:
            f = float(other)
        except TypeError:
            return NotImplemented

        return self._create_from_attrs(
            years=int(self.years * f),
            months=int(self.months * f),
            days=int(self.days * f),
            hours=int(self.hours * f),
            minutes=int(self.minutes * f),
            seconds=int(self.seconds * f),
            microseconds=int(self.microseconds * f))

    __rmul__ = __mul__

    def __eq__(self, other):
        if not isinstance(other, relativedelta):
            return NotImplemented
        if self.weekday or other.weekday:
            if not self.weekday or not other.weekday:
                return False
            if self.weekday.weekday != other.weekday.weekday:
                return False
            n1, n2 = self.weekday.n, other.weekday.n
            if n1 != n2 and not ((not n1 or n1 == 1) and (not n2 or n2 == 1)):
                return False
        return (self.years == other.years and
                self.months == other.months and
                self.days == other.days and
                self.hours == other.hours and
                self.minutes == other.minutes and
                self.seconds == other.seconds and
                self.microseconds == other.microseconds and
                self.leapdays == other.leapdays and
                self.year == other.year and
                self.month == other.month and
                self.day == other.day and
                self.weekday == other.weekday and
                self.hour == other.hour and
                self.minute == other.minute and
                self.second == other.second and
                self.microsecond == other.microsecond)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __div__(self, other):
        try:
            reciprocal = 1 / float(other)
        except (TypeError, ZeroDivisionError):
            return NotImplemented
        return self.__mul__(reciprocal)

    __truediv__ = __div__

    def __repr__(self):
        l = []
        for attr in ["years", "months", "days", "leapdays",
                     "hours", "minutes", "seconds", "microseconds"]:
            value = getattr(self, attr)
            if value:
                l.append("%s=%+d" % (attr, value))
        for attr in ["year", "month", "day", "weekday",
                     "hour", "minute", "second", "microsecond"]:
            value = getattr(self, attr)
            if value is not None:
                l.append("%s=%s" % (attr, repr(value)))
        return "%s(%s)" % (self.__class__.__name__, ", ".join(l))

    def __hash__(self):
        return hash((
            self.__class__,
            self.years,
            self.months,
            self.days,
            self.hours,
            self.minutes,
            self.seconds,
            self.microseconds,
            self.leapdays,
            self.year,
            self.month,
            self.day,
            self.weekday,
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
        ))


def _sign(x):
    return int(copysign(1, x))


# vim:ts=4:sw=4:et
