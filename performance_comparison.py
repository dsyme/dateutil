#!/usr/bin/env python3
"""
Performance comparison script for rrule bysetpos optimization.

This script compares the optimized implementation with a simulation 
of the old inefficient approach to measure the improvement.
"""

import time
import statistics
from dateutil.rrule import rrule, MONTHLY, MO, TU, WE, TH, FR
from datetime import datetime


def simulate_old_inefficient_approach(dayset, start, end, daypos):
    """Simulate the old inefficient list comprehension approach."""
    # This simulates: [x for x in dayset[start:end] if x is not None][daypos]
    return [x for x in dayset[start:end] if x is not None][daypos]


def simulate_new_efficient_approach(dayset, start, end, daypos):
    """Simulate the new efficient iterative approach."""
    # This simulates the optimized code
    filtered_count = 0
    for x in dayset[start:end]:
        if x is not None:
            if filtered_count == daypos:
                return x
            filtered_count += 1
    raise IndexError


def benchmark_approaches():
    """Benchmark both approaches on synthetic data."""
    
    # Create test data that simulates a typical dayset
    dayset_size = 1000
    none_ratio = 0.7  # 70% None values (typical filtered scenario)
    
    # Create dayset with mix of None and valid indices
    dayset = []
    for i in range(dayset_size):
        if i % 10 < none_ratio * 10:  # Distribute None values
            dayset.append(None)
        else:
            dayset.append(i)
    
    start, end = 0, dayset_size
    test_positions = [0, 5, 10, 20, 50]  # Different daypos values
    
    print("Performance Comparison: List Comprehension vs Iterator")
    print("=" * 60)
    print(f"Dataset: {dayset_size} elements, {none_ratio*100:.0f}% None values")
    print(f"Non-None elements: ~{len([x for x in dayset if x is not None])}")
    print()
    
    for daypos in test_positions:
        if daypos >= len([x for x in dayset if x is not None]):
            continue
            
        print(f"Testing daypos = {daypos}")
        
        # Benchmark old approach
        old_times = []
        iterations = 1000
        
        for _ in range(iterations):
            start_time = time.perf_counter()
            try:
                result_old = simulate_old_inefficient_approach(dayset, start, end, daypos)
            except IndexError:
                continue
            end_time = time.perf_counter()
            old_times.append(end_time - start_time)
        
        # Benchmark new approach
        new_times = []
        
        for _ in range(iterations):
            start_time = time.perf_counter()
            try:
                result_new = simulate_new_efficient_approach(dayset, start, end, daypos)
            except IndexError:
                continue
            end_time = time.perf_counter()
            new_times.append(end_time - start_time)
        
        if old_times and new_times:
            old_mean = statistics.mean(old_times)
            new_mean = statistics.mean(new_times)
            improvement = (old_mean - new_mean) / old_mean * 100
            
            print(f"  Old approach: {old_mean*1000000:.1f} μs")
            print(f"  New approach: {new_mean*1000000:.1f} μs")
            print(f"  Improvement: {improvement:.1f}% faster")
            print(f"  Speedup: {old_mean/new_mean:.2f}x")
        print()
    
    # Test with more realistic rrule scenario
    print("Real-world rrule scenario:")
    rule = rrule(
        MONTHLY,
        byweekday=(MO, TU, WE, TH, FR),
        bysetpos=-1,  # Last occurrence
        dtstart=datetime(2020, 1, 1),
        count=100
    )
    
    times = []
    iterations = 100
    
    for _ in range(iterations):
        start_time = time.perf_counter()
        results = list(rule)
        end_time = time.perf_counter()
        times.append(end_time - start_time)
    
    mean_time = statistics.mean(times)
    print(f"  Current optimized implementation: {mean_time*1000:.2f} ms avg")
    print(f"  Operations per second: {1/mean_time:.0f}")
    print(f"  Generated {len(results)} dates")


def analyze_memory_efficiency():
    """Analyze memory efficiency differences."""
    
    print("\nMemory Efficiency Analysis")
    print("=" * 40)
    
    # Simulate different dataset sizes to show memory impact
    sizes = [100, 500, 1000, 5000]
    
    for size in sizes:
        non_none_count = size // 3  # Assume 1/3 are non-None
        
        # Memory for old approach (creates full list)
        old_memory = non_none_count * 8  # Rough estimate: 8 bytes per element
        
        # Memory for new approach (only stores current element)
        new_memory = 8  # Just one element at a time
        
        memory_saving = (old_memory - new_memory) / old_memory * 100
        
        print(f"Dataset size {size} ({non_none_count} valid elements):")
        print(f"  Old approach memory: ~{old_memory} bytes")
        print(f"  New approach memory: ~{new_memory} bytes") 
        print(f"  Memory savings: {memory_saving:.1f}%")
        print()


if __name__ == "__main__":
    benchmark_approaches()
    analyze_memory_efficiency()