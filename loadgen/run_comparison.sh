#!/bin/bash
# Interleaved defense-off / defense-on comparison harness.
#
# Non-negotiable (see CLAUDE.md): defense-off and defense-on runs must use the
# IDENTICAL traffic pattern and must be INTERLEAVED (off, on, off, on, ...), never
# run as two separate blocks. Laptops heat up and slow down under sustained load,
# so running all "off" runs first and all "on" runs second would unfairly make
# whichever set ran second look different just because the CPU was hotter/cooler.
#
# This script also always runs the legitimate probe cohort (probe.js) concurrently
# with the attack profile and reports whether it survived.
#
# Usage:
#   export $(grep -v '^#' .env | xargs)   # load LLAMA_SERVER_URL and SHIELD_URL
#   bash loadgen/run_comparison.sh <profile> <rounds>
#
#   profile: spike | sustained | profile-d
#   rounds:  number of off/on pairs (default 3 — see CLAUDE.md cut list: 5 -> 3
#            is an acceptable reduction under time pressure, going below 3 is not)

set -e

PROFILE="${1:?Usage: run_comparison.sh <spike|sustained|profile-d> <rounds>}"
ROUNDS="${2:-3}"

if [ -z "$LLAMA_SERVER_URL" ]; then
    echo "Error: LLAMA_SERVER_URL is not set (needed for defense-off runs)"
    exit 1
fi

SHIELD_URL="${SHIELD_URL:-http://localhost:9090}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="results/comparison_${PROFILE}_${TIMESTAMP}"
mkdir -p "$RESULTS_DIR"

echo "=========================================="
echo "Interleaved on/off comparison: $PROFILE"
echo "Rounds: $ROUNDS (each round = 1 off run + 1 on run)"
echo "Defense-off target: $LLAMA_SERVER_URL (direct to llama-server)"
echo "Defense-on target:  $SHIELD_URL (through Shield)"
echo "Results dir: $RESULTS_DIR"
echo "=========================================="

# run_order counts every leg in the ACTUAL chronological sequence they execute in
# (round1-off=1, round1-on=2, round2-off=3, ...), not just the round number. CLAUDE.md
# calls for this: laptops thermal-throttle under sustained load, so drift across the
# session needs to be visible as a column in the data, not just inferred from filenames.
RUN_ORDER=0

run_leg() {
    local mode="$1"       # off | on
    local round="$2"
    local target="$3"
    RUN_ORDER=$((RUN_ORDER + 1))

    echo ""
    echo "--- Round $round: defense-$mode (run_order=$RUN_ORDER) ---"

    # Legitimate probe runs concurrently in the background for this leg.
    # --out csv writes k6's raw per-request samples (not just the aggregate summary) —
    # normalize_csv.py reshapes that into the per-request CSV /analysis reads.
    LLAMA_SERVER_URL="$target" PROBE_DURATION="2m" \
        k6 run loadgen/profiles/probe.js \
        --summary-export="$RESULTS_DIR/round${round}_${mode}_probe.json" \
        --out csv="$RESULTS_DIR/round${round}_${mode}_probe_raw.csv" \
        > "$RESULTS_DIR/round${round}_${mode}_probe.log" 2>&1 &
    local probe_pid=$!

    LLAMA_SERVER_URL="$target" \
        k6 run "loadgen/profiles/${PROFILE}.js" \
        --summary-export="$RESULTS_DIR/round${round}_${mode}_attack.json" \
        --out csv="$RESULTS_DIR/round${round}_${mode}_attack_raw.csv" \
        > "$RESULTS_DIR/round${round}_${mode}_attack.log" 2>&1

    wait "$probe_pid"

    python loadgen/normalize_csv.py \
        "$RESULTS_DIR/round${round}_${mode}_probe_raw.csv" \
        "$RESULTS_DIR/round${round}_${mode}_probe.csv" \
        --run-order "$RUN_ORDER"
    python loadgen/normalize_csv.py \
        "$RESULTS_DIR/round${round}_${mode}_attack_raw.csv" \
        "$RESULTS_DIR/round${round}_${mode}_attack.csv" \
        --run-order "$RUN_ORDER"

    echo "Round $round ($mode) complete."
}

for round in $(seq 1 "$ROUNDS"); do
    run_leg "off" "$round" "$LLAMA_SERVER_URL"
    run_leg "on" "$round" "$SHIELD_URL"
done

echo ""
echo "=========================================="
echo "All rounds complete. Raw results in: $RESULTS_DIR"
echo "Per-request CSVs (analysis-ready): $RESULTS_DIR/round*_*.csv"
echo "Next: python analysis/analyze.py $RESULTS_DIR/round1_off_attack.csv"
echo "      python analysis/proportions.py $RESULTS_DIR/round1_off_attack.csv"
echo "      python analysis/drift_check.py $RESULTS_DIR/round*_attack.csv --threshold 0.2"
echo "      python analysis/compare_on_off.py $RESULTS_DIR"
echo "=========================================="
