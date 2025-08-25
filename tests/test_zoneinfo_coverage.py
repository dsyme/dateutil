# -*- coding: utf-8 -*-
"""
Tests for improving coverage of dateutil.zoneinfo module.

This module focuses on testing previously uncovered edge cases and error conditions
in the zoneinfo package to improve overall test coverage.
"""
import pickle
import unittest
import warnings
from io import BytesIO
from unittest import mock

from dateutil import zoneinfo


class TestZoneInfoCoverage(unittest.TestCase):
    """Test cases to improve zoneinfo module coverage."""

    def test_tzfile_reduce_method(self):
        """Test the __reduce__ method of tzfile class (line 19)."""
        # Get a valid timezone to test with
        zif = zoneinfo.get_zonefile_instance()
        tz_name = list(zif.zones.keys())[0] if zif.zones else 'UTC'
        
        if tz_name in zif.zones:
            tzf = zif.zones[tz_name]
            # Test that the tzfile can be pickled and unpickled
            # This will call __reduce__ method
            pickled_data = pickle.dumps(tzf)
            unpickled_tzf = pickle.loads(pickled_data)
            
            # Verify that the unpickled object is equivalent
            self.assertEqual(type(tzf), type(unpickled_tzf))

    @mock.patch('dateutil.zoneinfo.get_data')
    def test_getzoneinfofile_stream_ioerror(self, mock_get_data):
        """Test IOError handling in getzoneinfofile_stream (lines 25-27)."""
        # Mock get_data to raise IOError
        mock_ioerror = IOError()
        mock_ioerror.errno = 2
        mock_ioerror.strerror = "No such file or directory"
        mock_get_data.side_effect = mock_ioerror
        
        # Capture warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = zoneinfo.getzoneinfofile_stream()
            
            # Should return None due to IOError
            self.assertIsNone(result)
            
            # Should have issued a warning
            self.assertEqual(len(w), 1)
            self.assertIn("I/O error", str(w[0].message))

    @mock.patch.object(zoneinfo, 'TarFile')
    def test_zoneinfofile_no_metadata(self, mock_tarfile):
        """Test ZoneInfoFile initialization with missing metadata (lines 47-52)."""
        # Mock TarFile to simulate a tar without METADATA
        mock_tf = mock.Mock()
        mock_member = mock.Mock()
        mock_member.name = 'UTC'
        mock_member.isfile.return_value = True
        mock_member.islnk.return_value = False
        mock_member.issym.return_value = False
        mock_tf.getmembers.return_value = [mock_member]
        
        # Mock extractfile to return a minimal tzfile
        mock_tzfile_data = mock.Mock()
        mock_tf.extractfile.return_value = mock_tzfile_data
        
        # Mock getmember to raise KeyError for METADATA (line 47-49)
        mock_tf.getmember.side_effect = KeyError("METADATA not found")
        
        mock_tarfile.open.return_value.__enter__.return_value = mock_tf
        mock_tarfile.open.return_value.__exit__.return_value = None
        
        # This should trigger the KeyError handling for missing metadata
        with mock.patch('dateutil.zoneinfo.tzfile') as mock_tzfile_class:
            mock_tzfile_instance = mock.Mock()
            mock_tzfile_class.return_value = mock_tzfile_instance
            
            zif = zoneinfo.ZoneInfoFile(BytesIO(b'dummy'))
            
            # Should have set metadata to None when METADATA file is missing
            self.assertIsNone(zif.metadata)

    def test_zoneinfofile_none_stream(self):
        """Test ZoneInfoFile initialization with None stream (lines 50-52)."""
        zif = zoneinfo.ZoneInfoFile(None)
        
        # Should initialize empty zones and None metadata
        self.assertEqual(zif.zones, {})
        self.assertIsNone(zif.metadata)

    def test_gettz_db_metadata_lazy_initialization(self):
        """Test lazy initialization in gettz_db_metadata (line 166)."""
        # Clear the global instance to test lazy initialization
        original_instance = zoneinfo._CLASS_ZONE_INSTANCE[:]
        zoneinfo._CLASS_ZONE_INSTANCE.clear()
        
        try:
            # This should trigger the lazy initialization (line 166)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                metadata = zoneinfo.gettz_db_metadata()
                
            # Should have created an instance
            self.assertEqual(len(zoneinfo._CLASS_ZONE_INSTANCE), 1)
            self.assertIsNotNone(zoneinfo._CLASS_ZONE_INSTANCE[0])
            
        finally:
            # Restore original state
            zoneinfo._CLASS_ZONE_INSTANCE[:] = original_instance

    def test_gettz_lazy_initialization(self):
        """Test lazy initialization in gettz function."""
        # Clear the global instance to test lazy initialization
        original_instance = zoneinfo._CLASS_ZONE_INSTANCE[:]
        zoneinfo._CLASS_ZONE_INSTANCE.clear()
        
        try:
            # This should trigger the lazy initialization
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                # Try to get a timezone - this calls the lazy init
                result = zoneinfo.gettz('UTC')
                
            # Should have created an instance
            self.assertEqual(len(zoneinfo._CLASS_ZONE_INSTANCE), 1)
            self.assertIsNotNone(zoneinfo._CLASS_ZONE_INSTANCE[0])
            
        finally:
            # Restore original state
            zoneinfo._CLASS_ZONE_INSTANCE[:] = original_instance

    def test_deprecation_warnings(self):
        """Test that deprecated functions issue warnings."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            
            # Test gettz deprecation warning
            zoneinfo.gettz('UTC')
            
            # Test gettz_db_metadata deprecation warning  
            zoneinfo.gettz_db_metadata()
            
            # Should have 2 deprecation warnings
            deprecation_warnings = [warning for warning in w 
                                  if issubclass(warning.category, DeprecationWarning)]
            self.assertGreaterEqual(len(deprecation_warnings), 2)


if __name__ == '__main__':
    unittest.main()