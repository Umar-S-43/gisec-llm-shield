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

run_leg() {
    local mode="$1"       # off | on
    local round="$2"
    local target="$3"

    echo ""
    echo "--- Round $round: defense-$mode ---"

    # Legitimate probe runs concurrently in the background for this leg.
    LLAMA_SERVER_URL="$target" PROBE_DURATION="2m" \
        k6 run loadgen/profiles/probe.js \
        --summary-export="$RESULTS_DIR/round${round}_${mode}_probe.json" \
        > "$RESULTS_DIR/round${round}_${mode}_probe.log" 2>&1 &
    local probe_pid=$!

    LLAMA_SERVER_URL="$target" \
        k6 run "loadgen/profiles/${PROFILE}.js" \
        --summary-export="$RESULTS_DIR/round${round}_${mode}_attack.json" \
        > "$RESULTS_DIR/round${round}_${mode}_attack.log" 2>&1

    wait "$probe_pid"
    echo "Round $round ($mode) complete."
}

for round in $(seq 1 "$ROUNDS"); do
    run_leg "off" "$round" "$LLAMA_SERVER_URL"
    run_leg "on" "$round" "$SHIELD_URL"
done

echo ""
echo "=========================================="
echo "All rounds complete. Raw results in: $RESULTS_DIR"
echo "Next: python analysis/analyze.py $RESULTS_DIR/*_attack.json"
echo "      python analysis/proportions.py $RESULTS_DIR/*_probe.json"
echo "=========================================="
