#!/bin/bash
# Launch llama-server with pinned flags for reproducible testing
# Prerequisites: llama-server binary in PATH, model file in models/

set -e

# Configuration (adjust these based on your hardware)
MODEL_PATH="${MODEL_PATH:=models/Mistral-7B-Instruct-v0.1.Q4_K_M.gguf}"
LLAMA_SERVER_PORT="${LLAMA_SERVER_PORT:=8080}"
LLAMA_SERVER_HOST="${LLAMA_SERVER_HOST:=0.0.0.0}"  # 0.0.0.0 so other laptops on the
                                                    # network can reach it; llama-server
                                                    # defaults to 127.0.0.1 (loopback
                                                    # only) if --host is omitted.
NUM_PARALLEL="${NUM_PARALLEL:=4}"      # -np/--parallel: number of server slots
NUM_THREADS="${NUM_THREADS:=4}"        # -t: CPU threads (adjust for your machine)

# -c/--ctx-size is the TOTAL context llama-server allocates, and it divides that
# EVENLY across NUM_PARALLEL slots (confirmed empirically: --parallel 4 --ctx-size 2048
# produces n_ctx_slot=512, not 2048 per slot). So CONTEXT_SIZE must scale with
# NUM_PARALLEL, or each slot silently gets a much smaller context than the number
# looks like. Default per-slot budget is sized to fit Profile D's ~2112-token
# maximum-cost requests (loadgen/profiles/profile-d.js) with headroom.
# See docs/MANUAL_CONFIG.md.
CONTEXT_SIZE_PER_SLOT="${CONTEXT_SIZE_PER_SLOT:=2560}"
CONTEXT_SIZE="${CONTEXT_SIZE:=$((NUM_PARALLEL * CONTEXT_SIZE_PER_SLOT))}"

# Verify model file exists
if [ ! -f "$MODEL_PATH" ]; then
    echo "Error: Model file not found at $MODEL_PATH"
    echo "Download instructions: see service/README.md"
    exit 1
fi

# Verify llama-server is in PATH
if ! command -v llama-server &> /dev/null; then
    echo "Error: llama-server binary not found in PATH"
    echo "Install llama.cpp from: https://github.com/ggerganov/llama.cpp"
    exit 1
fi

# Print launch info
echo "=========================================="
echo "llama-server Configuration"
echo "=========================================="
echo "Model:              $MODEL_PATH"
echo "Host:                $LLAMA_SERVER_HOST"
echo "Port:               $LLAMA_SERVER_PORT"
echo "Max parallel:       $NUM_PARALLEL"
echo "CPU threads:        $NUM_THREADS"
echo "Context size:       $CONTEXT_SIZE total (~$CONTEXT_SIZE_PER_SLOT per slot)"
echo "Metrics enabled:    yes (GET /metrics)"
echo "=========================================="
echo ""
echo "Starting llama-server..."
echo "Once ready, verify reachability with:"
echo "  curl http://localhost:$LLAMA_SERVER_PORT/metrics"
echo ""
echo "To target from another machine on the same network:"
echo "  1. Find this machine's LAN IP (e.g. 'ip addr' or 'ifconfig' on Linux/macOS,"
echo "     'ipconfig' on Windows) and post it in the team chat (CLAUDE.md checklist)."
echo "  2. Everyone else sets LLAMA_SERVER_URL=http://<that-ip>:$LLAMA_SERVER_PORT in their .env"
echo ""
echo "REMINDER: TOTAL_LLAMA_SLOTS in the Shield's .env MUST equal NUM_PARALLEL ($NUM_PARALLEL)"
echo "or Defense C (slot reservation) will silently do the wrong thing. See docs/MANUAL_CONFIG.md."
echo ""

# Launch llama-server with pinned flags
llama-server \
    --model "$MODEL_PATH" \
    --host "$LLAMA_SERVER_HOST" \
    --port "$LLAMA_SERVER_PORT" \
    --parallel "$NUM_PARALLEL" \
    --threads "$NUM_THREADS" \
    --ctx-size "$CONTEXT_SIZE" \
    --metrics
