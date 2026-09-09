"""
Verify wilson_ci() (proportions.py) and bootstrap_ci() (analyze.py) are correct,
against three checks:

  1. wilson_ci against a known, numerically-verified Wilson score interval example.
  2. bootstrap_ci against synthetic latency data (sanity-check width and coverage).
  3. Both functions run end-to-end against analysis/fixtures/sample_run.csv, a fake
     CSV shaped like real loadgen/shield output (including a run_order column for
     future thermal-drift work — NOT implemented or exercised here, out of scope).

This is a manual, one-command verification script, not a pytest suite — run it
directly:

    python analysis/verify_ci_functions.py

No CI/CD, per CLAUDE.md; this is the same "one-command tool" pattern as
analyze.py/proportions.py, just for the CI math itself rather than a live run.
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

from proportions import wilson_ci
from analyze import bootstrap_ci

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_run.csv"


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        global _any_failed
        _any_failed = True


_any_failed = False


def test_wilson_known_example():
    print("\n=== 1. wilson_ci: known example (4 defects / 20 samples, 90% CI) ===")
    lo, hi = wilson_ci(4, 20, confidence=0.90)
    print(f"  Computed: ({lo:.4f}, {hi:.4f})")

    # Correct Wilson score interval for this input, verified numerically against
    # scipy.stats.norm — see conversation history. NOT (0.071, 0.400): that value
    # is the Clopper-Pearson EXACT interval for the same input, a different method
    # that does not agree with Wilson by construction. Do not "fix" this test to
    # match Clopper-Pearson; that would mean silently swapping the underlying math.
    expected_lo, expected_hi = 0.0931, 0.3784
    tol = 0.001
    check(
        f"lower bound ~{expected_lo} (tol {tol})",
        abs(lo - expected_lo) < tol,
    )
    check(
        f"upper bound ~{expected_hi} (tol {tol})",
        abs(hi - expected_hi) < tol,
    )


def test_bootstrap_synthetic():
    print("\n=== 2. bootstrap_ci: synthetic latency data (~200 samples, p95, 90% CI) ===")
    rng = np.random.default_rng(7)
    samples = rng.lognormal(mean=5.5, sigma=0.4, size=200)  # fake latency-shaped data

    point_estimate = np.percentile(samples, 95)
    ci_lower, ci_upper = bootstrap_ci(samples.tolist(), 95, n_resamples=2000, confidence=0.90)

    print(f"  Sample p95 (point estimate): {point_estimate:.1f}")
    print(f"  Bootstrap 90% CI:            ({ci_lower:.1f}, {ci_upper:.1f})")

    check("CI is well-formed (lower < upper)", ci_lower < ci_upper)
    check(
        "sample p95 falls within (or essentially at) the bootstrap CI",
        ci_lower - 1e-6 <= point_estimate <= ci_upper + 1e-6,
    )
    # Width sanity check, not a strict statistical guarantee: an unreasonably wide
    # or vanishing interval would indicate a bug (e.g. resampling from the wrong
    # axis, or not actually varying between resamples).
    width = ci_upper - ci_lower
    sample_range = samples.max() - samples.min()
    check(
        f"CI width ({width:.1f}) is a plausible fraction of the sample range ({sample_range:.1f}), not 0 or wildly larger",
        0 < width < sample_range,
    )


def test_end_to_end_fixture():
    print(f"\n=== 3. End-to-end against fake CSV: {FIXTURE_PATH.relative_to(Path.cwd()) if FIXTURE_PATH.is_absolute() else FIXTURE_PATH} ===")
    if not FIXTURE_PATH.exists():
        check(f"fixture file exists at {FIXTURE_PATH}", False)
        return

    df = pd.read_csv(FIXTURE_PATH)
    check("fixture has run_order column (shape-compat for future drift work, unused here)", "run_order" in df.columns)
    check("fixture has priority column", "priority" in df.columns)
    check("fixture has latency_ms column", "latency_ms" in df.columns)
    check("fixture has success column", "success" in df.columns)

    n = len(df)
    successes = int(df["success"].sum())
    lo, hi = wilson_ci(successes, n, confidence=0.90)
    print(f"  Overall success rate: {successes}/{n} = {successes/n*100:.1f}% [90% CI: {lo*100:.1f}-{hi*100:.1f}%]")
    check("overall wilson_ci is well-formed", 0.0 <= lo <= hi <= 1.0)

    for tier in ("legitimate", "attack"):
        tier_df = df[df["priority"] == tier]
        tier_successes = int(tier_df["success"].sum())
        t_lo, t_hi = wilson_ci(tier_successes, len(tier_df), confidence=0.90)
        print(f"  {tier:>10} success rate: {tier_successes}/{len(tier_df)} = {tier_successes/len(tier_df)*100:.1f}% [90% CI: {t_lo*100:.1f}-{t_hi*100:.1f}%]")
        check(f"{tier} wilson_ci is well-formed", 0.0 <= t_lo <= t_hi <= 1.0)

    successful_latencies = df.loc[df["success"], "latency_ms"].values
    p95_point = np.percentile(successful_latencies, 95)
    p95_lo, p95_hi = bootstrap_ci(successful_latencies.tolist(), 95, confidence=0.90)
    print(f"  p95 latency (successful requests only): {p95_point:.1f} ms [90% CI: {p95_lo:.1f}-{p95_hi:.1f} ms]")
    check("end-to-end bootstrap_ci is well-formed", p95_lo < p95_hi)


if __name__ == "__main__":
    test_wilson_known_example()
    test_bootstrap_synthetic()
    test_end_to_end_fixture()

    print()
    if _any_failed:
        print("One or more checks FAILED — see above.")
        sys.exit(1)
    else:
        print("All checks passed.")
        sys.exit(0)
