# Architecture & Design

## System Overview

The prototype defends an LLM inference service (llama-server) against availability and DoS attacks using a layered defense strategy:

```
Load Generator (k6/Locust)
            ↓
        Shield Proxy (FastAPI)
            ↓
        llama-server (CPU-only)
            ↓
        Metrics Exporter (Prometheus text format)
            ↓
        Analysis Scripts
```

## Component Design

### 1. llama-server (Service)

- Runs on a dedicated laptop; exposes `/metrics` endpoint in Prometheus text format.
- Metrics include:
  - `llamacpp:requests_deferred` — queue depth (requests waiting for processing)
  - `llamacpp:slots_*` — slot utilization (how many inference slots are in use)
  - `llamacpp:prompt_tokens_*` — token processing metrics
- **Note:** CPU-only; no GPU, no CUDA, no vLLM. Context and parallelism flags are pinned in `service/start.sh`.

### 2. Shield Proxy (Admission Control)

- Reverse proxy (FastAPI) sitting between load generator and llama-server.
- Implements:
  - **Token-bucket rate limiting:** Admits X tokens/second; clients consume tokens per request.
  - **Queue-aware load shedding:** Polls `/slots?fail_on_no_slot=1` on llama-server; rejects new requests if no slots available.
  - **Priority-tiered fair queuing:** Requests with `X-Priority: legitimate` header are prioritized over others when shedding; attack traffic is rate-limited more aggressively.

- **Rejection strategies:**
  - `429 Too Many Requests` — Token bucket depleted or rate limit exceeded.
  - `503 Service Unavailable` — No slots available on llama-server; legitimate requests queued, others rejected.

### 3. Load Generator (k6 / Locust)

- Generates traffic from a separate machine, connected via phone hotspot.
- **k6 profiles:**
  - Baseline: 5 req/sec sustained (legitimate)
  - Spike: Ramp to 20 req/sec over 10s, hold, ramp down
  - Sustained: 50 req/sec for 2 minutes (attack simulation)
  - Ramp: 1 → 30 req/sec over 3 minutes (find breaking point)
- **Locust scenario:** Multi-cohort (LegitimateUser + AttackUser) for concurrent testing.
- All scripts read `LLAMA_SERVER_URL` from `.env`; never hardcoded.

### 4. Analysis Scripts

- Parse per-request CSVs from load tests.
- Compute:
  - Bootstrap confidence intervals for latency percentiles (p50, p95, p99)
  - Wilson score intervals for success rates and error proportions
  - Thermal drift and cross-session divergence detection
  - Charts (timeseries, distributions)

## Threat Model

**Attack Vectors:**
1. **Volumetric attack:** Many concurrent requests → exhaust inference slots → availability loss.
2. **Slowloris:** Few slow requests → occupy all slots → block legitimate users.
3. **Amplification:** Short requests → long responses → backend overload.

**Defense Mechanism:**
- Token-bucket rate limiting caps total request throughput.
- Queue awareness prevents accepting requests when no slots available (hard rejection, not soft queue).
- Priority tiers preserve service for legitimate users even under full attack.
- Per-priority admission control: legitimate traffic gets preferential queuing.

## Assumptions & Constraints

- **Ephemeral connectivity:** Server and load generator join via phone hotspot; no fixed IPs or permanent connections.
- **CPU-only inference:** No GPU acceleration; latency and throughput are bottlenecked by CPU clock and memory bandwidth.
- **Single inference engine:** llama-server is the only inference backend; no ensemble or fallback.
- **No state sharing:** Shield proxy is stateless; no distributed consensus or coordination between replicas.

## Future Work (out of scope for 4-day hack)

- Distributed shield (multiple replicas with coordinated rate limiting)
- Context-aware load shedding (e.g., prioritize shorter prompts to minimize memory footprint)
- Model quantization/batching strategies to improve throughput
- Integration with load balancers or reverse proxies (nginx, etc.)
- GPU support via llama.cpp's CUDA backend (would need architecture redesign for heterogeneous hardware)

