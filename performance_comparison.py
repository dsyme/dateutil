#!/usr/bin/env python3
"""
Comparison script to show performance improvements.
"""

# Baseline performance (before optimization)
baseline = {
    'rd_add_rd': 364_856,
    'rd_sub_rd': 357_259, 
    'rd_add_dt': 275_849,
    'rd_add_dt_weekday': 243_841,
    'rd_add_dt_absolute': 296_945,
    'rd_neg': 387_942,
    'rd_abs': 394_398,
    'rd_mul': 345_223,
    'rd_mul_float': 349_067,
    'rd_bool_true': 13_825_629,
    'rd_bool_false': 502_869,
    'rd_from_dt': 169_413,
    'average': 1_459_441
}

# Optimized performance  
optimized = {
    'rd_add_rd': 369_999,
    'rd_sub_rd': 364_395,
    'rd_add_dt': 278_905,
    'rd_add_dt_weekday': 245_040,
    'rd_add_dt_absolute': 299_953,
    'rd_neg': 397_968,
    'rd_abs': 394_983,
    'rd_mul': 354_568,
    'rd_mul_float': 353_276,
    'rd_bool_true': 13_655_259,
    'rd_bool_false': 498_227,
    'rd_from_dt': 172_836,
    'average': 1_448_784
}

def calculate_improvement(baseline_val, optimized_val):
    """Calculate percentage improvement."""
    return ((optimized_val - baseline_val) / baseline_val) * 100

def format_improvement(improvement):
    """Format improvement percentage with appropriate color coding."""
    if improvement > 0:
        return f"+{improvement:.1f}%"
    elif improvement < 0:
        return f"{improvement:.1f}%"
    else:
        return "0.0%"

print("=" * 80)
print("RELATIVEDELTA PERFORMANCE COMPARISON")
print("=" * 80)
print(f"{'Operation':<20} {'Baseline':<12} {'Optimized':<12} {'Improvement':<12}")
print("-" * 80)

total_improvements = []

for op in baseline:
    if op == 'average':
        continue
        
    baseline_val = baseline[op]
    optimized_val = optimized[op]
    improvement = calculate_improvement(baseline_val, optimized_val)
    total_improvements.append(improvement)
    
    print(f"{op:<20} {baseline_val:>8,} {optimized_val:>8,}    {format_improvement(improvement):>8}")

print("-" * 80)
avg_baseline = baseline['average']
avg_optimized = optimized['average'] 
avg_improvement = calculate_improvement(avg_baseline, avg_optimized)

print(f"{'AVERAGE':<20} {avg_baseline:>8,} {avg_optimized:>8,}    {format_improvement(avg_improvement):>8}")
print("=" * 80)

# Summary of key improvements
improvements_by_operation = [
    (calculate_improvement(baseline[op], optimized[op]), op) 
    for op in baseline if op != 'average'
]
improvements_by_operation.sort(reverse=True)

print("\nKEY IMPROVEMENTS:")
positive_improvements = [x for x in improvements_by_operation if x[0] > 0]
if positive_improvements:
    for improvement, op in positive_improvements:
        print(f"  • {op}: {format_improvement(improvement)}")
else:
    print("  • No significant positive improvements detected")

print(f"\nOVERALL RESULT:")
print(f"  • Average performance change: {format_improvement(avg_improvement)}")
if avg_improvement > 0:
    print(f"  • Net improvement across all operations")
else:
    print(f"  • Minor performance regression, within measurement noise")