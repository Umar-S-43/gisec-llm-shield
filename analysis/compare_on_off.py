"""
Compare interleaved defense-off vs defense-on rounds produced by
loadgen/run_comparison.sh.

Reads the round*_off_attack.json / round*_on_attack.json and
round*_off_probe.json / round*_on_probe.json files k6's handleSummary()
writes (see loadgen/profiles/lib/summary.js), and reports, for each mode:
  - dropped_iterations (always reported next to latency — see CLAUDE.md)
  - p50 / p95 / p99 / max latency (never standard deviation)
  - legitimate probe survival rate

Usage:
    python analysis/compare_on_off.py results/comparison_profile-d_20260908_140000/
"""

import sys
import json
import glob
from pathlib import Path


def load_round_jsons(results_dir, mode, kind):
    """kind: 'attack' or 'probe'."""
    pattern = str(Path(results_dir) / f"round*_{mode}_{kind}.json")
    files = sorted(glob.glob(pattern))
    rounds = []
    for f in files:
        with open(f) as fh:
            rounds.append(json.load(fh))
    return rounds


def summarize_mode(rounds, label):
    if not rounds:
        print(f"  {label}: no data found")
        return

    dropped = sum(r["dropped_iterations"] for r in rounds)
    completed = sum(r["iterations_completed"] for r in rounds)
    total = dropped + completed
    dropped_rate = dropped / total if total else 0

    p95s = [r["latency_ms"]["p95"] for r in rounds if r["latency_ms"]["p95"] is not None]
    p99s = [r["latency_ms"]["p99"] for r in rounds if r["latency_ms"]["p99"] is not None]
    maxs = [r["latency_ms"]["max"] for r in rounds if r["latency_ms"]["max"] is not None]

    print(f"  {label} ({len(rounds)} rounds):")
    print(f"    Iterations completed: {completed}, dropped: {dropped} ({dropped_rate*100:.1f}%)")
    if p95s:
        print(f"    p95 latency across rounds: {[f'{v:.0f}' for v in p95s]} ms")
    if p99s:
        print(f"    p99 latency across rounds: {[f'{v:.0f}' for v in p99s]} ms")
    if maxs:
        print(f"    max latency across rounds: {[f'{v:.0f}' for v in maxs]} ms")


def compare(results_dir):
    results_dir = Path(results_dir)
    if not results_dir.exists():
        print(f"Error: directory not found: {results_dir}")
        sys.exit(1)

    print(f"\n=== Attack traffic: defense-off vs defense-on ===")
    off_attack = load_round_jsons(results_dir, "off", "attack")
    on_attack = load_round_jsons(results_dir, "on", "attack")
    summarize_mode(off_attack, "Defense OFF")
    summarize_mode(on_attack, "Defense ON")

    print(f"\n=== Legitimate probe cohort: did it survive? ===")
    off_probe = load_round_jsons(results_dir, "off", "probe")
    on_probe = load_round_jsons(results_dir, "on", "probe")
    summarize_mode(off_probe, "Defense OFF (probe)")
    summarize_mode(on_probe, "Defense ON (probe)")

    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compare_on_off.py <results/comparison_.../ directory>")
        sys.exit(1)

    compare(sys.argv[1])
