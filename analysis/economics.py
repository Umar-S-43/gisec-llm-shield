"""
Economic framing (research brief, "Formulas to present (no invented numbers)" and
"Goodput definition") — turns real measured data already sitting in /results into
the four cost formulas and the two goodput metrics the brief asks for. Every input
number here is either read from a committed CSV or a dated price the brief itself
already fetched and cited; nothing is invented.

Data sources used:
- results/shield_reconciliation_*.csv — real (not estimated) prompt/completion
  token counts per ADMITTED request, logged by shield/main.py's _log_reconciliation().
  Used to compute measured self-hosted tokens/sec.
- results/run_20260909_181820_phase1_baseline.csv — clean baseline latency (no
  attack), used as "typical single request latency" for Formula 1.
- results/run_20260909_182017_phase2_probe_noshield.csv and
  results/run_20260910_185041_phase4_probe_shieldfixed.csv — same attack profile
  (sustained.js, 50 req/s), no-Shield vs Shield-with-both-perf-fixes, used for the
  goodput-improvement factor N in Formula 4.
- profile-d.js's own configured token sizes (RATE=3, ~1600 prompt + 512 output
  tokens/request) — these are real values this project's own attack script sends,
  not invented, used for the denial-of-wallet exposure calculation.

Dated price sources (from the research brief, both fetched 2026-09-08):
- GCP g2-standard-4 (NVIDIA L4), us-central1: $0.706832276/hour.
- OpenAI API pricing, "chat-latest": $5.00 / 1M input tokens, $30.00 / 1M output
  tokens (Standard tier, no "prices as of" date stated on that page).

Usage:
    python analysis/economics.py
"""

import glob
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# Dated price sources -- see module docstring for citations.
GCP_L4_USD_PER_HOUR = 0.706832276
OPENAI_CHATLATEST_INPUT_USD_PER_1M = 5.00
OPENAI_CHATLATEST_OUTPUT_USD_PER_1M = 30.00

# profile-d.js's own real, configured attack shape (loadgen/profiles/profile-d.js) --
# not invented, this is what that script actually sends.
PROFILE_D_RATE_PER_SEC = 3
PROFILE_D_PROMPT_TOKENS = 1600  # MAX_PROMPT_WORDS=1200 words / 0.75 words-per-token
PROFILE_D_OUTPUT_TOKENS = 512


def measured_tokens_per_second(gap_threshold_s: float = 20.0) -> float:
    """
    Aggregate measured self-hosted output-token throughput across every committed
    shield_reconciliation_*.csv, counting only "active serving" time -- consecutive
    admitted requests less than gap_threshold_s apart. Without this filter, idle
    time between separate test sessions (the Shield ran across multiple days
    without restarting) swamps the real throughput number by two orders of
    magnitude, since (last_timestamp - first_timestamp) on a multi-day file
    includes overnight gaps, not serving time.
    """
    total_tokens = 0
    total_active_span = 0.0
    for f in glob.glob(str(RESULTS_DIR / "shield_reconciliation_*.csv")):
        df = pd.read_csv(f)
        if len(df) < 2:
            continue
        df["ts"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("ts").reset_index(drop=True)
        deltas = df["ts"].diff().dt.total_seconds()
        for i in range(1, len(df)):
            dt = deltas[i]
            if dt is not None and 0 < dt <= gap_threshold_s:
                total_active_span += dt
                total_tokens += df.loc[i, "completion_tokens_actual"]
    if total_active_span == 0:
        return 0.0
    return total_tokens / total_active_span


def formula_1_gpu_hour_cost_per_request(median_latency_ms: float) -> float:
    """
    GPU-hour unit cost of a request (self-hosted), per the brief's Formula 1.
    Framing, stated explicitly: this is "what one request's measured duration
    would cost if you were billed for a rented GPU-hour for exactly that long" --
    NOT a claim that a GPU would take the same time (GPUs are far faster; this
    doesn't simulate GPU speed, it prices OUR measured latency at a GPU's dollar
    rate, which is the comparison the brief's own table structure calls for).
    """
    hours = (median_latency_ms / 1000.0) / 3600.0
    return hours * GCP_L4_USD_PER_HOUR


def formula_2_cost_per_1k_tokens(tokens_per_sec: float) -> float:
    """
    Cost per 1k tokens served, self-hosted (Formula 2). Real self-hosted marginal
    cost on already-owned hardware is $0 -- this number is only meaningful as a
    labeled substitution: "if this SAME measured throughput were billed at a rented
    GPU's hourly rate" (again, not claiming the GPU would run at this speed).
    """
    seconds_per_1k = 1000.0 / tokens_per_sec
    usd_per_second = GCP_L4_USD_PER_HOUR / 3600.0
    return seconds_per_1k * usd_per_second


def formula_3_denial_of_wallet_per_hour() -> dict:
    """
    Denial-of-wallet exposure per attacker-hour (Formula 3): what profile-d.js's
    real, already-configured attack shape would cost an operator per hour if it
    hit a managed API instead of a self-hosted server, at zero defense (i.e. the
    Phase 2 scenario, applied to a billed API instead of a free-to-us laptop).
    """
    requests_per_hour = PROFILE_D_RATE_PER_SEC * 3600
    input_tokens_per_hour = requests_per_hour * PROFILE_D_PROMPT_TOKENS
    output_tokens_per_hour = requests_per_hour * PROFILE_D_OUTPUT_TOKENS

    input_cost = (input_tokens_per_hour / 1_000_000) * OPENAI_CHATLATEST_INPUT_USD_PER_1M
    output_cost = (output_tokens_per_hour / 1_000_000) * OPENAI_CHATLATEST_OUTPUT_USD_PER_1M

    return {
        "requests_per_hour": requests_per_hour,
        "input_tokens_per_hour": input_tokens_per_hour,
        "output_tokens_per_hour": output_tokens_per_hour,
        "input_cost_usd": input_cost,
        "output_cost_usd": output_cost,
        "total_cost_usd_per_hour": input_cost + output_cost,
    }


def formula_4_goodput_improvement_factor() -> dict:
    """
    Capacity-cost avoidance of the defense (Formula 4): goodput-improvement factor
    N, using the SAME attack profile (sustained.js, 50 req/s) measured with and
    without the Shield -- Phase 2 (no Shield) vs Phase 4 (Shield, both perf fixes),
    so the comparison is apples-to-apples on rate, not mixed with the 3 req/s tests.
    """
    phase2 = pd.read_csv(RESULTS_DIR / "run_20260909_182017_phase2_probe_noshield.csv")
    phase4 = pd.read_csv(RESULTS_DIR / "run_20260910_185041_phase4_probe_shieldfixed.csv")

    phase2_survival = (phase2["response_code"] == 200).mean()
    phase4_survival = (phase4["response_code"] == 200).mean()

    return {
        "phase2_survival_pct": phase2_survival * 100,
        "phase4_survival_pct": phase4_survival * 100,
        "N": phase4_survival / phase2_survival if phase2_survival else float("inf"),
    }


def goodput(csv_path: str, duration_s: float, latency_slo_ms: float = 10000) -> dict:
    """
    Goodput = completed requests/s that met the SLO (research brief's definition).
    SLO here: response_code==200 AND latency_ms <= latency_slo_ms. 10s is a
    deliberately generous, explicitly-stated threshold for this CPU-only, ~6-7s
    typical response time setup -- NOT a GPU-era SLO reused inappropriately.

    Distinguishes request-goodput (successful, SLO-conforming requests/s) from
    token-goodput (real delivered output tokens/s to those same requests), per the
    brief's explicit instruction to report both separately.
    """
    df = pd.read_csv(csv_path)
    conforming = df[(df["response_code"] == 200) & (df["latency_ms"] <= latency_slo_ms)]
    request_goodput = len(conforming) / duration_s
    return {
        "conforming_requests": len(conforming),
        "total_requests": len(df),
        "duration_s": duration_s,
        "request_goodput_per_s": request_goodput,
    }


if __name__ == "__main__":
    print("=" * 70)
    print("ECONOMIC FRAMING (research brief formulas, real measured inputs)")
    print("=" * 70)

    tps = measured_tokens_per_second()
    print(f"\nMeasured self-hosted throughput (aggregate, active-serving-time only):")
    print(f"  {tps:.3f} tokens/sec  (llamacpp:predicted_tokens_seconds equivalent)")

    baseline = pd.read_csv(RESULTS_DIR / "run_20260909_181820_phase1_baseline.csv")
    median_latency_ms = baseline.loc[baseline["response_code"] == 200, "latency_ms"].median()
    print(f"\nFormula 1 -- GPU-hour unit cost of a request:")
    print(f"  Median clean-baseline latency: {median_latency_ms:.0f}ms")
    print(f"  Priced at GCP g2-standard-4/L4 rate (${GCP_L4_USD_PER_HOUR}/hr):")
    print(f"  -> ${formula_1_gpu_hour_cost_per_request(median_latency_ms):.6f} per request")
    print(f"  (labeled substitution: prices OUR measured duration at a GPU's hourly")
    print(f"   rate -- does not claim a GPU would take the same time)")

    print(f"\nFormula 2 -- Cost per 1k tokens served, self-hosted:")
    cost_per_1k = formula_2_cost_per_1k_tokens(tps)
    print(f"  At {tps:.3f} tokens/sec, same labeled GPU-hour-rate substitution:")
    print(f"  -> ${cost_per_1k:.5f} per 1,000 tokens")

    print(f"\nFormula 3 -- Denial-of-wallet exposure per attacker-hour:")
    dow = formula_3_denial_of_wallet_per_hour()
    print(f"  profile-d.js's real configured shape: {PROFILE_D_RATE_PER_SEC} req/s,")
    print(f"  {PROFILE_D_PROMPT_TOKENS} prompt + {PROFILE_D_OUTPUT_TOKENS} output tokens/request")
    print(f"  -> {dow['requests_per_hour']:,} requests/hour if undefended")
    print(f"  -> {dow['input_tokens_per_hour']:,} input tokens/hour = ${dow['input_cost_usd']:.2f}")
    print(f"  -> {dow['output_tokens_per_hour']:,} output tokens/hour = ${dow['output_cost_usd']:.2f}")
    print(f"  -> TOTAL exposure: ${dow['total_cost_usd_per_hour']:.2f}/hour (OpenAI chat-latest pricing)")

    print(f"\nFormula 4 -- Capacity-cost avoidance (goodput-improvement factor N):")
    n = formula_4_goodput_improvement_factor()
    print(f"  Same attack profile (sustained.js, 50 req/s), Phase 2 (no Shield) vs Phase 4 (Shield):")
    print(f"  Phase 2 survival: {n['phase2_survival_pct']:.1f}%")
    print(f"  Phase 4 survival: {n['phase4_survival_pct']:.1f}%")
    print(f"  -> N = {n['N']:.1f}x")

    print("\n" + "=" * 70)
    print("GOODPUT (Phase 4: sustained.js 50 req/s, through Shield, both perf fixes)")
    print("=" * 70)
    g = goodput(str(RESULTS_DIR / "run_20260910_185041_phase4_probe_shieldfixed.csv"), duration_s=120)
    print(f"  {g['conforming_requests']}/{g['total_requests']} requests met SLO (200 AND <=10s) over {g['duration_s']}s")
    print(f"  Request-goodput: {g['request_goodput_per_s']:.3f} req/s")

    # Token-goodput: real output tokens delivered to Phase 4's SLO-conforming
    # requests, from the reconciliation log's own window (first 140s of the file
    # that spans Phase 4 -- see shield_reconciliation_20260910_183557.csv).
    recon = pd.read_csv(RESULTS_DIR / "shield_reconciliation_20260910_183557.csv")
    recon["ts"] = pd.to_datetime(recon["timestamp"])
    window = recon[(recon["ts"] - recon["ts"].min()).dt.total_seconds() <= 140]
    window = window[window["priority"] == "legitimate"]
    total_output_tokens = window["completion_tokens_actual"].sum()
    print(f"  Real output tokens delivered in this window: {total_output_tokens} ({len(window)} admitted legitimate requests)")
    print(f"  Token-goodput: {total_output_tokens / 120:.3f} tokens/sec")
