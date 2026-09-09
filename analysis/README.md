# Analysis: Statistical Scripts & Visualization

Python scripts for analyzing load test results, computing confidence intervals, and detecting drift.

## Exit Criterion

By end of workstream session:
- `analyze.py` — Computes bootstrap CI for latency percentiles (p50, p95, p99)
- `proportions.py` — Computes Wilson CI for success rate and error proportions
- `charts.py` — Generates line/bar charts from raw CSVs
- `drift_check.py` — Detects thermal drift and cross-session divergence
- All scripts read from per-request CSVs in `/results/`
- One-command invocation for each analysis type

## One-Command Usage

```bash
# Latency analysis: bootstrap CI for percentiles
python analysis/analyze.py results/run_20260908_baseline.csv

# Success rate analysis: Wilson CI for proportions
python analysis/proportions.py results/run_20260908_baseline.csv

# Chart generation from one or more runs
python analysis/charts.py results/run_*.csv --output docs/charts/

# Drift detection: cross-run consistency check
python analysis/drift_check.py results/run_*.csv --threshold 0.2

# Compare interleaved defense-off vs defense-on rounds (from loadgen/run_comparison.sh)
python analysis/compare_on_off.py results/comparison_profile-d_20260908_140000/

# Verify the CI math itself is correct (known-example + synthetic + fake-CSV
# end-to-end checks) — run this if you ever touch wilson_ci or bootstrap_ci
python analysis/verify_ci_functions.py
```

## CI Function Signatures

- `proportions.wilson_ci(successes: int, n: int, confidence: float = 0.90) -> tuple[float, float]`
  — Wilson score interval, returned as a (lower, upper) **proportion** in [0, 1]
  (multiply by 100 for display). Not the same as a Clopper-Pearson exact interval —
  the two methods give different answers for the same input by construction.
- `analyze.bootstrap_ci(samples: list[float], percentile: float, n_resamples: int = 2000, confidence: float = 0.90) -> tuple[float, float]`
  — nonparametric bootstrap percentile CI for a given percentile (0-100 scale,
  matching `np.percentile`) of latency (or any numeric) data.

Both are verified in `analysis/verify_ci_functions.py` against a known Wilson
example, synthetic latency data, and `analysis/fixtures/sample_run.csv` — a fake
CSV shaped like real loadgen/shield output (including a `run_order` column for
future thermal-drift/cross-session work, which is NOT implemented yet — see
`drift_check.py` for that separate, later task).

## Reporting Rules (non-negotiable, see CLAUDE.md)

- Always report `dropped_iterations` next to every latency number.
- Report p50/p95/p99 and Max. **Never report standard deviation** of latency — it's
  statistically misleading for this queue-driven, skewed kind of data.
- Defense-off vs defense-on comparisons must come from interleaved rounds
  (`loadgen/run_comparison.sh`), not two separate blocks — see `compare_on_off.py`.

## Input Format: Per-Request CSV

Load test scripts write CSVs with columns:

```
timestamp,request_type,response_code,latency_ms,error_message,priority,server_url
2026-09-08T12:00:01.234Z,completion,200,542,,,legitimate,http://192.168.1.100:8080
2026-09-08T12:00:02.100Z,completion,429,50,Rate limit exceeded,,attack,http://192.168.1.100:8080
...
```

- `timestamp`: ISO 8601 (for temporal analysis)
- `request_type`: completion, chat, etc.
- `response_code`: HTTP status (200, 429, 503, etc.)
- `latency_ms`: Response time in milliseconds (0 for rejected requests)
- `error_message`: Error text if any
- `priority`: "legitimate" or "attack" (from X-Priority header)
- `server_url`: Target (llama-server or shield proxy)

## Output Formats

### Latency Analysis
```
Latency Analysis: results/run_20260908_baseline.csv
Total requests: 1234
Success rate: 98.5%

Percentile Analysis (successful requests only):
  p50:  342 ms [95% CI: 320-365 ms]
  p95:  856 ms [95% CI: 821-912 ms]
  p99: 1205 ms [95% CI: 1100-1350 ms]
  max:  2430 ms
```

### Proportions Analysis
```
Response Code Distribution:
  200 (Success): 1215/1234 (98.5%) [95% CI: 97.2-99.3%]
  429 (Rate Limited): 15/1234 (1.2%) [95% CI: 0.6-2.1%]
  503 (Overloaded): 4/1234 (0.3%) [95% CI: 0.1-0.8%]

Priority Breakdown (success rate):
  Legitimate: 1200/1210 (99.2%) [95% CI: 98.1-99.8%]
  Attack: 15/24 (62.5%) [95% CI: 40.6-81.4%]
```

### Charts
- Latency over time (timeseries)
- Success rate vs. load (line chart)
- Error rate by cohort (bar chart)
- Response code distribution (pie chart)

### Drift Detection
```
Drift Analysis: runs across 2026-09-08 sessions
Session 1 (baseline): p95 latency = 856 ms
Session 2 (same config): p95 latency = 923 ms
Deviation: +7.8% (within 20% threshold, OK)

Thermal drift detected in Session 1:
  First 30s avg latency: 420 ms
  Last 30s avg latency: 680 ms (+61.9%)
  -> Recommend rerun with longer cooldown
```

## Implementation Hints

### Bootstrap CI (latency percentiles)
1. Load CSV, filter to `response_code == 200`
2. Extract `latency_ms` values
3. For each percentile (p50, p95, p99):
   - Resample with replacement 1000 times
   - Compute percentile for each sample
   - Extract 2.5th and 97.5th percentile of bootstrap distribution

### Wilson CI (proportions)
```python
# Success rate CI
p = successes / total
z = 1.96  # 95% CI
denominator = 1 + z**2 / total
center = (p + z**2 / (2*total)) / denominator
margin = z * sqrt(p*(1-p)/total + z**2/(4*total**2)) / denominator
ci_lower = max(0, center - margin)
ci_upper = min(1, center + margin)
```

### Drift Detection
1. Group rows by session (extract date from timestamp)
2. Compute p95 latency for each session
3. Flag if deviation from first session > threshold (e.g., 20%)
4. Within each session, split into time windows; flag if latency increases > 50% (thermal drift)

## Dependencies

Pinned in `requirements.txt`:
```bash
pip install -r analysis/requirements.txt
```

Includes: pandas, numpy, matplotlib, scipy (for statistical tests).

