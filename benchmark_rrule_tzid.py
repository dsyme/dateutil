#!/usr/bin/env python3
"""
Benchmark script for rrule TZID regex pre-compilation optimization.
Tests performance impact of the regex optimization in rrulestr parsing.
"""

import time
from dateutil.rrule import rrulestr

def benchmark_rrulestr_with_tzid():
    """Benchmark rrulestr parsing with TZID patterns."""
    
    # Sample rrule strings with TZID patterns that trigger the regex
    test_cases = [
        # Basic RRULE with TZID
        "DTSTART;TZID=America/New_York:20210101T090000\nRRULE:FREQ=DAILY;COUNT=10",
        
        # EXDATE with TZID  
        "DTSTART:20210101T090000\nEXDATE;TZID=Asia/Tokyo:20210108T090000\nRRULE:FREQ=DAILY;COUNT=5",
        
        # Different timezone
        "DTSTART;TZID=Europe/London:20210101T090000\nRRULE:FREQ=WEEKLY;COUNT=4",
        
        # Simple case with timezone
        "DTSTART;TZID=UTC:20210101T000000\nRRULE:FREQ=HOURLY;COUNT=24"
    ]
    
    # Warm up
    for test_case in test_cases:
        rrulestr(test_case)
    
    # Benchmark
    iterations = 10000
    start_time = time.perf_counter()
    
    for i in range(iterations):
        for test_case in test_cases:
            rrulestr(test_case)
    
    end_time = time.perf_counter()
    total_time = end_time - start_time
    ops_per_sec = (iterations * len(test_cases)) / total_time
    
    print(f"RRULE TZID Parsing Benchmark Results:")
    print(f"Total operations: {iterations * len(test_cases):,}")
    print(f"Total time: {total_time:.4f} seconds")
    print(f"Operations per second: {ops_per_sec:.0f}")
    print(f"Average time per operation: {(total_time / (iterations * len(test_cases))) * 1000:.3f} ms")
    
    return ops_per_sec

if __name__ == "__main__":
    ops_per_sec = benchmark_rrulestr_with_tzid()