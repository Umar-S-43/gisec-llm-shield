# LLM Inference Service Availability Defense Prototype

A defensive prototype for hardening LLM inference services against availability and DoS stress (OWASP LLM10:2025). Built on [llama.cpp](https://github.com/ggerganov/llama.cpp) (llama-server), running CPU-only on laptops. Server and load-generator laptops connect over a phone hotspot during scheduled sessions.

**Note:** This is a 4-day hackathon project. Infrastructure is ephemeral; server/load-gen machines join via phone hotspot for short sessions. No fixed IPs or permanent connections assumed.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Load Generator Machine (k6 / Locust)                               │
│ Reads LLAMA_SERVER_URL or shield URL from env                      │
│                                                                     │
│   ┌─────────────────────────────────┐                              │
│   │ k6 (4 load profiles +           │                              │
│   │    legitimate probe cohort)      │                              │
│   │ Locust (multi-cohort scenarios)  │                              │
│   └──────────────┬──────────────────┘                              │
│                  │ (HTTP traffic)                                   │
└──────────────────┼──────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Shield Proxy (FastAPI)                                              │
│ Reads LLAMA_SERVER_URL from env (points to llama-server)           │
│                                                                     │
│   ┌──────────────────────────────────────────────────────────────┐ │
│   │ Token-bucket admission control                               │ │
│   │ Queue-aware load shedding (llamacpp:requests_deferred,       │ │
│   │   /slots?fail_on_no_slot=1)                                  │ │
│   │ Priority-tiered fair queuing                                 │ │
│   └────────────────┬─────────────────────────────────────────────┘ │
│                    │ (forwarded HTTP)                               │
└────────────────────┼───────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ llama-server (--metrics flag enabled)                               │
│ Reads model from disk; exposes Prometheus text metrics at           │
│ /metrics endpoint                                                   │
│                                                                     │
│   Key metrics:                                                      │
│   - llamacpp:requests_deferred (queue depth)                       │
│   - llamacpp:slots_* (slot usage)                                  │
│   - llamacpp:prompt_tokens_* (processing metrics)                  │ 
│                                                                     │
│   Config: --metrics -np/-t/-c flags pinned in service/start.sh     │
└────────────────────┬────────────────────────────────────────────────┘
                     │
                     ▼
            (Prometheus text format)
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Analysis Scripts (Python)                                            │
│                                                                     │
│   - Bootstrap CI for latency percentiles                           │
│   - Wilson CI for proportions (error rates, success %)             │
│   - Chart generation from raw CSVs                                 │
│   - Session drift & thermal-drift detection                        │
│   - Cross-session consistency checks                               │
└─────────────────────────────────────────────────────────────────────┘

Results stored in /results/*.csv (gitignored except .gitkeep)
Session metadata: date, host, generator, recorded metrics
```

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
- Available load profiles (4 profiles + legitimate probe)
- Multi-cohort Locust scenarios
- How to select profile by workload type

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

## Session Log

| Date | Host Machine | Load Generator | What Ran | Notes |
|------|--------------|---|---|---|
| 2026-09-08 | laptop-a (admin) | laptop-b | Baseline k6 run | Established test harness |
| | | | | |
| | | | | |

Update this table as you run experiments. Include date, which laptop hosted the server, which generated load, and what metrics were recorded.

## Key Constraints & Assumptions

- **Ephemeral connectivity:** Server and load generator connect via phone hotspot; no fixed IPs or persistent connections.
- **Single config point:** All components read `LLAMA_SERVER_URL` from the environment (`.env`). No hardcoded IPs anywhere.
- **CPU-only:** No GPU flags, no CUDA, no cloud infrastructure.
- **Pinned dependencies:** Python deps locked to exact versions in `requirements.txt` to prevent drift during short shared sessions.
- **No CI/CD:** Manual runs only; no automated testing infrastructure (4-day timeline).

## Workstream Branches

Each team member creates a feature branch for their workstream:

- `feature/service` — llama-server setup, model download, Prometheus config
- `feature/shield` — admission control, queue awareness, fair queuing
- `feature/loadgen` — k6 profiles, Locust scenarios, multi-cohort design
- `feature/analysis` — statistical analysis, chart generation, drift detection

**Branch strategy:** Keep PRs small, merge same-day to main. Do not let branches diverge more than a day (4-day timeline is tight).

## Building the Repo on GitHub

1. Create a new GitHub repository
2. Push this scaffold:
   ```bash
   git remote add origin https://github.com/your-org/repo.git
   git branch -M main
   git push -u origin main
   ```
3. **Enable branch protection on `main`:**
   - Require status checks: **disabled** (no CI/CD)
   - Require approvals: **0 reviewers** (self-merge allowed)
   - Allow force pushes: **no** (use normal push + merge)
   - Dismiss stale reviews: **no**
   - Require code owner review: **no**

   Rationale: This team assembles on different laptops during short scheduled sessions. Waiting for external reviews is not viable; 0 reviewers lets each contributor self-merge to `main` after exit criteria are met.

## Troubleshooting

- **"Connection refused" when reaching LLAMA_SERVER_URL:** Check that the server machine's IP matches what's in `.env`, that the port is open, and that `llama-server` is running.
- **Shield proxy can't reach llama-server:** Verify `LLAMA_SERVER_URL` env var is set correctly in the shield process environment.
- **Load generator results are empty:** Check that the target URL (LLAMA_SERVER_URL or shield URL) is reachable; verify the load profile syntax in k6 scripts.

---

**Last updated:** 2026-09-08  
**Hackathon:** GISEC (4 days)  
**Defense focus:** Availability & DoS mitigation (OWASP LLM10:2025)
