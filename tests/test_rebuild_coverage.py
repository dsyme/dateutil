import os
import sys
import pytest
import tempfile
import subprocess
from unittest.mock import patch, MagicMock

# Import the module to test
from dateutil.zoneinfo import rebuild


class TestRebuildCoverage:
    """Test coverage for dateutil.zoneinfo.rebuild module error handling"""

    def test_print_on_nosuchfile_errno_2(self):
        """Test _print_on_nosuchfile with errno 2 (file not found)"""
        # Create a mock OSError with errno 2
        mock_error = OSError("No such file or directory")
        mock_error.errno = 2
        
        # Test that the function logs the expected error message
        with patch('dateutil.zoneinfo.rebuild.logging.error') as mock_log:
            rebuild._print_on_nosuchfile(mock_error)
            
            # Verify the expected error message was logged
            mock_log.assert_called_once_with(
                "Could not find zic. Perhaps you need to install "
                "libc-bin or some other package that provides it, "
                "or it's not in your PATH?"
            )

    def test_print_on_nosuchfile_other_errno(self):
        """Test _print_on_nosuchfile with other errno values (should not log)"""
        # Create a mock OSError with a different errno
        mock_error = OSError("Permission denied")
        mock_error.errno = 13  # EACCES
        
        # Test that no logging occurs for non-errno-2 errors
        with patch('dateutil.zoneinfo.rebuild.logging.error') as mock_log:
            rebuild._print_on_nosuchfile(mock_error)
            
            # Should not have called logging.error
            mock_log.assert_not_called()

    def test_run_zic_zic_not_found(self):
        """Test _run_zic when zic command is not found"""
        zonedir = "/tmp/test_zone"
        filepaths = ["/tmp/test_file"]
        
        # Mock check_output to raise OSError (command not found)
        with patch('dateutil.zoneinfo.rebuild.check_output') as mock_check_output:
            mock_error = OSError("No such file or directory")
            mock_error.errno = 2
            mock_check_output.side_effect = mock_error
            
            # Mock the print function to verify it gets called
            with patch('dateutil.zoneinfo.rebuild._print_on_nosuchfile') as mock_print:
                # Should raise the OSError after calling _print_on_nosuchfile
                with pytest.raises(OSError):
                    rebuild._run_zic(zonedir, filepaths)
                
                # Verify _print_on_nosuchfile was called with the error
                mock_print.assert_called_once_with(mock_error)

    def test_run_zic_help_with_bloat_option(self):
        """Test _run_zic when zic help shows -b option (newer zic)"""
        zonedir = "/tmp/test_zone"
        filepaths = ["/tmp/test_file"]
        
        # Mock zic --help output that includes -b option
        help_output_with_b = b"Usage: zic [options] [filename ...]\nOptions:\n  -b {slim|fat}  Use slim or fat format\n"
        
        with patch('dateutil.zoneinfo.rebuild.check_output') as mock_check_output:
            with patch('dateutil.zoneinfo.rebuild.check_call') as mock_check_call:
                mock_check_output.return_value = help_output_with_b
                
                rebuild._run_zic(zonedir, filepaths)
                
                # Should have called check_call with -b fat arguments
                expected_args = ["zic", "-b", "fat", "-d", zonedir] + filepaths
                mock_check_call.assert_called_once_with(expected_args)

    def test_run_zic_help_without_bloat_option(self):
        """Test _run_zic when zic help doesn't show -b option (older zic)"""
        zonedir = "/tmp/test_zone" 
        filepaths = ["/tmp/test_file"]
        
        # Mock zic --help output that doesn't include -b option
        help_output_without_b = b"Usage: zic [options] [filename ...]\nOptions:\n  -d directory  Specify output directory\n"
        
        with patch('dateutil.zoneinfo.rebuild.check_output') as mock_check_output:
            with patch('dateutil.zoneinfo.rebuild.check_call') as mock_check_call:
                mock_check_output.return_value = help_output_without_b
                
                rebuild._run_zic(zonedir, filepaths)
                
                # Should have called check_call without -b fat arguments
                expected_args = ["zic", "-d", zonedir] + filepaths
                mock_check_call.assert_called_once_with(expected_args)

    def test_rebuild_basic_functionality_mocked(self):
        """Test rebuild function with mocked dependencies"""
        # This tests parts of the rebuild function without requiring actual zic
        
        # Create a temporary test file
        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tf:
            tf.write(b'test content')  # Minimal content for tarfile
            temp_filename = tf.name
        
        try:
            # Mock all the external dependencies
            with patch('dateutil.zoneinfo.rebuild.TarFile.open') as mock_tarfile:
                with patch('dateutil.zoneinfo.rebuild._run_zic') as mock_run_zic:
                    with patch('dateutil.zoneinfo.rebuild.tempfile.mkdtemp') as mock_mkdtemp:
                        with patch('dateutil.zoneinfo.rebuild.shutil.rmtree') as mock_rmtree:
                            with patch('dateutil.zoneinfo.rebuild.os.path.join') as mock_join:
                                with patch('dateutil.zoneinfo.rebuild.os.listdir') as mock_listdir:
                                    with patch('builtins.open', create=True) as mock_open:
                                        with patch('dateutil.zoneinfo.rebuild.json.dump') as mock_json_dump:
                                            
                                            # Set up the mocks
                                            mock_mkdtemp.return_value = '/tmp/test_dir'
                                            mock_join.side_effect = lambda *args: '/'.join(args)
                                            mock_listdir.return_value = ['test_entry']
                                            
                                            # Mock tarfile context managers
                                            mock_tf_read = MagicMock()
                                            mock_tf_write = MagicMock()
                                            mock_tarfile.side_effect = [mock_tf_read, mock_tf_write]
                                            mock_tf_read.__enter__ = MagicMock(return_value=mock_tf_read)
                                            mock_tf_read.__exit__ = MagicMock(return_value=False)
                                            mock_tf_write.__enter__ = MagicMock(return_value=mock_tf_write)
                                            mock_tf_write.__exit__ = MagicMock(return_value=False)
                                            
                                            # Mock file operations
                                            mock_file = MagicMock()
                                            mock_open.return_value.__enter__.return_value = mock_file
                                            
                                            # Test parameters
                                            zonegroups = ['test_group']
                                            metadata = {'version': '2023c'}
                                            
                                            # Call the function
                                            rebuild.rebuild(temp_filename, zonegroups=zonegroups, metadata=metadata)
                                            
                                            # Verify cleanup was called
                                            mock_rmtree.assert_called_once_with('/tmp/test_dir')
                                            
                                            # Verify JSON dump was called
                                            mock_json_dump.assert_called_once_with(
                                                metadata, mock_file, indent=4, sort_keys=True
                                            )

        finally:
            # Clean up temp file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def test_rebuild_with_format_and_tag(self):
        """Test rebuild function with optional format and tag parameters"""
        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tf:
            temp_filename = tf.name
            
        try:
            with patch('dateutil.zoneinfo.rebuild.TarFile.open') as mock_tarfile:
                with patch('dateutil.zoneinfo.rebuild._run_zic'):
                    with patch('dateutil.zoneinfo.rebuild.tempfile.mkdtemp', return_value='/tmp/test_dir'):
                        with patch('dateutil.zoneinfo.rebuild.shutil.rmtree'):
                            with patch('dateutil.zoneinfo.rebuild.os.path.join', side_effect=lambda *args: '/'.join(args)):
                                with patch('dateutil.zoneinfo.rebuild.os.listdir', return_value=['test_entry']):
                                    with patch('builtins.open', create=True):
                                        with patch('dateutil.zoneinfo.rebuild.json.dump'):
                                            
                                            # Mock tarfile context managers
                                            mock_tf_read = MagicMock()
                                            mock_tf_write = MagicMock()
                                            mock_tarfile.side_effect = [mock_tf_read, mock_tf_write]
                                            mock_tf_read.__enter__ = MagicMock(return_value=mock_tf_read)
                                            mock_tf_read.__exit__ = MagicMock(return_value=False)
                                            mock_tf_write.__enter__ = MagicMock(return_value=mock_tf_write)
                                            mock_tf_write.__exit__ = MagicMock(return_value=False)
                                            
                                            # Call rebuild with optional parameters
                                            rebuild.rebuild(
                                                temp_filename,
                                                tag='2023c',
                                                format='bz2',  # Different format
                                                zonegroups=['group1', 'group2'],
                                                metadata={'test': 'data'}
                                            )
                                            
                                            # Verify tarfile.open was called with correct format
                                            # The second call should be for writing with bz2 format
                                            write_call = mock_tarfile.call_args_list[1]
                                            assert 'w:bz2' in str(write_call)

        finally:
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)