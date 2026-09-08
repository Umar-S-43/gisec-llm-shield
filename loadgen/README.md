# Loadgen: Load Profiles & Stress Scenarios

k6 scripts (open-loop, arrival-rate based) and a Locust multi-cohort scenario.

## Exit Criterion

- 4 canonical load profiles implemented as k6 scripts: A (normal), B (spike),
  C (sustained flood), D (slow/low-rate, high-cost) — see CLAUDE.md for why D matters most
- 1 legitimate probe cohort (`probe.js`) that runs concurrently with any attack profile
- `run_comparison.sh` — interleaved defense-off/defense-on harness (off, on, off, on…)
- All k6 scripts use **open-loop** executors (`constant-arrival-rate` /
  `ramping-arrival-rate`), never plain VU+sleep — closed-loop generators hide the
  overload we're trying to measure ("coordinated omission")
- Every run reports `dropped_iterations` alongside p50/p95/p99/max latency, and never
  reports standard deviation
- All scripts read `LLAMA_SERVER_URL` from environment — no hardcoded IPs

## One-Command Run

```bash
# Load LLAMA_SERVER_URL from .env, then run any single profile:
export $(grep -v '^#' .env | xargs)
k6 run loadgen/profiles/baseline.js      # Profile A — normal
k6 run loadgen/profiles/spike.js         # Profile B — spike
k6 run loadgen/profiles/sustained.js     # Profile C — sustained flood
k6 run loadgen/profiles/profile-d.js     # Profile D — slow, high-cost (key differentiator)
k6 run loadgen/profiles/probe.js         # legitimate probe cohort (run alongside B/C/D)
```

## The Real Test: Interleaved On/Off Comparison

```bash
export $(grep -v '^#' .env | xargs)   # needs LLAMA_SERVER_URL and SHIELD_URL
bash loadgen/run_comparison.sh profile-d 3
```

This runs `<profile>` and `probe.js` concurrently, alternating defense-off (straight
to `llama-server`) and defense-on (through the Shield), for the given number of
rounds — **never as two separate blocks**, because laptop CPUs heat up under sustained
load and that would bias whichever block ran second. Output lands in
`results/comparison_<profile>_<timestamp>/`.

## Load Profiles (k6)

### A — Normal (`baseline.js`)
Steady 5 req/sec, open-loop, for 2 minutes. Legitimate traffic. Baseline behavior.

### B — Spike (`spike.js`)
Ramping-arrival-rate: 5 → 40 req/sec over 10s, hold 30s, ramp down. Legitimate traffic.

### C — Sustained Flood (`sustained.js`)
Constant-arrival-rate: 50 req/sec for 2 minutes. No priority header — simulated attack.

### D — Slow/Low-Rate, High-Cost (`profile-d.js`) — **the key differentiator**
Only ~3 req/sec, but each request asks for the maximum prompt + output tokens the
server will handle. This is the profile that **defeats a naive request-counting rate
limiter** (3 req/sec looks harmless) while a token-cost-aware Shield catches it on
estimated cost. If this profile is skipped, the project's central argument — "count
tokens, not requests" — has no evidence behind it.

### Legitimate Probe Cohort (`probe.js`)
A small, constant ~0.5 req/sec stream with `X-Priority: legitimate`. Run it
**concurrently** with any attack profile (B/C/D) to measure whether the real user
survives. Its own threshold asserts `<5%` failure rate — this is the assertion that
matters most.

## Locust Multi-Cohort Scenario

`loadgen/locustfile.py` mixes `LegitimateUser` and `AttackUser`. Locust is closed-loop
by nature (it's a good complement for exploratory multi-cohort mixes) but the k6
scripts above are the ones that produce the open-loop numbers reported in the analysis.

```bash
python -m locust -f loadgen/locustfile.py --host=$LLAMA_SERVER_URL
```

## Recording Results

Each k6 script's `handleSummary` writes:
- Console text summary (iterations, dropped_iterations, error rate, p50/p95/p99/max)
- `results/k6_<scenario>_<timestamp>.json` — machine-readable, consumed by `/analysis`

`dropped_iterations` is k6's own signal that the **load generator** could not keep up
with its configured arrival rate — report it next to every latency number so a reader
can tell "the server was slow" from "the load generator itself fell behind."

## Environment Variables

```bash
# In .env
LLAMA_SERVER_URL=http://192.168.x.x:8080   # direct-to-server (defense-off)
SHIELD_URL=http://192.168.x.x:9090         # through the Shield (defense-on)
```

**Never hardcode** server IPs or ports in scripts; always read from these env vars.
The IP changes every session (see CLAUDE.md session-start checklist) since the team
isn't on a permanent network.

## Dependencies

**k6:** Separate binary, not a Python dependency. [Install instructions](https://k6.io/docs/getting-started/installation/).

**Locust:** Installed via `analysis/requirements.txt`:
```bash
pip install -r analysis/requirements.txt
```
