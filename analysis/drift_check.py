"""
Drift detection: thermal drift within a run, drift across run order (interleaved
rounds within one session), and cross-session divergence.

Usage:
    python analysis/drift_check.py results/run_*.csv --threshold 0.2
    python analysis/drift_check.py "results/comparison_*/round*_*.csv" --threshold 0.2
"""

import sys
import glob
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict


def detect_thermal_drift(df, window_size=100, drift_threshold=0.5):
    """Detect thermal drift within a single run (first N rows vs last N rows)."""
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


def extract_run_order(df):
    """
    Prefer the run_order column (added by loadgen/normalize_csv.py — see CLAUDE.md's
    call for a run-index/run-order column in the CSV schema) for unambiguous
    chronological ordering across runs. run_order is constant per run/CSV (which
    position this whole run occupies in its session's interleaved sequence), not
    per-request, so the first row's value is the run's value.

    Returns None if the column is absent, so callers can fall back to (fragile)
    filename-based ordering for older CSVs that predate this column.
    """
    if "run_order" in df.columns and len(df) > 0:
        return int(df["run_order"].iloc[0])
    return None


def extract_session_label(csv_path):
    """
    Best-effort session label for grouping/display only — never used for ordering;
    run_order is authoritative for that when present.

    Prefers the parent directory name (e.g. comparison_profile-d_20260908_140000/,
    produced by loadgen/run_comparison.sh) since that identifies one physical
    session in this repo's actual file layout. Falls back to the old
    'run_YYYYMMDD_*' filename heuristic for standalone CSVs that don't sit inside
    a comparison_*/ directory.
    """
    parent = Path(csv_path).parent.name
    if parent and parent not in (".", ""):
        return parent
    try:
        return Path(csv_path).stem.split('_')[1]
    except IndexError:
        return "unknown"


def detect_run_order_drift(session_runs, drift_threshold=0.5):
    """
    Detect drift across run order WITHIN one session (e.g. across interleaved
    defense-off/on rounds). CLAUDE.md calls for this explicitly: laptops
    thermal-throttle under sustained load, so the arms are interleaved specifically
    to make this visible rather than confounded with which defense ran second.

    Compares mean p95 of the first half of the run_order-sorted sequence against
    the second half — the same first-window/last-window logic as
    detect_thermal_drift, just one level up (across runs instead of across rows).
    Requires at least 4 runs with a known run_order to split meaningfully.
    """
    ordered = sorted(session_runs, key=lambda r: r['run_order'])
    if len(ordered) < 4:
        return None

    mid = len(ordered) // 2
    first_half = np.mean([r['p95'] for r in ordered[:mid]])
    second_half = np.mean([r['p95'] for r in ordered[mid:]])

    if first_half == 0:
        return None

    drift = (second_half - first_half) / first_half
    return ordered, drift, drift > drift_threshold


def compare_sessions(session_summaries, threshold=0.2):
    """Compare each session's representative p95 against the first session (reference)."""
    if len(session_summaries) < 2:
        return []

    ref = session_summaries[0]
    deviations = []
    for s in session_summaries[1:]:
        if ref['p95'] == 0:
            continue
        deviation = abs(s['p95'] - ref['p95']) / ref['p95']
        deviations.append({
            'session': s['session'],
            'p95': s['p95'],
            'ref_session': ref['session'],
            'ref_p95': ref['p95'],
            'deviation': deviation,
            'anomaly': deviation > threshold,
        })
    return deviations


def check_drift(csv_files, threshold=0.2):
    """Analyze drift across runs: within-run thermal, across-run-order, and cross-session."""
    if not csv_files:
        print("No CSV files found")
        return

    print(f"\nDrift Analysis: {len(csv_files)} runs")
    print(f"Threshold: {threshold * 100:.0f}%\n")

    runs = []
    for csv_file in sorted(csv_files):
        if not Path(csv_file).exists():
            continue

        df = pd.read_csv(csv_file)
        successful = df[df['response_code'] == 200]
        if len(successful) == 0:
            continue

        p95 = np.percentile(successful['latency_ms'].values, 95)
        run = {
            'csv_file': csv_file,
            'run_name': Path(csv_file).stem,
            'p95': p95,
            'session': extract_session_label(csv_file),
            'run_order': extract_run_order(df),
        }
        runs.append(run)

        drift_info = detect_thermal_drift(df)
        if drift_info:
            drift, is_anomaly = drift_info
            status = "DRIFT DETECTED" if is_anomaly else "OK"
            print(f"{run['run_name']}")
            print(f"  p95 latency: {p95:.0f} ms")
            print(f"  thermal drift (within run): {drift*100:+.1f}% {status}")

    if not runs:
        print("No usable runs (no successful requests found in any file)")
        return

    sessions = defaultdict(list)
    for r in runs:
        sessions[r['session']].append(r)

    print("\nDrift Across Run Order (within each session):")
    for session_name, session_runs in sessions.items():
        missing_order = [r for r in session_runs if r['run_order'] is None]
        if missing_order:
            print(
                f"  [{session_name}] {len(missing_order)}/{len(session_runs)} CSVs lack a "
                f"run_order column; skipping (re-generate with loadgen/normalize_csv.py)"
            )
            continue

        result = detect_run_order_drift(session_runs, threshold)
        if result is None:
            print(f"  [{session_name}] fewer than 4 runs with run_order; cannot assess")
            continue

        ordered, drift, is_anomaly = result
        status = "DRIFT DETECTED" if is_anomaly else "OK"
        sequence = [(r['run_order'], f"{r['p95']:.0f}ms") for r in ordered]
        print(f"  [{session_name}] sequence (run_order, p95): {sequence}")
        print(f"  [{session_name}] first-half vs second-half p95: {drift*100:+.1f}% {status}")

    print("\nCross-Session Consistency:")
    if len(sessions) < 2:
        print(f"  Only one session ({next(iter(sessions))}); cannot assess cross-session drift")
    else:
        session_summaries = [
            {'session': name, 'p95': float(np.mean([r['p95'] for r in session_runs]))}
            for name, session_runs in sessions.items()
        ]
        deviations = compare_sessions(session_summaries, threshold)
        ref = session_summaries[0]
        print(f"  Reference session: {ref['session']} (mean p95={ref['p95']:.0f}ms)")
        for dev in deviations:
            status = "ANOMALY" if dev['anomaly'] else "OK"
            print(f"  {dev['session']}: mean p95={dev['p95']:.0f}ms, {dev['deviation']*100:+.1f}% vs reference {status}")

    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("csv_files", nargs="*", help="CSV files or glob pattern")
    parser.add_argument("--threshold", type=float, default=0.2, help="Deviation threshold (default 0.2 = 20%%)")
    args = parser.parse_args()

    if not args.csv_files:
        print("Usage: python drift_check.py <csv_files or pattern> --threshold <ratio>")
        sys.exit(1)

    # Expand globs
    all_files = []
    for pattern in args.csv_files:
        all_files.extend(glob.glob(pattern))

    check_drift(all_files, args.threshold)
