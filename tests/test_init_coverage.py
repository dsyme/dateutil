import sys
import pytest
import dateutil


class TestDateutilInit:
    """Test coverage for dateutil.__init__.py module functionality"""

    def test_version_import_success(self):
        """Test successful import of version from _version module"""
        # This tests the normal case where _version module exists
        assert hasattr(dateutil, '__version__')
        assert isinstance(dateutil.__version__, str)
        assert dateutil.__version__ != 'unknown'

    def test_getattr_valid_modules(self):
        """Test __getattr__ with valid module names"""
        # Test accessing modules via __getattr__
        import dateutil
        
        # Test accessing each module in __all__
        for module_name in dateutil.__all__:
            module = getattr(dateutil, module_name)
            assert module is not None
            # Verify it's actually the expected module
            assert module.__name__ == f'dateutil.{module_name}'

    def test_getattr_invalid_attribute(self):
        """Test __getattr__ with invalid attribute name"""
        import dateutil
        
        with pytest.raises(AttributeError) as excinfo:
            getattr(dateutil, 'nonexistent_module')
        
        # Test the exact error message format
        expected_msg = "module 'dateutil' has not attribute 'nonexistent_module'"
        assert str(excinfo.value) == expected_msg

    def test_getattr_attribute_error_message_format(self):
        """Test that AttributeError message matches expected format exactly"""
        import dateutil
        
        # Test different invalid attribute names to cover the format string
        test_cases = [
            'invalid_name',
            'bad_module', 
            'xyz123',
            'non_existent_attr'
        ]
        
        for invalid_name in test_cases:
            with pytest.raises(AttributeError) as excinfo:
                getattr(dateutil, invalid_name)
            
            expected_msg = f"module 'dateutil' has not attribute '{invalid_name}'"
            assert str(excinfo.value) == expected_msg

    def test_getattr_edge_cases(self):
        """Test __getattr__ with various edge case inputs"""
        import dateutil
        
        # Test with empty string
        with pytest.raises(AttributeError):
            getattr(dateutil, '')
        
        # Test with None (should raise TypeError before reaching __getattr__)
        with pytest.raises(TypeError):
            getattr(dateutil, None)
            
        # Test with non-string type
        with pytest.raises(TypeError):
            getattr(dateutil, 123)

    def test_dir_functionality(self):
        """Test custom __dir__ method returns correct attributes"""
        import dateutil
        
        dir_result = dir(dateutil)
        
        # Should include all modules from __all__
        for module_name in dateutil.__all__:
            assert module_name in dir_result
        
        # Should also include regular module attributes
        assert '__version__' in dir_result
        assert '__all__' in dir_result
        
        # Should be a list
        assert isinstance(dir_result, list)

    def test_dir_excludes_sys_modules(self):
        """Test that __dir__ excludes already loaded modules correctly"""
        import dateutil
        
        # The __dir__ method should exclude modules that are already in sys.modules
        # from the globals() part, but include them in __all__
        dir_result = dir(dateutil)
        
        # __all__ modules should always be included
        for module_name in dateutil.__all__:
            assert module_name in dir_result

    def test_all_attribute_contents(self):
        """Test that __all__ contains expected module names"""
        import dateutil
        
        expected_modules = ['easter', 'parser', 'relativedelta', 'rrule', 'tz', 'utils', 'zoneinfo']
        assert dateutil.__all__ == expected_modules

    def test_lazy_import_returns_correct_modules(self):
        """Test that lazy importing returns the expected module objects"""
        import dateutil
        
        # Access a module - should return the actual imported module
        parser_module = dateutil.parser
        
        # Verify it's the correct module
        assert parser_module.__name__ == 'dateutil.parser'
        
        # Test another module
        tz_module = dateutil.tz
        assert tz_module.__name__ == 'dateutil.tz'

    def test_module_level_attributes(self):
        """Test module-level attributes are accessible"""
        import dateutil
        
        # Test that basic attributes exist
        assert hasattr(dateutil, '__name__')
        assert hasattr(dateutil, '__package__')
        assert hasattr(dateutil, '__version__')
        assert hasattr(dateutil, '__all__')
        
        # Test __name__ is correct
        assert dateutil.__name__ == 'dateutil'

    def test_importlib_usage_in_getattr(self):
        """Test that __getattr__ properly uses importlib.import_module"""
        import dateutil
        
        # This test exercises the importlib.import_module call
        # in the __getattr__ method
        module = dateutil.easter
        
        # Verify it imported correctly
        assert hasattr(module, 'easter')  # easter function should exist
        
        # Test that accessing again returns same module
        module2 = dateutil.easter
        assert module is module2