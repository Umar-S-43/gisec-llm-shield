#!/bin/bash
# Launch llama-server with pinned flags for reproducible testing
# Prerequisites: llama-server binary in PATH, model file in models/

set -e

# Configuration (adjust these based on your hardware)
MODEL_PATH="${MODEL_PATH:=models/Mistral-7B-Instruct-v0.1.Q4_K_M.gguf}"
LLAMA_SERVER_PORT="${LLAMA_SERVER_PORT:=8080}"
NUM_PARALLEL="${NUM_PARALLEL:=1}"      # -np: max concurrent requests
NUM_THREADS="${NUM_THREADS:=4}"        # -t: CPU threads (adjust for your machine)
CONTEXT_SIZE="${CONTEXT_SIZE:=2048}"   # -c: context window size

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
echo "Port:               $LLAMA_SERVER_PORT"
echo "Max parallel:       $NUM_PARALLEL"
echo "CPU threads:        $NUM_THREADS"
echo "Context size:       $CONTEXT_SIZE"
echo "Metrics enabled:    yes (GET /metrics)"
echo "=========================================="
echo ""
echo "Starting llama-server..."
echo "Once ready, verify reachability with:"
echo "  curl http://localhost:$LLAMA_SERVER_PORT/metrics"
echo ""
echo "To target from another machine, use:"
echo "  LLAMA_SERVER_URL=http://$(hostname -I | awk '{print $1}'):$LLAMA_SERVER_PORT"
echo ""

# Launch llama-server with pinned flags
llama-server \
    --model "$MODEL_PATH" \
    --port "$LLAMA_SERVER_PORT" \
    --np "$NUM_PARALLEL" \
    --threads "$NUM_THREADS" \
    --ctx-size "$CONTEXT_SIZE" \
    --metrics
