"""
Drift detection: thermal drift within runs and cross-session divergence.

Usage:
    python analysis/drift_check.py results/run_*.csv --threshold 0.2
"""

import sys
import glob
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime


def detect_thermal_drift(df, window_size=100, drift_threshold=0.5):
    """Detect thermal drift within a single run."""
    successful = df[df['response_code'] == 200]
    if len(successful) < 2 * window_size:
        return None

    latencies = successful['latency_ms'].values
    first_window = latencies[:window_size].mean()
    last_window = latencies[-window_size:].mean()

    if first_window == 0:
        return None

    drift = (last_window - first_window) / first_window
    return drift, drift > drift_threshold


def detect_cross_session_drift(all_results, threshold=0.2):
    """Detect divergence across multiple runs."""
    if len(all_results) < 2:
        return []

    ref_p95 = all_results[0][1]
    deviations = []

    for i in range(1, len(all_results)):
        run_name, p95, session = all_results[i]
        if ref_p95 == 0:
            continue

        deviation = abs(p95 - ref_p95) / ref_p95
        is_anomaly = deviation > threshold
        deviations.append({
            'run': run_name,
            'p95': p95,
            'deviation': deviation,
            'anomaly': is_anomaly,
            'session': session,
        })

    return deviations


def check_drift(csv_files, threshold=0.2):
    """Analyze drift across runs."""
    if not csv_files:
        print("No CSV files found")
        return

    print(f"\nDrift Analysis: {len(csv_files)} runs")
    print(f"Threshold: {threshold * 100:.0f}%\n")

    all_results = []

    for csv_file in sorted(csv_files):
        if not Path(csv_file).exists():
            continue

        df = pd.read_csv(csv_file)
        run_name = Path(csv_file).stem

        # Extract session date from filename or timestamp
        try:
            date_str = run_name.split('_')[1]  # Assuming format: run_YYYYMMDD_*
            session = date_str
        except:
            session = "unknown"

        successful = df[df['response_code'] == 200]
        if len(successful) == 0:
            continue

        p95 = np.percentile(successful['latency_ms'].values, 95)
        all_results.append((run_name, p95, session))

        # Thermal drift
        drift_info = detect_thermal_drift(df)
        if drift_info:
            drift, is_anomaly = drift_info
            status = "⚠️  DRIFT DETECTED" if is_anomaly else "OK"
            print(f"{run_name}")
            print(f"  p95 latency: {p95:.0f} ms")
            print(f"  thermal drift: {drift*100:+.1f}% {status}")

    # Cross-session
    print("\nCross-Session Consistency:")
    deviations = detect_cross_session_drift(all_results, threshold)

    if not deviations:
        print("  Only one run; cannot assess cross-session drift")
    else:
        for dev in deviations:
            status = "❌ ANOMALY" if dev['anomaly'] else "✓"
            print(f"  {dev['run']}: p95={dev['p95']:.0f}ms, {dev['deviation']*100:+.1f}% {status}")

    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("csv_files", nargs="*", help="CSV files or glob pattern")
    parser.add_argument("--threshold", type=float, default=0.2, help="Deviation threshold (default 0.2 = 20%)")
    args = parser.parse_args()

    if not args.csv_files:
        print("Usage: python drift_check.py <csv_files or pattern> --threshold <ratio>")
        sys.exit(1)

    # Expand globs
    all_files = []
    for pattern in args.csv_files:
        all_files.extend(glob.glob(pattern))

    check_drift(all_files, args.threshold)
