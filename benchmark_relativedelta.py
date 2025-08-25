#!/usr/bin/env python3
"""
Benchmark script for relativedelta performance testing.
"""

import timeit
import datetime
from dateutil.relativedelta import relativedelta, MO

# Test data setup
dt = datetime.datetime(2020, 3, 15, 10, 30, 45, 123456)
dt2 = datetime.datetime(2021, 6, 20, 14, 25, 30, 654321)

# Test relativedelta instances
rd1 = relativedelta(years=1, months=2, days=3, hours=4, minutes=5, seconds=6, microseconds=123)
rd2 = relativedelta(years=2, months=3, days=4, hours=5, minutes=6, seconds=7, microseconds=456)
rd3 = relativedelta(months=6, weekday=MO(1))
rd4 = relativedelta(year=2022, month=12, day=25, hour=0, minute=0, second=0)

# Test cases for different operations
test_cases = [
    # relativedelta + relativedelta operations
    ("rd_add_rd", "rd1 + rd2", {"rd1": rd1, "rd2": rd2}),
    ("rd_sub_rd", "rd1 - rd2", {"rd1": rd1, "rd2": rd2}),
    
    # relativedelta + datetime operations  
    ("rd_add_dt", "dt + rd1", {"dt": dt, "rd1": rd1}),
    ("rd_add_dt_weekday", "dt + rd3", {"dt": dt, "rd3": rd3}),
    ("rd_add_dt_absolute", "dt + rd4", {"dt": dt, "rd4": rd4}),
    
    # Unary operations
    ("rd_neg", "-rd1", {"rd1": rd1}),
    ("rd_abs", "abs(rd1)", {"rd1": rd1}),
    
    # Multiplication
    ("rd_mul", "rd1 * 3", {"rd1": rd1}),
    ("rd_mul_float", "rd1 * 2.5", {"rd1": rd1}),
    
    # Boolean evaluation
    ("rd_bool_true", "bool(rd1)", {"rd1": rd1}),
    ("rd_bool_false", "bool(relativedelta())", {"relativedelta": relativedelta}),
    
    # Construction from two datetimes
    ("rd_from_dt", "relativedelta(dt2, dt)", {"dt": dt, "dt2": dt2, "relativedelta": relativedelta}),
]

def benchmark_operation(name, expression, globals_dict, iterations=50000):
    """Benchmark a single operation."""
    time_taken = timeit.timeit(expression, globals=globals_dict, number=iterations)
    ops_per_sec = iterations / time_taken
    return {
        'name': name,
        'expression': expression,
        'time': time_taken,
        'ops_per_sec': ops_per_sec,
        'iterations': iterations
    }

def run_benchmarks():
    """Run all benchmark tests."""
    print("=" * 60)
    print("RELATIVEDELTA PERFORMANCE BENCHMARK")
    print("=" * 60)
    
    results = []
    total_ops = 0
    total_time = 0
    
    for name, expression, globals_dict in test_cases:
        result = benchmark_operation(name, expression, globals_dict)
        results.append(result)
        
        print(f"{name:20s}: {result['ops_per_sec']:>8,.0f} ops/sec "
              f"({result['time']:.4f}s for {result['iterations']:,} iterations)")
        
        total_ops += result['ops_per_sec']
        total_time += result['time']
    
    print("-" * 60)
    avg_ops_per_sec = total_ops / len(results)
    print(f"{'AVERAGE':20s}: {avg_ops_per_sec:>8,.0f} ops/sec "
          f"({total_time:.4f}s total)")
    print("=" * 60)
    
    return results, avg_ops_per_sec

if __name__ == "__main__":
    results, avg_ops = run_benchmarks()
    
    # Save results for comparison
    import json
    
    output = {
        'timestamp': datetime.datetime.now().isoformat(),
        'average_ops_per_sec': avg_ops,
        'total_test_cases': len(test_cases),
        'results': results
    }
    
    with open('benchmark_relativedelta_results.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults saved to benchmark_relativedelta_results.json")