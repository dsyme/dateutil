#!/usr/bin/env python3
"""
Benchmark script for rrule bysetpos performance optimization.

This script measures the performance improvement from optimizing the 
list comprehension in the bysetpos logic.
"""

import time
import statistics
from dateutil.rrule import rrule, MONTHLY, MO, TU, WE, TH, FR
from datetime import datetime


def benchmark_bysetpos_performance():
    """Benchmark rrule performance with bysetpos parameter."""
    
    # Test case that exercises the bysetpos code path
    # This creates a rule for the last weekday of each month
    rule = rrule(
        MONTHLY,
        byweekday=(MO, TU, WE, TH, FR),
        bysetpos=-1,  # Last occurrence
        dtstart=datetime(2020, 1, 1),
        count=100  # Generate 100 occurrences
    )
    
    print("Benchmarking rrule with bysetpos parameter...")
    print(f"Rule: Monthly, last weekday, 100 occurrences")
    
    # Warm-up
    list(rule)
    
    # Benchmark
    times = []
    iterations = 50
    
    for i in range(iterations):
        start_time = time.perf_counter()
        results = list(rule)
        end_time = time.perf_counter()
        times.append(end_time - start_time)
    
    # Calculate statistics
    mean_time = statistics.mean(times)
    stdev_time = statistics.stdev(times)
    min_time = min(times)
    max_time = max(times)
    
    print(f"\nResults ({iterations} iterations):")
    print(f"Mean time: {mean_time*1000:.3f} ms")
    print(f"Std dev: {stdev_time*1000:.3f} ms")
    print(f"Min time: {min_time*1000:.3f} ms")
    print(f"Max time: {max_time*1000:.3f} ms")
    print(f"Operations/sec: {1/mean_time:.1f}")
    print(f"Generated {len(results)} dates")
    
    # Show a few sample results
    print(f"\nSample dates: {results[:5]}")
    
    return mean_time, len(results)


def benchmark_multiple_scenarios():
    """Benchmark multiple rrule scenarios that use bysetpos."""
    
    scenarios = [
        {
            "name": "Last weekday of month (100 occurrences)",
            "rule": rrule(MONTHLY, byweekday=(MO, TU, WE, TH, FR), bysetpos=-1, 
                         dtstart=datetime(2020, 1, 1), count=100)
        },
        {
            "name": "First weekday of month (50 occurrences)",
            "rule": rrule(MONTHLY, byweekday=(MO, TU, WE, TH, FR), bysetpos=1,
                         dtstart=datetime(2020, 1, 1), count=50)
        },
        {
            "name": "Second and third weekdays (75 occurrences)",
            "rule": rrule(MONTHLY, byweekday=(MO, TU, WE, TH, FR), bysetpos=(2, 3),
                         dtstart=datetime(2020, 1, 1), count=75)
        },
    ]
    
    print("=== Multi-scenario Benchmark ===")
    
    total_time = 0
    total_dates = 0
    
    for scenario in scenarios:
        print(f"Scenario: {scenario['name']}")
        
        # Warm-up
        list(scenario['rule'])
        
        # Benchmark
        times = []
        iterations = 25
        
        for _ in range(iterations):
            start_time = time.perf_counter()
            results = list(scenario['rule'])
            end_time = time.perf_counter()
            times.append(end_time - start_time)
        
        mean_time = statistics.mean(times)
        ops_per_sec = 1 / mean_time
        
        print(f"  Mean time: {mean_time*1000:.3f} ms")
        print(f"  Operations/sec: {ops_per_sec:.1f}")
        print(f"  Generated dates: {len(results)}")
        print()
        
        total_time += mean_time
        total_dates += len(results)
    
    print(f"=== Summary ===")
    print(f"Total scenarios: {len(scenarios)}")
    print(f"Average time per scenario: {total_time/len(scenarios)*1000:.3f} ms")
    print(f"Total dates generated: {total_dates}")


if __name__ == "__main__":
    print("rrule bysetpos Performance Benchmark")
    print("=" * 50)
    
    # Single scenario benchmark
    benchmark_bysetpos_performance()
    
    print("\n" + "=" * 50)
    
    # Multiple scenarios benchmark  
    benchmark_multiple_scenarios()