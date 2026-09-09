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

# Try drift_check.py against synthetic fixtures (one session with real thermal
# drift injected, one stable session) before you have real data:
python analysis/drift_check.py "analysis/fixtures/drift_demo/session1/*.csv" "analysis/fixtures/drift_demo/session2/*.csv" --threshold 0.2

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
CSV shaped like real loadgen/shield output.

Bootstrap resamples raw per-request latency samples WITHIN one run, not the set
of run-level percentile point-estimates across runs — see the docstring at the
top of `analyze.py` for why (short version: CLAUDE.md's cut list allows as few
as 3 runs per arm, far too few points to bootstrap meaningfully; a single run
has hundreds of raw samples instead). Cross-run/cross-session variability is a
separate question, handled by `drift_check.py`.

## Reporting Rules (non-negotiable, see CLAUDE.md)

- Always report `dropped_iterations` next to every latency number.
- Report p50/p95/p99 and Max. **Never report standard deviation** of latency — it's
  statistically misleading for this queue-driven, skewed kind of data.
- Defense-off vs defense-on comparisons must come from interleaved rounds
  (`loadgen/run_comparison.sh`), not two separate blocks — see `compare_on_off.py`.

## Input Format: Per-Request CSV

Load test scripts write CSVs with columns:

```
timestamp,request_type,response_code,latency_ms,error_message,priority,server_url,run_order
2026-09-08T12:00:01.234Z,completion,200,542,,legitimate,http://192.168.1.100:8080,1
2026-09-08T12:00:02.100Z,completion,429,50,Rate limit exceeded,attack,http://192.168.1.100:8080,1
...
```

- `timestamp`: ISO 8601 (for temporal analysis)
- `request_type`: completion, chat, etc.
- `response_code`: HTTP status (200, 429, 503, etc.)
- `latency_ms`: Response time in milliseconds (0 for rejected requests)
- `error_message`: Error text if any
- `priority`: "legitimate" or "attack" (from X-Priority header)
- `server_url`: Target (llama-server or shield proxy)
- `run_order` (optional): position of this WHOLE RUN in its session's chronological
  sequence (1, 2, 3, ...) — constant for every row in one CSV, not per-request.
  Produced by `loadgen/normalize_csv.py` / `loadgen/run_comparison.sh`. Used by
  `drift_check.py` to order interleaved rounds correctly; scripts fall back to
  filename order (with a warning) when it's absent, for older CSVs.

## Output Formats

### Latency Analysis
```
Latency Analysis: results/run_20260908_baseline.csv
Total requests: 1234
Success rate: 98.5%

Percentile Analysis (successful requests only):
  p50:  342 ms [90% CI: 320-365 ms]
  p95:  856 ms [90% CI: 821-912 ms]
  p99: 1205 ms [90% CI: 1100-1350 ms]
  max:  2430 ms
```

### Proportions Analysis
```
Response Code Distribution:
  200 (Success): 1215/1234 (98.5%) [90% CI: 97.2-99.3%]
  429 (Rate Limited): 15/1234 (1.2%) [90% CI: 0.6-2.1%]
  503 (Overloaded): 4/1234 (0.3%) [90% CI: 0.1-0.8%]

Priority Breakdown (success rate):
  Legitimate: 1200/1210 (99.2%) [90% CI: 98.1-99.8%]
  Attack: 15/24 (62.5%) [90% CI: 40.6-81.4%]
```

### Charts
- Latency over time (timeseries)
- Success rate vs. load (line chart)
- Error rate by cohort (bar chart)
- Response code distribution (pie chart)

### Drift Detection
```
Drift Analysis: 8 runs
Threshold: 20%

round1_off_attack
  p95 latency: 235 ms
  thermal drift (within run): +3.1% OK

Drift Across Run Order (within each session):
  [session1] sequence (run_order, p95): [(1, '235ms'), (2, '269ms'), (3, '344ms'), (4, '398ms')]
  [session1] first-half vs second-half p95: +47.2% DRIFT DETECTED
  [session2] sequence (run_order, p95): [(1, '261ms'), (2, '248ms'), (3, '223ms'), (4, '239ms')]
  [session2] first-half vs second-half p95: -9.2% OK

Cross-Session Consistency:
  Reference session: session1 (mean p95=311ms)
  session2: mean p95=243ms, +22.0% vs reference ANOMALY
```

Three distinct checks, each answering a different question:
- **Thermal drift (within one run):** first N vs last N successful requests' mean
  latency, inside a single CSV. Detects the laptop heating up mid-run.
- **Drift across run order (within one session):** compares the first half vs
  second half of a session's `run_order`-sorted runs (e.g. interleaved
  off/on/off/on rounds). This is what actually catches "the laptop got hotter as
  the interleaved rounds went on" — the reason CLAUDE.md requires interleaving
  instead of running all off-rounds then all on-rounds.
- **Cross-session:** compares each session's mean p95 against a reference
  session. Sessions are identified by the CSV's parent directory name (e.g.
  `comparison_profile-d_20260908_140000/`, as produced by
  `loadgen/run_comparison.sh`), falling back to filename parsing for standalone
  CSVs. A session with internal thermal drift can itself look anomalous here —
  that's a real finding, not a bug, and worth noting in the report.

## Implementation Notes (matches the actual code — see docstrings for details)

### Bootstrap CI (latency percentiles) — `analyze.bootstrap_ci`
Resamples raw per-request latency samples (not run-level point estimates) with
replacement `n_resamples` times (default 2000), computes the target percentile
on each resample, and takes the resulting distribution's tail cutoffs at the
requested confidence level. See the rationale docstring at the top of
`analyze.py` for why raw-sample resampling was chosen over resampling run-level
percentile estimates.

### Wilson CI (proportions) — `proportions.wilson_ci`
True Wilson score interval (via `scipy.stats.norm.ppf` for a general z-value,
not a hardcoded 95%/99% lookup). Note: the research brief's own worked example
(4 defects / 20 samples → 90% CI ≈ (0.071, 0.400)) is actually a
Clopper-Pearson EXACT interval, not Wilson — the two methods disagree by
construction on the same input. `wilson_ci(4, 20, confidence=0.90)` correctly
returns ≈ (0.093, 0.378); see `verify_ci_functions.py`.

### Drift Detection — `drift_check.py`
1. **Within-run thermal drift:** first N vs last N successful requests' mean
   latency in one CSV (`detect_thermal_drift`).
2. **Across-run-order drift, within one session:** group runs by session
   (parent directory name), sort by the `run_order` column, compare first-half
   vs second-half mean p95 (`detect_run_order_drift`). Falls back to a warning
   and skips this check for CSVs missing `run_order`.
3. **Cross-session:** compare each session's mean p95 against a reference
   session (`compare_sessions`).

## Dependencies

Pinned in `requirements.txt`:
```bash
pip install -r analysis/requirements.txt
```

Includes: pandas, numpy, matplotlib, scipy (for statistical tests).

