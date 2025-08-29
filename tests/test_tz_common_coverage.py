# -*- coding: utf-8 -*-
"""
Test cases to improve coverage of dateutil.tz._common module.

This test file focuses on testing error conditions and edge cases
that are not covered by existing tests.
"""
from __future__ import unicode_literals
import pytest
from datetime import datetime, timedelta, tzinfo

from dateutil.tz import _common


class TestValidateFromutcInputs:
    """Test the _validate_fromutc_inputs decorator."""

    def test_validate_fromutc_inputs_non_datetime(self):
        """Test TypeError when non-datetime is passed."""
        @_common._validate_fromutc_inputs
        def dummy_fromutc(self, dt):
            return dt

        tz_instance = _common._tzinfo()
        
        # Test with non-datetime object (string)
        with pytest.raises(TypeError, match="fromutc\\(\\) requires a datetime argument"):
            dummy_fromutc(tz_instance, "not a datetime")

        # Test with non-datetime object (None)  
        with pytest.raises(TypeError, match="fromutc\\(\\) requires a datetime argument"):
            dummy_fromutc(tz_instance, None)

        # Test with non-datetime object (integer)
        with pytest.raises(TypeError, match="fromutc\\(\\) requires a datetime argument"):
            dummy_fromutc(tz_instance, 12345)

    def test_validate_fromutc_inputs_wrong_tzinfo(self):
        """Test ValueError when dt.tzinfo is not self."""
        @_common._validate_fromutc_inputs
        def dummy_fromutc(self, dt):
            return dt

        tz1 = _common._tzinfo()
        tz2 = _common._tzinfo()
        
        # Create datetime with different tzinfo
        dt = datetime(2020, 1, 1, 12, 0, 0, tzinfo=tz2)
        
        with pytest.raises(ValueError, match="dt.tzinfo is not self"):
            dummy_fromutc(tz1, dt)


class TestTzinfoFromutc:
    """Test the _fromutc method in _tzinfo class."""

    def test_fromutc_none_utcoffset(self):
        """Test ValueError when utcoffset returns None."""
        class TestTZ(_common._tzinfo):
            def utcoffset(self, dt):
                return None
            def dst(self, dt):
                return timedelta(0)

        tz = TestTZ()
        dt = datetime(2020, 1, 1, 12, 0, 0, tzinfo=tz)
        
        with pytest.raises(ValueError, match="fromutc\\(\\) requires a non-None utcoffset\\(\\) result"):
            tz._fromutc(dt)

    def test_fromutc_none_dst(self):
        """Test ValueError when dst returns None."""
        class TestTZ(_common._tzinfo):
            def utcoffset(self, dt):
                return timedelta(hours=5)
            def dst(self, dt):
                return None

        tz = TestTZ()
        dt = datetime(2020, 1, 1, 12, 0, 0, tzinfo=tz)
        
        with pytest.raises(ValueError, match="fromutc\\(\\) requires a non-None dst\\(\\) result"):
            tz._fromutc(dt)

    def test_fromutc_inconsistent_dst_after_fold(self):
        """Test ValueError when dst gives inconsistent results after fold."""
        class TestTZ(_common._tzinfo):
            def __init__(self):
                self.dst_call_count = 0
            
            def utcoffset(self, dt):
                return timedelta(hours=5)
                
            def dst(self, dt):
                # Return None on second call (after enfold)
                self.dst_call_count += 1
                if self.dst_call_count == 2:
                    return None
                return timedelta(hours=1)

        tz = TestTZ()
        dt = datetime(2020, 1, 1, 12, 0, 0, tzinfo=tz)
        
        with pytest.raises(ValueError, match="fromutc\\(\\): dt.dst gave inconsistent results; cannot convert"):
            tz._fromutc(dt)


class TestTzrangebase:
    """Test the tzrangebase abstract base class."""

    def test_tzrangebase_init_raises_not_implemented(self):
        """Test that tzrangebase.__init__ raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="tzrangebase is an abstract base class"):
            _common.tzrangebase()

    def test_tzrangebase_fromutc_type_error(self):
        """Test TypeError in tzrangebase.fromutc when non-datetime passed."""
        class TestTZRange(_common.tzrangebase):
            def __init__(self):
                # Skip parent __init__ to avoid NotImplementedError
                pass
            def transitions(self, year):
                return None
            def utcoffset(self, dt):
                return timedelta(hours=5)

        tz = TestTZRange()
        
        with pytest.raises(TypeError, match="fromutc\\(\\) requires a datetime argument"):
            tz.fromutc("not a datetime")

    def test_tzrangebase_fromutc_value_error(self):
        """Test ValueError in tzrangebase.fromutc when dt.tzinfo is not self."""
        class TestTZRange(_common.tzrangebase):
            def __init__(self):
                # Skip parent __init__ to avoid NotImplementedError
                pass
            def transitions(self, year):
                return None
            def utcoffset(self, dt):
                return timedelta(hours=5)

        tz1 = TestTZRange()
        tz2 = TestTZRange()
        dt = datetime(2020, 1, 1, 12, 0, 0, tzinfo=tz2)
        
        with pytest.raises(ValueError, match="dt.tzinfo is not self"):
            tz1.fromutc(dt)

    def test_tzrangebase_repr(self):
        """Test __repr__ method of tzrangebase subclass."""
        class TestTZRange(_common.tzrangebase):
            def __init__(self):
                # Skip parent __init__ to avoid NotImplementedError
                pass
            def transitions(self, year):
                return None

        tz = TestTZRange()
        
        # Test that __repr__ returns expected format
        repr_str = repr(tz)
        assert repr_str == "TestTZRange(...)"
