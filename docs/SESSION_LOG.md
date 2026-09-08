# Session Log

Record each test run here with metadata, results, and observations. Use this to track progress across the 4-day hackathon and detect cross-session drift.

## Run Table

| Date | Server Host | Load Generator Host | Scenario | Duration | Requests | Success Rate | p95 Latency | Key Findings | File |
|------|-------------|---------------------|----------|----------|----------|--------------|-------------|--------------|------|
| 2026-09-08 | laptop-a | laptop-b | Baseline (no shield) | 2m | 600 | 98.5% | 856ms | Established baseline; server stable | results/run_20260908_120000_baseline.csv |
| | | | | | | | | | |
| | | | | | | | | | |
| | | | | | | | | | |

## Column Descriptions

- **Date:** Session date (YYYY-MM-DD)
- **Server Host:** Machine/IP running llama-server (e.g., "laptop-a 192.168.1.100")
- **Load Generator Host:** Machine/IP running k6/Locust (e.g., "laptop-b 192.168.1.101")
- **Scenario:** Test profile (Baseline, Spike, Sustained, Ramp, Multi-Cohort, etc.)
- **Duration:** How long the test ran (e.g., "2m" for 2 minutes)
- **Requests:** Total number of requests sent
- **Success Rate:** (HTTP 200 / total) × 100%
- **p95 Latency:** 95th percentile response time (in milliseconds)
- **Key Findings:** Brief observation (thermal drift, priority queueing worked, etc.)
- **File:** Path to raw CSV result file in `/results/`

## Notes

- **Before each run:** Record server/generator IPs, model size, and any config changes in a brief header comment.
- **Thermal drift:** If p95 latency in last 30s is >50% higher than first 30s, flag and recommend cooldown.
- **Cross-session drift:** If same scenario run on different day shows >20% difference, document and investigate (hardware variance, network load, etc.).
- **Priority testing:** When testing multi-cohort scenarios, explicitly note if legitimate traffic was preserved (p95 latency stayed low) even when attacked.

## Example Entry Format

```
| 2026-09-08 | laptop-a (192.168.1.100) | laptop-b (192.168.1.101) | Sustained Attack (no shield) | 2m | 6000 | 34.2% | 3240ms | Server overwhelmed; all slots busy for 1.5m | results/run_20260908_140000_attack_no_shield.csv |
```

