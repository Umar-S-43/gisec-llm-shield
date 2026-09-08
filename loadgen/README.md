# Loadgen: Load Profiles & Stress Scenarios

k6 scripts and Locust scenarios for multi-cohort stress testing.

## Exit Criterion

By end of workstream session:
- 4 load profiles implemented in k6 (baseline, spike, sustained, ramp)
- 1 legitimate probe cohort (low-volume, realistic queries)
- Locust scenario file for multi-cohort runs
- All scripts read `LLAMA_SERVER_URL` from environment (no hardcoded IPs)
- One-command run for each profile; results output as CSV with per-request metadata

## Quick Start

### k6 Baseline Profile

```bash
# Load LLAMA_SERVER_URL from .env
export $(grep LLAMA_SERVER_URL .env | xargs)
k6 run loadgen/profiles/baseline.js
```

### Locust Multi-Cohort Scenario

```bash
# Run multi-cohort scenario (mix of attack + legitimate traffic)
# Reads LLAMA_SERVER_URL from env
python -m locust -f loadgen/locustfile.py --host=$LLAMA_SERVER_URL
```

## Load Profiles (k6)

Design 4 profiles to evaluate shield's effectiveness:

### 1. Baseline (loadgen/profiles/baseline.js)
- Sustained low load (~5 req/sec for 2 minutes)
- Simulates normal legitimate usage
- Expected: 100% success rate, <1s latency p95

### 2. Spike (loadgen/profiles/spike.js)
- Ramp to 20 req/sec over 10 seconds
- Hold at peak for 30 seconds
- Ramp down over 10 seconds
- Simulates traffic surge (legitimate or DoS)
- Expected: Some errors or queuing under shield

### 3. Sustained Attack (loadgen/profiles/sustained.js)
- 50+ concurrent requests sustained for 2 minutes
- No priority headers (simulated attack traffic)
- Expected: Heavy load shedding on shield, mostly `429`/`503` responses

### 4. Ramp-Up (loadgen/profiles/ramp.js)
- Linear ramp from 1 to 30 req/sec over 3 minutes
- Helps identify breaking point / queue saturation
- Expected: Gradual degradation in success rate

## Legitimate Probe Cohort

Requests sent with `X-Priority: legitimate` header to bypass or queue fairly:

```javascript
let response = http.post(url, payload, {
    headers: {
        'X-Priority': 'legitimate'
    }
});
```

Include this cohort in multi-cohort runs to measure shield's ability to preserve service for legitimate users even under attack.

## Locust Scenario

`loadgen/locustfile.py` implements:
- `LegitimateUser` — Low volume, `X-Priority: legitimate` header
- `AttackUser` — High volume, no priority header
- Swarm configuration to mix cohorts

Run with:
```bash
python -m locust -f loadgen/locustfile.py --host=$LLAMA_SERVER_URL
```

## Recording Results

Each script should output a CSV file with:
- `timestamp` (ISO 8601)
- `request_type` (completion, chat, etc.)
- `response_code` (200, 429, 503, etc.)
- `latency_ms` (response time in milliseconds)
- `error_message` (if any)
- `priority` (legitimate or attack)
- `server_url` (target: llama-server or shield proxy)

Example: `results/run_20260908_120000_baseline.csv`

Store in `/results/` (gitignored except .gitkeep).

## Dependencies

**k6:** Installed separately (not a Python dependency).
```bash
# Install k6: https://k6.io/docs/getting-started/installation/
k6 version  # Verify
```

**Locust:** Installed via `analysis/requirements.txt`:
```bash
pip install -r analysis/requirements.txt
```

## Environment Variables

Both k6 and Locust read from `.env`:

```bash
# In .env
LLAMA_SERVER_URL=http://192.168.x.x:8080

# Scripts read it:
export $(grep LLAMA_SERVER_URL .env | xargs)
```

**Never hardcode** server IPs or ports in scripts; always read from `LLAMA_SERVER_URL`.

