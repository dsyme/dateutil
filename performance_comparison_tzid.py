#!/usr/bin/env python3
"""
Performance comparison script for TZID regex optimization.
This script validates the performance improvement of pre-compiled regex patterns.
"""

import time
import statistics
from dateutil.rrule import rrulestr

def run_performance_test():
    """Run comprehensive performance tests for TZID parsing optimization."""
    
    # Test cases with varying levels of TZID complexity
    test_cases = [
        ("Basic TZID", "DTSTART;TZID=America/New_York:20210101T090000\nRRULE:FREQ=DAILY;COUNT=10"),
        ("EXDATE TZID", "DTSTART:20210101T090000\nEXDATE;TZID=Asia/Tokyo:20210108T090000\nRRULE:FREQ=DAILY;COUNT=5"),
        ("Euro timezone", "DTSTART;TZID=Europe/London:20210101T090000\nRRULE:FREQ=WEEKLY;COUNT=4"),
        ("UTC simple", "DTSTART;TZID=UTC:20210101T000000\nRRULE:FREQ=HOURLY;COUNT=24"),
        ("Long timezone", "DTSTART;TZID=America/Argentina/Buenos_Aires:20210101T120000\nRRULE:FREQ=MONTHLY;COUNT=12")
    ]
    
    print("RRULE TZID Regex Optimization Performance Test")
    print("=" * 55)
    
    iterations = 5000
    results = {}
    
    for name, test_case in test_cases:
        # Warm up
        for _ in range(100):
            rrulestr(test_case)
        
        # Measure performance with multiple runs for accuracy
        times = []
        for run in range(3):
            start_time = time.perf_counter()
            
            for _ in range(iterations):
                rrulestr(test_case)
            
            end_time = time.perf_counter()
            times.append(end_time - start_time)
        
        avg_time = statistics.mean(times)
        ops_per_sec = iterations / avg_time
        results[name] = ops_per_sec
        
        print(f"{name:15s}: {ops_per_sec:8.0f} ops/sec  ({avg_time*1000/iterations:.3f} ms/op)")
    
    # Overall statistics
    overall_ops = sum(results.values())
    print("-" * 55)
    print(f"{'Overall':15s}: {overall_ops/len(results):8.0f} ops/sec average")
    print(f"Total test operations: {iterations * len(test_cases):,}")
    
    # Specific test for regex pattern matching efficiency
    print("\nTZID Pattern Extraction Efficiency:")
    print("-" * 40)
    
    # Test case specifically designed to exercise the regex
    regex_test = "DTSTART;TZID=Test/Zone:20210101T000000\nEXDATE;TZID=Another/Zone:20210201T000000\nRRULE:FREQ=DAILY;COUNT=1"
    
    start_time = time.perf_counter()
    for _ in range(10000):
        rrulestr(regex_test)
    end_time = time.perf_counter()
    
    regex_ops_per_sec = 10000 / (end_time - start_time)
    print(f"TZID extraction: {regex_ops_per_sec:.0f} ops/sec")
    
    return results

if __name__ == "__main__":
    results = run_performance_test()