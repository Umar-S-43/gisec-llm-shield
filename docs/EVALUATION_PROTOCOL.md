# Evaluation Protocol

## Objective

Demonstrate that the shield proxy can defend an LLM inference service (llama-server) against availability/DoS attacks while preserving service quality for legitimate users.

## Test Environment

- **Server machine:** Dedicated laptop running llama-server (CPU-only).
- **Load generator machine:** Separate laptop running k6/Locust, connected via phone hotspot.
- **No GPU, no cloud infrastructure:** Everything runs locally; CPU inference only.

## Test Scenarios

### Scenario 1: Baseline (No Attack)

**Workload:** Baseline k6 profile
- 5 req/sec sustained for 2 minutes
- Legitimate requests (with `X-Priority: legitimate` header)

**Success Criteria:**
- ≥95% success rate (HTTP 200)
- p95 latency ≤ 2s
- No errors or dropped connections

**Expected Outcome:** Shield passes all traffic through; llama-server responds normally.

---

### Scenario 2: Traffic Spike

**Workload:** Spike k6 profile
- Ramp to 20 req/sec over 10 seconds
- Sustain for 30 seconds
- Ramp down over 10 seconds
- Legitimate requests

**Success Criteria:**
- ≥80% success rate during spike
- p95 latency ≤ 5s during spike
- Some requests may be rate-limited (429) or queued (503), but not all

**Expected Outcome:** Shield rate-limits aggressively but permits some legitimate traffic through. Latency increases due to queuing.

---

### Scenario 3: Sustained Attack

**Workload:** Sustained k6 profile
- 50 concurrent requests per second for 2 minutes
- Attack traffic (no `X-Priority` header)

**Success Criteria:**
- ≥50% of attack requests are rejected (429 or 503)
- If legitimate probe cohort runs concurrently, they should have ≥90% success rate

**Expected Outcome:** Shield heavily rate-limits attack traffic; legitimate probes get priority.

---

### Scenario 4: Ramp-Up (Breaking Point)

**Workload:** Ramp k6 profile
- Linear ramp from 1 to 30 req/sec over 3 minutes
- Legitimate requests

**Success Criteria:**
- Identify load at which success rate drops to <95%
- Identify load at which p95 latency exceeds 5s
- Measure shield's effectiveness across the ramp

**Expected Outcome:** Smooth degradation up to a breaking point; shield admits as much legitimate traffic as possible before hard rejection (queue full).

---

### Scenario 5: Multi-Cohort (Legitimate + Attack Mix)

**Workload:** Locust scenario
- 5 LegitimateUser instances (1-3 req/sec each, with priority header)
- 5 AttackUser instances (5+ req/sec each, no priority header)
- Run for 2 minutes

**Success Criteria:**
- Legitimate success rate ≥95%
- Attack success rate ≤50%
- Latency for legitimate requests ≤ 3s (p95)

**Expected Outcome:** Shield implements priority-aware fair queuing; legitimate users remain unaffected by attack.

## Metrics & Collection

Each load test writes a per-request CSV to `/results/run_<timestamp>.csv`:

```csv
timestamp,request_type,response_code,latency_ms,error_message,priority,server_url
2026-09-08T12:00:01.234Z,completion,200,542,,,legitimate,http://192.168.1.100:8080
...
```

### Derived Metrics

From raw CSV:
- **Success rate:** (HTTP 200 / total requests) × 100%
- **Error rate:** (non-200 / total requests) × 100%
- **p50, p95, p99 latency:** Bootstrap 95% CI for percentiles
- **Rate limit rate:** (HTTP 429 / total requests) × 100%
- **Overload rate:** (HTTP 503 / total requests) × 100%
- **By priority:** Separate success/error rates for legitimate vs. attack traffic

### Thermal Drift Check

For each run:
- Compare p95 latency in first 30 seconds vs. last 30 seconds
- Flag if drift > 50% (indicates CPU thermal throttling or memory pressure)
- If detected, recommend rerun with cooldown period

### Cross-Session Drift

Across multiple runs (same scenario, different days/machines):
- Compare p95 latency across runs
- Flag if deviation > 20% (indicates machine variance, network issues, etc.)
- Document baseline for each machine

## Acceptance Criteria (Exit Checklist)

By end of hackathon:

- [ ] Scenario 1 passes: Baseline traffic flows through shield without degradation
- [ ] Scenario 2 passes: Spike handled gracefully; legitimate traffic prioritized
- [ ] Scenario 3 passes: Attack traffic heavily rate-limited; no impact on legitimate probes
- [ ] Scenario 4 passes: Breaking point identified; metrics logged
- [ ] Scenario 5 passes: Multi-cohort test shows priority-aware queuing
- [ ] All raw CSVs collected in `/results/`
- [ ] Analysis complete: charts and drift checks generated
- [ ] Documentation: SESSION_LOG.md updated with all test runs and findings
- [ ] Report written: key findings, recommendations, lessons learned

## Run-Order & Scheduling

**Suggested schedule (4 days):**

**Day 1 (Monday):** Setup
- Deploy llama-server, run Scenario 1 (baseline)

**Day 2 (Tuesday):** Vulnerability assessment
- Run Scenario 3 (sustained attack) and Scenario 5 (multi-cohort) to show attack impact

**Day 3 (Wednesday):** Defense deployment
- Deploy shield proxy; re-run Scenarios 3 & 5 to show improvement

**Day 4 (Thursday):** Stress testing & report
- Run Scenario 2 (spike), Scenario 4 (ramp), finalize analysis, write report

## Post-Test Cleanup

- Archive raw CSVs to `/results/` with session metadata in filenames
- Generate charts and drift reports in `/docs/charts/`
- Update SESSION_LOG.md with final results
- Write-up final report with lessons learned and recommendations

