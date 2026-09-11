# Service: llama-server Setup & Launch

This workstream is responsible for running the llama-server inference engine, exposing metrics, and documenting model setup.

## Exit Criterion

By end of workstream session:
- llama-server running with `--metrics` flag enabled
- Prometheus text metrics endpoint (`/metrics`) reachable at the server IP
- Model file downloaded and placed in correct directory
- `start.sh` script documented and tested from a fresh machine

## Prerequisites

1. Install Python 3.10 or newer.
2. Install a CPU build of `llama.cpp` that provides the `llama-server` executable.
  Add the directory containing `llama-server` (or `llama-server.exe` on Windows) to
  `PATH`.
3. Run all commands below from the repository root.

Check the installation with:

```bash
llama-server --help
python --version
```

## Model Setup

### Download Model

The included downloader supports resume and several GGUF presets. Mistral is the
default, but Qwen is a better starting point on a laptop with limited RAM:

```bash
# Recommended for weak CPU-only laptops
python service/download_model.py --model qwen2.5-1.5b-instruct

# List all available presets
python service/download_model.py --list
```

To use the documented default instead:

```bash
python service/download_model.py
```

The model is stored in `models/`, which is intentionally not committed to git.
If you download a non-default preset, pass its path when starting the server, for
example `MODEL_PATH=models/qwen2.5-1.5b-instruct-q4_k_m.gguf`.

### Start on Linux, macOS, or Git Bash

```bash
# From repo root; reads any needed env vars and launches llama-server
bash service/start.sh
```

### Start on Windows PowerShell

```powershell
python service/download_model.py --model qwen2.5-1.5b-instruct
$env:MODEL_PATH = 'models/qwen2.5-1.5b-instruct-q4_k_m.gguf'
$env:NUM_THREADS = '4'
& .\service\start.ps1
```

PowerShell uses the same optional variables as Bash: `MODEL_PATH`,
`LLAMA_SERVER_PORT`, `NUM_PARALLEL`, `NUM_THREADS`, and `CONTEXT_SIZE`.

The `start.sh` script should:
1. Check for the model file in `models/`
2. Print the server URL it's listening on
3. Launch llama-server with:
   - `--metrics` (exposes `/metrics` endpoint in Prometheus text format)
   - `-np 4` (max concurrent requests — see [docs/MANUAL_CONFIG.md](../docs/MANUAL_CONFIG.md); must match shield/main.py's `total_llama_slots`)
   - `-t 4` (CPU threads; adjust for your machine)
   - `-c 4096` (context window size — see [docs/MANUAL_CONFIG.md](../docs/MANUAL_CONFIG.md); must stay comfortably above Profile D's worst-case prompt+output token count, adjust if model differs)

### Prometheus Metrics

After `llama-server` starts, verify metrics are accessible in a second terminal:

```bash
curl http://localhost:8080/metrics | head -20
```

On Windows PowerShell, use `curl.exe` to select the real curl command:

```powershell
curl.exe http://localhost:8080/metrics
```

Key metrics for the shield proxy and analysis:
- `llamacpp:requests_deferred` — requests waiting in queue
- `llamacpp:slots_*` — slot usage (busy, idle)
- `llamacpp:prompt_tokens_*` — tokens processed

### Verify Server Reachability

From another machine on the network (e.g., load generator):

```bash
# Replace 192.168.x.x with actual server IP
curl -X POST http://192.168.x.x:8080/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "n_predict": 10}'
```

Should return a completion response (may take a few seconds on CPU).

### Connect the Shield

Once the service responds locally, set the same address in the root `.env` file:

```dotenv
LLAMA_SERVER_URL=http://localhost:8080
TOTAL_LLAMA_SLOTS=1
```

For a server on another machine, replace `localhost` with that machine's LAN IP and
allow TCP port 8080 through its firewall. Start the Shield only after this URL is
reachable:

```bash
python shield/main.py
```

## Notes

- Model weights (`.gguf` files) are gitignored; document the download step in this README.
- `start.sh` and `start.ps1` should be self-contained and work from a freshly-cloned repo (minus the model file, which downloads separately).
- CPU-only: no GPU flags, no CUDA, no vLLM.

