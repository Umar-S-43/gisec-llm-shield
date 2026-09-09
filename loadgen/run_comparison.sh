#!/bin/bash
# Interleaved defense-off / defense-on comparison harness.
#
# Non-negotiable (see CLAUDE.md): defense-off and defense-on runs must use the
# IDENTICAL traffic pattern and must be INTERLEAVED (off, on, off, on, ...), never
# run as two separate blocks. Laptops heat up and slow down under sustained load,
# so running all "off" runs first and all "on" runs second would unfairly make
# whichever set ran second look different just because the CPU was hotter/cooler.
#
# Both legs target the SAME Shield process at SHIELD_URL and toggle its behavior
# via POST /admin/shield-active — they do NOT send the "off" leg straight to
# llama-server. Bypassing the Shield for "off" would confound the comparison with
# an extra network hop / FastAPI overhead that has nothing to do with the defense
# itself (see shield/main.py's /admin/shield-active docstring). This is what
# shield/main.py's own module docstring means by "flip this instead of standing up
# a second target" — SHIELD_ACTIVE the env var only sets the STARTUP value; this
# script is what actually flips it between rounds without restarting the process.
#
# This script also always runs the legitimate probe cohort (probe.js) concurrently
# with the attack profile and reports whether it survived.
#
# Usage:
#   export $(grep -v '^#' .env | xargs)   # load SHIELD_URL
#   bash loadgen/run_comparison.sh <profile> <rounds>
#
#   profile: spike | sustained | profile-d
#   rounds:  number of off/on pairs (default 3 — see CLAUDE.md cut list: 5 -> 3
#            is an acceptable reduction under time pressure, going below 3 is not)

set -e

PROFILE="${1:?Usage: run_comparison.sh <spike|sustained|profile-d> <rounds>}"
ROUNDS="${2:-3}"

SHIELD_URL="${SHIELD_URL:-http://localhost:9090}"

if ! curl -sf "$SHIELD_URL/health" > /dev/null; then
    echo "Error: Shield proxy not reachable at $SHIELD_URL/health"
    echo "Start it first: python shield/main.py"
    exit 1
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="results/comparison_${PROFILE}_${TIMESTAMP}"
mkdir -p "$RESULTS_DIR"

echo "=========================================="
echo "Interleaved on/off comparison: $PROFILE"
echo "Rounds: $ROUNDS (each round = 1 off run + 1 on run)"
echo "Both legs target the Shield at: $SHIELD_URL (toggled via /admin/shield-active)"
echo "Results dir: $RESULTS_DIR"
echo "=========================================="

set_shield_active() {
    local active="$1"   # true | false
    curl -sf -X POST "$SHIELD_URL/admin/shield-active" \
        -H "Content-Type: application/json" \
        -d "{\"active\": $active}" > /dev/null
}

run_leg() {
    local mode="$1"       # off | on

    local round="$2"

    echo ""
    echo "--- Round $round: defense-$mode ---"

    if [ "$mode" = "off" ]; then
        set_shield_active false
    else
        set_shield_active true
    fi

    # Legitimate probe runs concurrently in the background for this leg. Both legs
    # target the Shield ($SHIELD_URL); only its /admin/shield-active state differs.
    LLAMA_SERVER_URL="$SHIELD_URL" PROBE_DURATION="2m" \
        k6 run loadgen/profiles/probe.js \
        --summary-export="$RESULTS_DIR/round${round}_${mode}_probe.json" \
        > "$RESULTS_DIR/round${round}_${mode}_probe.log" 2>&1 &
    local probe_pid=$!

    LLAMA_SERVER_URL="$SHIELD_URL" \
        k6 run "loadgen/profiles/${PROFILE}.js" \
        --summary-export="$RESULTS_DIR/round${round}_${mode}_attack.json" \
        > "$RESULTS_DIR/round${round}_${mode}_attack.log" 2>&1

    wait "$probe_pid"
    echo "Round $round ($mode) complete."
}

for round in $(seq 1 "$ROUNDS"); do
    run_leg "off" "$round"
    run_leg "on" "$round"
done

# Leave the Shield in its normal defense-on state when the harness exits.
set_shield_active true

echo ""
echo "=========================================="
echo "All rounds complete. Raw results in: $RESULTS_DIR"
echo "Next: python analysis/compare_on_off.py $RESULTS_DIR"
echo "=========================================="
