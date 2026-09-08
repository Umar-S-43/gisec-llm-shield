# Final Report: LLM Inference Service Availability Defense

**Hackathon:** GISEC (4 days)  
**Focus:** Defending LLM inference services against availability/DoS attacks (OWASP LLM10:2025)  
**Date Completed:** [Fill in]  
**Team:** [List team members]

---

## Executive Summary

Brief overview of findings and recommendations. 1-2 paragraphs.

---

## Background

### Problem Statement

LLM inference services are vulnerable to availability attacks that exhaust computational resources (inference slots, memory, bandwidth). A malicious user sending many concurrent completion requests can cause a denial-of-service for legitimate users.

### Defensive Approach

A reverse proxy with token-bucket rate limiting, queue awareness (via `/slots` metric from llama-server), and priority-aware fair queuing can mitigate this threat.

---

## Findings

### 1. Baseline Performance (No Defense)

**Test:** Scenario 1 (5 req/sec legitimate traffic, no attack)

| Metric | Value |
|--------|-------|
| Success Rate | XX% |
| p95 Latency | XX ms |
| Thermal Drift | XX% |
| Observations | [Notes] |

---

### 2. Attack Impact (No Defense)

**Test:** Scenario 3 (50 req/sec attack traffic)

| Metric | Value |
|--------|-------|
| Success Rate | XX% |
| Legitimate Probe Success Rate* | XX% |
| p95 Latency | XX ms |
| Server Queue Depth (max) | XX requests |
| Observations | [Notes] |

*If run with concurrent legitimate probes

---

### 3. Defense Effectiveness (With Shield)

**Test:** Scenarios 3 & 5 (same attack, but with shield proxy)

| Metric | No Shield | With Shield | Improvement |
|--------|-----------|-------------|------------|
| Attack Success Rate | XX% | XX% | XX pp |
| Legitimate Success Rate | XX% | XX% | XX pp |
| Legitimate p95 Latency | XX ms | XX ms | XX% |
| Server Queue Depth (max) | XX | XX | XX% |

**Priority Queueing Effect:** When attack traffic flooded the proxy, legitimate requests were prioritized and had [XX%] success rate vs. attack traffic [XX%].

---

### 4. Stress Test Results

**Test:** Scenario 4 (ramp-up to find breaking point)

- **Breaking point identified at:** XX req/sec
- **Success rate drops to <95% at:** XX req/sec
- **p95 latency exceeds 5s at:** XX req/sec
- **Shield saturation:** Shield's token bucket depletes at approximately XX req/sec, after which all requests are rate-limited

---

### 5. Cross-Session Consistency

| Session | Scenario | p95 Latency | Deviation from Baseline |
|---------|----------|-------------|------------------------|
| Day 1 | Baseline | XX ms | — |
| Day 2 | Baseline (rerun) | XX ms | XX% |
| Day 3 | Baseline (rerun) | XX ms | XX% |

**Assessment:** [Observations on hardware variance, thermal issues, etc.]

---

## Recommendations

### Immediate (In Scope - Deploy Now)

1. **Token-bucket tuning:** Current bucket capacity of [XX] tokens/sec preserves [XX%] of legitimate traffic under [XX req/sec] attack. Consider adjusting based on acceptable loss rate.

2. **Priority header enforcement:** Mark legitimate traffic with `X-Priority: legitimate` to ensure preferential treatment. Consider authenticating this header (OAuth/JWT) if deployed to production.

3. **Queue monitoring:** Integrate llama-server metrics (`llamacpp:requests_deferred`, `/slots`) into shield logging for real-time visibility.

### Short-term (1-2 weeks)

1. **Distributed shield:** Run multiple shield proxy instances with coordinated rate limiting to handle higher throughput.

2. **Adaptive rate limiting:** Adjust token bucket refill rate based on current queue depth; be more aggressive when backlog is high.

3. **Context-aware shedding:** Prioritize shorter prompts (lower inference cost) over long prompts to maximize throughput under load.

### Long-term (Out of Scope)

1. **Model quantization:** Use smaller quantizations (Q4 vs. Q6) to reduce memory footprint and increase parallelism.

2. **Batching:** Group requests into inference batches (if llama-server supports) to amortize fixed costs.

3. **Multi-model fallback:** Route to cheaper models (e.g., smaller 7B model) if primary model is overloaded.

---

## Lessons Learned

### Technical

- [Key insight about rate limiting, queuing, or monitoring]
- [Challenge encountered and solution]
- [Surprise finding]

### Process

- [What worked well for team coordination]
- [What could be improved]
- [Recommendations for future hackathons]

---

## Appendix

### Test Configuration

- **Model:** [Model name, quantization, e.g., "Mistral 7B Q4_K_M"]
- **llama-server flags:** -np [X], -t [X], -c [X]
- **Shield bucket:** capacity=[X], refill_rate=[X]
- **Test environment:** CPU-only, no GPU, phone hotspot connectivity

### Raw Data

All per-request CSVs stored in `/results/`:
- `run_YYYYMMDD_HHMMSS_<scenario>.csv`

Analysis outputs in `/docs/charts/`:
- Latency timeseries charts
- Response code distributions
- Drift analysis plots

### References

- [ARCHITECTURE.md](ARCHITECTURE.md) — System design
- [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) — Test procedures
- [SESSION_LOG.md](SESSION_LOG.md) — Per-run metadata

---

**Report compiled by:** [Name(s)]  
**Last updated:** [Date]
