# Service: llama-server Setup & Launch

This workstream is responsible for running the llama-server inference engine, exposing metrics, and documenting model setup.

## Exit Criterion

By end of workstream session:
- llama-server running with `--metrics` flag enabled
- Prometheus text metrics endpoint (`/metrics`) reachable at the server IP
- Model file downloaded and placed in correct directory
- `start.sh` script documented and tested from a fresh machine

## Model Setup

### Download Model

llama.cpp recommends GGUF-format models. Example with Mistral 7B:

```bash
# From the llama.cpp/models directory (or anywhere convenient)
wget https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.1-GGUF/resolve/main/Mistral-7B-Instruct-v0.1.Q4_K_M.gguf
# Or use curl/your preferred downloader

# Place model file
mkdir -p models/
mv Mistral-7B-Instruct-v0.1.Q4_K_M.gguf models/
```

Adjust model size (Q4_K_M, Q5_K_M, etc.) based on available RAM. CPU inference is slower; smaller quantizations reduce memory footprint.

### One-Command Service Start

```bash
# From repo root; reads any needed env vars and launches llama-server
bash service/start.sh
```

The `start.sh` script should:
1. Check for the model file in `models/`
2. Print the server URL it's listening on
3. Launch llama-server with:
   - `--metrics` (exposes `/metrics` endpoint in Prometheus text format)
   - `-np 1` (max concurrent requests)
   - `-t 4` (CPU threads; adjust for your machine)
   - `-c 4096` (context window size — see [docs/MANUAL_CONFIG.md](../docs/MANUAL_CONFIG.md); must stay comfortably above Profile D's worst-case prompt+output token count, adjust if model differs)

### Prometheus Metrics

After llama-server starts, verify metrics are accessible:

```bash
curl http://localhost:8080/metrics | head -20
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

## Notes

- Model weights (`.gguf` files) are gitignored; document the download step in this README.
- `start.sh` should be self-contained and work from a freshly-cloned repo (minus the model file, which downloads separately).
- CPU-only: no GPU flags, no CUDA, no vLLM.

