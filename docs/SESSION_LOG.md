# Session Log

Record each test run here with metadata, results, and observations. Use this to track progress across the 4-day hackathon and detect cross-session drift.

## Status as of 2026-09-10 (read this before starting a new session)

- **Team status:** Server (Syeda), Shield (Umar), Loadgen+Analysis (Negar) are all
  implemented and were live-tested together on 2026-09-09 over a phone hotspot
  (10.185.191.x). Deadline: 11 Sept 23:59 GST.
- **Branches/PRs:** `feature/loadgen` and `feature/analysis` are MERGED into `main`.
  `feature/shield` has an OPEN, unmerged PR (#3) — **`main` does NOT yet have**
  the `slot_available()` perf fix or two startup bugfixes (`extra="ignore"`,
  `model_fields_set` check) from that PR. `feature/service` still has zero pushed
  commits — Syeda's server config was never committed to git (only run locally).
- **What was actually run on 2026-09-09** (see Run Table below): Phase 1 (baseline,
  no attack) — 100% survival. Phase 2 (sustained attack, no Shield) — 2.2% legitimate
  survival, service effectively down. Phase 3 (same attack, through the Shield) —
  17.3% legitimate survival (~8x better than no defense, but far from complete).
- **Open investigation, NOT resolved:** Phase 3's failures don't cleanly break down.
  Of 32 `response_code=0` ("no response at all") entries, only 10 are explained by
  a specific, plausible-but-UNVERIFIED theory (uncached `/slots` checks queuing up
  on the Shield's single-event-loop, delaying already-successful responses past the
  client's timeout) — see PR #3. The other 22 are completely unaccounted for; the
  k6 raw error-string data needed to investigate them was never obtained (lives on
  Negar's machine, never copied over). Also unresolved: the Shield's results folder
  sits inside a OneDrive-synced directory, a live confirmed variable that was never
  ruled in or out as a contributing cause.
- **Next actions, in priority order:** (1) merge PR #3 or decide against it, (2)
  get k6's raw `--out csv` output from Phase 3 to break down the other 22 failures
  by actual error type, (3) rerun the identical Phase 3 profile and compare the
  `response_code=0` count before/after PR #3 — this is the only thing that can
  confirm or refute that fix, (4) test `profile-d.js` (slow/high-cost), never run
  yet, (5) get Syeda to push her real `service/start.sh` config for the record.
- **Full detail:** `docs/MANUAL_CONFIG.md` has the dated, itemized history of every
  config value that had to be fixed this way (context size, Shield timeout, `-np`
  sync) — read it before touching any threshold or flag.

## 2026-09-10 update — found and fixed a second timeout-mismatch bug (probe.js)

- Investigated why Phase 3's k6 timeouts were seen at 30s when the Shield/loadgen
  timeout pairing was supposedly fixed to 130s/120s on 2026-09-09.
- **Root cause: `loadgen/profiles/probe.js` (the legitimate-cohort script Phase 3
  actually measured) was never updated** — only `profile-d.js` got the 2026-09-09
  fix. `probe.js` was still at its original `timeout: '30s'`, well under the
  Shield's 130.0s forward-timeout ceiling. Any probe request the Shield legitimately
  took >30s to service under Phase 3's flood load would read to k6 as
  `response_code=0` even if the Shield/server would have answered correctly —
  likely a real contributor to the 22 previously-unexplained failures, separate
  from and in addition to the PR #3 `slot_available()` theory.
- **Fixed:** `probe.js`'s timeout raised `30s` → `130s`, same "comfortably above
  the Shield's ceiling" pairing as `profile-d.js`. See `docs/MANUAL_CONFIG.md`
  for the full writeup and a note flagging `baseline.js`/`spike.js`/`sustained.js`
  (still at `60s`) for the same check if they're ever used to measure
  legitimate-cohort survival under heavy load.
- **This is UNVERIFIED like PR #3** — same situation: no live server this session
  to confirm it actually reduces the `response_code=0` count. Should be tested in
  the same live Phase 3 rerun as PR #3, not treated as resolved yet.

## 2026-09-10 update — PR #3 code review (no live server available this session)

- Reviewed PR #3's full diff (`shield/main.py`, docs) statically — no `llama-server`
  or team members reachable this session to run the confirming rerun.
- **Finding: code is correct and low-risk.** `slot_available()`'s caching + pooled
  client changes leave admission/shedding logic untouched (same `200 == available`
  check, same fail-open-on-exception behavior); the two startup bugfixes
  (`extra="ignore"`, `model_fields_set` check) match what was already verified live
  on 2026-09-09. Minor non-blocking note: concurrent cache misses within the same
  TTL window aren't de-duplicated (two requests can both miss and both fire a
  `/slots` call before either writes back) — not a regression vs. the old no-cache
  behavior, not worth fixing before a rerun.
- **Decision: hold the merge until the live Phase 3 rerun confirms the perf fix**
  (team's call, not a code-quality blocker) — per the open investigation, the only
  thing that can actually confirm or refute whether this closes the
  `response_code=0` gap is comparing that count before vs. after against a live
  server, and merging early wouldn't change what that rerun still needs to prove.
- Still blocked, same as before: Negar's raw k6 CSVs (needed for the other 22
  unexplained failures) were never copied off her machine, and no live
  `llama-server` instance is running to test PR #3 against. Both require a session
  with the team's laptops present.

## Run Table

| Date | Server Host | Load Generator Host | Scenario | Duration | Requests | Success Rate | p95 Latency | Key Findings | File |
|------|-------------|---------------------|----------|----------|----------|--------------|-------------|--------------|------|
| 2026-09-09 | Syeda's laptop (10.185.191.119, Qwen2.5-1.5B, -np 4) | Negar's laptop | Phase 1: baseline probe, no attack | 1m | 31 | 100% | ~6.8s | Clean baseline; server healthy, slow (CPU-only) but zero failures | results/run_20260909_181820_phase1_baseline.csv (Negar's machine) |
| 2026-09-09 | same | Negar's laptop | Phase 2: sustained attack (50 req/s) straight at server, no Shield | 2m | attack: 1200 sent (80% dropped by k6 itself before send); probe: 45 | probe: 2.2% (1/45) | probe p50 ~30s (timeout) | No defense = one attacker takes down the service for everyone; 99.6% attack error rate too | results/run_20260909_182017_phase2_*_noshield.csv (Negar's machine) |
| 2026-09-09 | same | Negar's laptop, through Umar's Shield (10.185.191.136:9090) | Phase 3: same attack, through Shield | 2m | attack: 4953; probe: 52 | probe: 17.3% (9/52) | n/a (bimodal — 200s fast, 503s fast, 0-code entries effectively timed out) | ~8x better than no defense, but 82.7% of legitimate traffic still failed. Breakdown: 9×200, 8×503 (Shield correctly shedding), 3×500, 32×response_code=0 (no response at all — see investigation notes above). Shield's own reconciliation log shows 19 legitimate 200s were actually forwarded successfully, but only 9 reached the client — a 10-request gap, unverified fix in PR #3. | results/run_20260909_190310_phase3_*_shield.csv (Negar's machine — not copied to this repo's /results, which only has the Shield's own results/shield_reconciliation_*.csv from this same session) |

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

