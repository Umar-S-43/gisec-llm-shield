"""
Response code and success rate analysis with Wilson confidence intervals.

Usage:
    python analysis/proportions.py results/run_20260908_baseline.csv
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from scipy.stats import norm


def wilson_ci(successes: int, n: int, confidence: float = 0.90) -> tuple[float, float]:
    """
    Wilson score interval for a binomial proportion (success rate, error rate,
    survival rate, etc.). Returns (lower, upper) as PROPORTIONS in [0, 1], not
    percentages — multiply by 100 for display.

    Known example (verified numerically, see analysis/verify_ci_functions.py):
    wilson_ci(4, 20, confidence=0.90) ≈ (0.093, 0.378).

    Note: this is NOT the same as a Clopper-Pearson exact interval, which is a
    different method that gives a different (wider) answer for the same input
    (~(0.071, 0.401) for 4/20 @ 90%) — don't expect the two to agree.
    """
    if n == 0:
        return (0.0, 0.0)

    p = successes / n
    z = norm.ppf(1 - (1 - confidence) / 2)
    z2 = z * z

    denominator = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denominator
    margin = z * np.sqrt(p * (1 - p) / n + z2 / (4 * n**2)) / denominator

    ci_lower = max(0.0, center - margin)
    ci_upper = min(1.0, center + margin)

    return (ci_lower, ci_upper)


def analyze_proportions(csv_path):
    """Analyze response codes and success rates."""
    if not Path(csv_path).exists():
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    print(f"\nProportions Analysis: {csv_path}")
    print(f"Total requests: {len(df)}\n")

    # Overall response code distribution
    print("Response Code Distribution:")
    code_counts = df['response_code'].value_counts().sort_index()
    for code in [200, 429, 503, 500]:
        if code in code_counts.index:
            count = code_counts[code]
            ci_l, ci_u = wilson_ci(count, len(df), confidence=0.90)
            pct = count / len(df) * 100
            status_text = {200: "Success", 429: "Rate Limited", 503: "Overloaded", 500: "Server Error"}
            print(f"  {code} ({status_text.get(code, 'Other')}): {count}/{len(df)} ({pct:.1f}%) [90% CI: {ci_l*100:.1f}-{ci_u*100:.1f}%]")

    # By priority (if available)
    if 'priority' in df.columns:
        print("\nSuccess Rate by Priority:")
        for priority in ['legitimate', 'attack']:
            priority_df = df[df['priority'] == priority]
            if len(priority_df) > 0:
                successes = (priority_df['response_code'] == 200).sum()
                ci_l, ci_u = wilson_ci(successes, len(priority_df), confidence=0.90)
                pct = successes / len(priority_df) * 100
                print(f"  {priority}: {successes}/{len(priority_df)} ({pct:.1f}%) [90% CI: {ci_l*100:.1f}-{ci_u*100:.1f}%]")

    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python proportions.py <csv_file>")
        sys.exit(1)

    csv_path = sys.argv[1]
    analyze_proportions(csv_path)
