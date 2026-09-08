"""
Response code and success rate analysis with Wilson confidence intervals.

Usage:
    python analysis/proportions.py results/run_20260908_baseline.csv
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path


def wilson_ci(successes, total, ci=0.95):
    """Compute Wilson score interval for a proportion."""
    if total == 0:
        return 0, (0, 0)

    p = successes / total
    z = 1.96 if ci == 0.95 else 2.576

    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    margin = z * np.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator

    ci_lower = max(0, center - margin)
    ci_upper = min(1, center + margin)

    return p * 100, (ci_lower * 100, ci_upper * 100)


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
            pct, (ci_l, ci_u) = wilson_ci(count, len(df))
            status_text = {200: "Success", 429: "Rate Limited", 503: "Overloaded", 500: "Server Error"}
            print(f"  {code} ({status_text.get(code, 'Other')}): {count}/{len(df)} ({pct:.1f}%) [95% CI: {ci_l:.1f}-{ci_u:.1f}%]")

    # By priority (if available)
    if 'priority' in df.columns:
        print("\nSuccess Rate by Priority:")
        for priority in ['legitimate', 'attack']:
            priority_df = df[df['priority'] == priority]
            if len(priority_df) > 0:
                successes = (priority_df['response_code'] == 200).sum()
                pct, (ci_l, ci_u) = wilson_ci(successes, len(priority_df))
                print(f"  {priority}: {successes}/{len(priority_df)} ({pct:.1f}%) [95% CI: {ci_l:.1f}-{ci_u:.1f}%]")

    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python proportions.py <csv_file>")
        sys.exit(1)

    csv_path = sys.argv[1]
    analyze_proportions(csv_path)
