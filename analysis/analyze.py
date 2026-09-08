"""
Latency analysis with bootstrap confidence intervals.

Usage:
    python analysis/analyze.py results/run_20260908_baseline.csv
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path


def bootstrap_ci(data, n_bootstrap=1000, ci=95):
    """Compute bootstrap CI for a metric (e.g., latency percentiles)."""
    if len(data) < 2:
        return None, (None, None)

    percentile_target = np.percentile(data, ci)
    bootstrap_samples = []

    for _ in range(n_bootstrap):
        sample = np.random.choice(data, size=len(data), replace=True)
        sample_percentile = np.percentile(sample, ci)
        bootstrap_samples.append(sample_percentile)

    bootstrap_samples = sorted(bootstrap_samples)
    ci_lower = bootstrap_samples[int(0.025 * n_bootstrap)]
    ci_upper = bootstrap_samples[int(0.975 * n_bootstrap)]

    return percentile_target, (ci_lower, ci_upper)


def analyze_csv(csv_path):
    """Analyze latency percentiles from a per-request CSV."""
    if not Path(csv_path).exists():
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    print(f"\nLatency Analysis: {csv_path}")
    print(f"Total requests: {len(df)}")

    # Success rate
    successful = df[df['response_code'] == 200]
    success_rate = len(successful) / len(df) * 100
    print(f"Success rate: {success_rate:.1f}%")

    if len(successful) == 0:
        print("No successful requests; skipping percentile analysis")
        return

    latencies = successful['latency_ms'].values
    print("\nPercentile Analysis (successful requests only):")

    for p in [50, 95, 99]:
        percentile, (ci_lower, ci_upper) = bootstrap_ci(latencies, ci=p)
        if percentile is not None:
            print(f"  p{p:2d}: {percentile:6.0f} ms [95% CI: {ci_lower:.0f}-{ci_upper:.0f} ms]")

    print(f"  max:  {latencies.max():.0f} ms")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze.py <csv_file>")
        sys.exit(1)

    csv_path = sys.argv[1]
    analyze_csv(csv_path)
