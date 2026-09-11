# LLM Inference Service Availability Defense Prototype

A defensive prototype for hardening LLM inference services against availability and DoS stress (OWASP LLM10:2025). Built on [llama.cpp](https://github.com/ggerganov/llama.cpp) (llama-server), running CPU-only on laptops. Server and load-generator laptops connect over the same network during scheduled sessions.

**Note:** This is a 4-day hackathon project. Infrastructure is ephemeral; server/load-gen machines join via same network for short sessions. No fixed IPs or permanent connections assumed.

## Architecture

The system is a four-stage pipeline: a load generator, a shield proxy, the inference server, and an offline analysis layer. Traffic flows left to right; metrics flow back the other way.

1. **Load Generator**: Runs on its own machine and reads the target URL from LLAMA_SERVER_URL, pointing either at the shield (normal runs) or directly at llama-server (baseline runs). k6 produces the four load profiles and the legitimate probe cohort using open-model arrival-rate executors, so offered load does not silently back off when the server slows. Locust handles multi-cohort scenarios where a legitimate user class and a heavy attacker class share one timeline.

2. **Shield Proxy (FastAPI)**: The defensive core. It reads LLAMA_SERVER_URL pointing at llama-server and applies three policies in order: token-bucket admission control (charging estimated input plus weighted output tokens, not a flat request count, with fast 429 and Retry-After when over budget); queue-aware shedding (watching llamacpp:requests_deferred and /slots?fail_on_no_slot=1 and rejecting low-priority requests before they pile up); and priority-tiered fair queuing (a reserved share for interactive traffic, plus wait-time aging so low-priority requests cannot starve). Admitted requests are forwarded as ordinary HTTP.

3. **llama-server**: Started with --metrics enabled, which is required for the Prometheus endpoint to exist. Reads the model from disk and exposes an OpenAI-compatible API. Its config is pinned in service/start.sh; the knobs that matter are -np (slots), -t/-tb (threads), and -c (context), set low so the server saturates at single-digit requests per second. Two observability surfaces feed the shield and analysis: /metrics (carrying llamacpp:requests_deferred, the llamacpp:slots_* family, and llamacpp:prompt_tokens_*) and /slots, which returns 503 under fail_on_no_slot=1 when no slot is free. These are the CPU-stack substitute for the KV-cache metric GPU gateways use.

4. **Analysis Scripts (Python)**: Run offline after each session. They compute bootstrap confidence intervals for latency percentiles, Wilson intervals for proportions (error rate, legitimate-cohort survival, false-positive rate), generate charts from raw CSVs, and detect session drift, thermal drift, and cross-session inconsistency so run-order effects stay visible.

5. **Data flow and storage**: Traffic goes generator → shield → llama-server; metrics are scraped from /metrics and written to per-run CSVs. Results live in /results/*.csv, gitignored except for .gitkeep. Each session records metadata alongside its data: date, host, generator, and captured metrics, so any figure in the report traces back to a specific reproducible run.


## Quick Start

### Prerequisites

- **Python 3.11** (exact version required for reproducibility)
- **k6** (separate binary, not a Python dependency) — [install from k6.io](https://k6.io/docs/getting-started/installation/)
- **llama.cpp** binary (`llama-server`) — See [/service/README.md](/service/README.md)

### Setup

1. **Clone and enter the repo:**
   ```bash
   git clone <repo-url>
   cd <repo>
   ```

2. **Create `.env` from the template:**
   ```bash
   cp .env.example .env
   # Edit .env and set LLAMA_SERVER_URL to the actual server IP/port
   # e.g., http://192.168.x.x:8080
   ```

3. **Install Python dependencies (shield + analysis):**
   ```bash
   pip install -r shield/requirements.txt
   pip install -r analysis/requirements.txt
   ```

### Running the Service

See [/service/README.md](/service/README.md) for:
- Model download/placement instructions
- How to run `llama-server` with pinned flags
- Prometheus endpoint verification

### Running Load Tests

**Option 1: k6**
```bash
# Load LLAMA_SERVER_URL from .env
source .env  # (or set manually if on Windows)
k6 run loadgen/profiles/baseline.js
```

See [/loadgen/README.md](/loadgen/README.md) for:
- Available load profiles (A/B/C/D + legitimate probe — Profile D is the key differentiator)
- The interleaved defense-off/defense-on comparison harness (`run_comparison.sh`)
- Multi-cohort Locust scenarios

### Running the Shield Proxy

```bash
# Reads LLAMA_SERVER_URL from .env
python shield/main.py
# Shield listens on http://localhost:9090 by default
```

See [/shield/README.md](/shield/README.md) for configuration and policies.

### Running Analysis

```bash
# After a load test run, analyze results
python analysis/analyze.py results/run_20260908_120000.csv
python analysis/charts.py results/run_*.csv --output docs/
```

See [/analysis/README.md](/analysis/README.md) for available scripts and report generation.

## Repository Structure

```
.
├── .env.example           # Template for LLAMA_SERVER_URL and other config
├── README.md              # This file
├── service/               # llama-server launch script, model setup
├── shield/                # FastAPI reverse proxy with admission control
├── loadgen/               # k6 profiles + Locust scenarios
├── analysis/              # Python stats & visualization scripts
├── results/               # Raw per-request CSVs (gitignored)
└── docs/                  # Architecture, evaluation protocol, session log, reports
```

## Key Constraints & Assumptions

- **Ephemeral connectivity:** Server and load generator connect via phone hotspot; no fixed IPs or persistent connections.
- **Single config point:** All components read `LLAMA_SERVER_URL` from the environment (`.env`). No hardcoded IPs anywhere.
- **CPU-only:** No GPU flags, no CUDA, no cloud infrastructure.
- **Pinned dependencies:** Python deps locked to exact versions in `requirements.txt` to prevent drift during short shared sessions.
- **No CI/CD:** Manual runs only; no automated testing infrastructure (4-day timeline).
- **Manual config sync:** Several values (e.g. `-np` vs. the Shield's slot count) must be kept in sync by hand across files — see [docs/MANUAL_CONFIG.md](docs/MANUAL_CONFIG.md) before changing `-np` or tuning any threshold.

## Workstream Branches

Each team member creates a feature branch for their workstream:

- `feature/service` — llama-server setup, model download, Prometheus config
- `feature/shield` — admission control, queue awareness, fair queuing
- `feature/loadgen` — k6 profiles, Locust scenarios, multi-cohort design
- `feature/analysis` — statistical analysis, chart generation, drift detection

**Branch strategy:** Keep PRs small, merge same-day to main. Do not let branches diverge more than a day (4-day timeline is tight).

## Troubleshooting

- **"Connection refused" when reaching LLAMA_SERVER_URL:** Check that the server machine's IP matches what's in `.env`, that the port is open, and that `llama-server` is running.
- **Shield proxy can't reach llama-server:** Verify `LLAMA_SERVER_URL` env var is set correctly in the shield process environment.
- **Load generator results are empty:** Check that the target URL (LLAMA_SERVER_URL or shield URL) is reachable; verify the load profile syntax in k6 scripts.

---

**Hackathon:** GISEC (4 days)  
**Defense focus:** Availability & DoS mitigation (OWASP LLM10:2025)
