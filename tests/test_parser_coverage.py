# -*- coding: utf-8 -*-
"""
Coverage tests for parser module focusing on uncovered error conditions and edge cases.
"""
from __future__ import unicode_literals

import sys
import unittest
import pytest
from io import StringIO
from datetime import datetime

from dateutil.parser import parse, ParserError
from dateutil.parser._parser import _timelex, _ymd, parser, parserinfo


class TestTimelex(unittest.TestCase):
    """Test _timelex class for uncovered code paths"""
    
    def test_next_method_python2_compat(self):
        # Test line 197: Python 2.x compatibility method
        tl = _timelex('test word')
        # Python 2 compatibility: next() should call __next__()
        token1 = tl.__next__()
        token2 = tl.next()  # This calls __next__() internally
        self.assertIsInstance(token1, str)
        self.assertIsInstance(token2, str)
        self.assertNotEqual(token1, token2)  # Should be different tokens


class TestYMDClass(unittest.TestCase):
    """Test _ymd class for error conditions"""
    
    def test_duplicate_month_error(self):
        # Test lines 445: ValueError when month is already set
        ymd = _ymd()
        ymd.append(1, 'M')  # Set month first time
        with pytest.raises(ValueError, match='Month is already set'):
            ymd.append(2, 'M')  # Try to set month again
    
    def test_duplicate_day_error(self):
        # Test lines 449: ValueError when day is already set  
        ymd = _ymd()
        ymd.append(15, 'D')  # Set day first time
        with pytest.raises(ValueError, match='Day is already set'):
            ymd.append(20, 'D')  # Try to set day again
    
    def test_duplicate_year_error(self):
        # Test lines 453: ValueError when year is already set
        ymd = _ymd()
        ymd.append(2023, 'Y')  # Set year first time
        with pytest.raises(ValueError, match='Year is already set'):
            ymd.append(2024, 'Y')  # Try to set year again


class TestParserEdgeCases(unittest.TestCase):
    """Test parser edge cases and error conditions"""
    
    def test_year_conversion_edge_cases(self):
        # Test lines around 376: Year conversion in different ranges
        p = parser()
        
        # Test two-digit years that trigger century adjustments
        # This helps cover some of the year processing logic
        result1 = parse("99-01-01")  # Should become 1999
        result2 = parse("01-01-01")  # Should become 2001 (not 00 which causes month=0)
        self.assertEqual(result1.year, 1999)
        self.assertEqual(result2.year, 2001)
    
    def test_timelex_string_io_input(self):
        # Test _timelex with StringIO input to cover different input types
        string_input = StringIO("2023-01-01 12:30:45")
        tl = _timelex(string_input)
        tokens = list(tl)
        self.assertTrue(len(tokens) > 0)
        self.assertIn('2023', tokens)
    
    def test_parser_ampm_validation_edge_cases(self):
        # Test some edge cases around AM/PM handling
        # These may hit some of the uncovered validation logic
        
        # Valid AM/PM cases
        result1 = parse("12:30 AM")
        result2 = parse("12:30 PM") 
        self.assertEqual(result1.hour, 0)  # 12:30 AM = 00:30
        self.assertEqual(result2.hour, 12)  # 12:30 PM = 12:30
    
    def test_fuzzy_parsing_edge_cases(self):
        # Test fuzzy parsing with various input formats to hit edge cases
        result1 = parse("Today is January 1, 2023", fuzzy=True)
        self.assertEqual(result1.year, 2023)
        self.assertEqual(result1.month, 1)
        self.assertEqual(result1.day, 1)
        
        # Test fuzzy with tokens
        result2, tokens = parse("Meeting on January 15th at 3pm", fuzzy_with_tokens=True)
        self.assertEqual(result2.year, datetime.now().year)  # Current year default
        self.assertEqual(result2.month, 1)
        self.assertEqual(result2.day, 15)
        self.assertEqual(result2.hour, 15)  # 3pm = 15:00
        self.assertTrue(len(tokens) > 0)
    
    def test_parserinfo_customization(self):
        # Test custom parserinfo to cover some initialization paths
        class CustomParserInfo(parserinfo):
            def __init__(self):
                super(CustomParserInfo, self).__init__()
                
        custom_info = CustomParserInfo()
        p = parser(info=custom_info)
        result = p.parse("2023-01-01")
        self.assertEqual(result.year, 2023)


class TestParserErrorConditions(unittest.TestCase):
    """Test various parser error conditions"""
    
    def test_invalid_time_components(self):
        # Test various invalid time formats that should raise ParserError
        invalid_times = [
            "25:00:00",  # Invalid hour
            "12:60:00",  # Invalid minute  
            "12:30:60",  # Invalid second
        ]
        
        for time_str in invalid_times:
            with pytest.raises(ParserError):
                parse(time_str)
    
    def test_ambiguous_date_handling(self):
        # Test handling of ambiguous dates with different settings
        # This may help cover some of the date resolution logic
        
        # Test dayfirst parameter effects
        result_month_first = parse("01/13/2023", dayfirst=False)  # MM/dd/yyyy
        result_day_first = parse("13/01/2023", dayfirst=True)     # dd/MM/yyyy
        
        self.assertEqual(result_month_first.month, 1)
        self.assertEqual(result_month_first.day, 13)
        self.assertEqual(result_day_first.month, 1) 
        self.assertEqual(result_day_first.day, 13)
    
    def test_microsecond_parsing(self):
        # Test microsecond parsing edge cases
        result1 = parse("2023-01-01 12:30:45.123456")
        result2 = parse("2023-01-01 12:30:45.123")
        result3 = parse("2023-01-01 12:30:45,123456")  # Comma separator
        
        self.assertEqual(result1.microsecond, 123456)
        self.assertEqual(result2.microsecond, 123000)
        self.assertEqual(result3.microsecond, 123456)


if __name__ == '__main__':
    unittest.main()