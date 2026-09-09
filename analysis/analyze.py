"""
Latency analysis with bootstrap confidence intervals.

Usage:
    python analysis/analyze.py results/run_20260908_baseline.csv

Method choice (documented per the research brief's explicit ask — resampling
raw per-request samples within a run vs. resampling per-run percentile point
estimates is a real choice, not a prescribed method):

We resample the RAW per-request latency samples within a single run, not the
set of run-level percentile point-estimates across runs. Reason: CLAUDE.md's
cut list allows as few as 3 runs per arm (5 -> 3 under time pressure). Bootstrapping
a set of only 3-5 point estimates would be built on far too little data to say
anything stable about the interval's shape. A single run instead has hundreds of
raw request samples, which is enough to characterize that run's own sampling
variability. Cross-run/cross-session variability (thermal drift, different
sessions/laptops) is a different question and is handled separately by
drift_check.py, not folded into this per-run CI.
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path


def bootstrap_ci(
    samples: list[float],
    percentile: float,
    n_resamples: int = 2000,
    confidence: float = 0.90,
) -> tuple[float, float]:
    """
    Nonparametric bootstrap percentile confidence interval for a given percentile
    of latency (or any other) data. `percentile` is on the 0-100 scale (e.g. 95
    for p95), matching numpy's np.percentile convention.

    Resamples `samples` with replacement `n_resamples` times, computes the
    requested percentile on each resample, and returns the (lower, upper) bound
    of the resulting distribution at the given confidence level. Returns
    (None, None) if there isn't enough data to resample meaningfully.
    """
    if len(samples) < 2:
        return (None, None)

    samples = np.asarray(samples)
    n = len(samples)
    rng = np.random.default_rng()

    boot_stats = np.empty(n_resamples)
    for i in range(n_resamples):
        resample = rng.choice(samples, size=n, replace=True)
        boot_stats[i] = np.percentile(resample, percentile)

    alpha = 1 - confidence
    ci_lower = np.percentile(boot_stats, 100 * alpha / 2)
    ci_upper = np.percentile(boot_stats, 100 * (1 - alpha / 2))

    return (float(ci_lower), float(ci_upper))


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
        point_estimate = np.percentile(latencies, p)
        ci_lower, ci_upper = bootstrap_ci(latencies, p, confidence=0.90)
        if ci_lower is not None:
            print(f"  p{p:2d}: {point_estimate:6.0f} ms [90% CI: {ci_lower:.0f}-{ci_upper:.0f} ms]")

    print(f"  max:  {latencies.max():.0f} ms")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze.py <csv_file>")
        sys.exit(1)

    csv_path = sys.argv[1]
    analyze_csv(csv_path)
