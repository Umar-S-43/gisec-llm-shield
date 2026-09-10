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
- **Open investigation, partially resolved 2026-09-10:** the raw k6 error-string
  data for Phase 3's 32 `response_code=0` entries has now been recovered and
  committed (see the 2026-09-10 entry below "Negar's raw k6 CSVs recovered") — it
  splits cleanly 16/16 into `dial: errno 10060` (TCP handshake never acknowledged;
  points at Shield-side saturation, targeted by PR #3) vs `request timeout`
  (connection succeeded, no response in time; targeted by the `probe.js` timeout
  fix). Both existing fixes now have a specific, distinct sub-count to check against
  in a rerun, instead of one explaining 10 and 22 being a total mystery. Still
  UNVERIFIED without that rerun. Also still unresolved: the Shield's results folder
  sits inside a OneDrive-synced directory, a live confirmed variable that was never
  ruled in or out as a contributing cause.
- **Next actions, in priority order:** (1) merge PR #3 (and the `probe.js` timeout
  fix) or decide against them, (2) ~~get k6's raw output~~ DONE 2026-09-10 — see
  entry below, (3) rerun the identical Phase 3 profile and check the `dial`-error
  and `request timeout` counts SEPARATELY, not just the total `response_code=0`
  count — that's what actually confirms or refutes each fix individually, (4) test
  `profile-d.js` (slow/high-cost), never run yet, (5) get Syeda to push her real
  `service/start.sh` config for the record.
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

## 2026-09-10 update — Negar's raw k6 CSVs recovered; response_code=0 breakdown by actual error string

This resolves the "k6 raw error-string data ... never obtained" blocker noted above and in the PR #3
review — the data was sitting on my machine from the original 2026-09-09 run; committing it now
(see file list at the end of this entry) so it doesn't have to be re-requested or re-run to get.

**Exact breakdown of all 32 `response_code=0` entries from Phase 3's probe run**, pulled from the
`error_message` column `loadgen/normalize_csv.py` already preserves from k6's raw output (no rerun
needed — this was extractable from data already on hand):

```
error_message                                                                    count
request timeout                                                                     16
dial: unknown errno 10060 (connected party did not properly respond in time)        16
```

**What this changes about the "10 explained / 22 unexplained" framing above:** the two error types are
mechanically different and point at different layers, which the status/count alone couldn't distinguish:

- **`dial: errno 10060` (16 of 32):** the TCP handshake itself was never acknowledged — no connection
  was ever established. This can ONLY be a server/Shield-side saturation symptom (the listening
  socket's accept queue), never a client-timeout-value problem. These 16 are consistent with — and
  don't need any explanation beyond — PR #3's `slot_available()` single-event-loop theory. Raising
  `probe.js`'s client timeout (the 2026-09-10 fix above) cannot fix these; only PR #3's fix (or
  something else that reduces Shield-side saturation) can.
- **`request timeout` (16 of 32):** the connection DID succeed; k6 waited out its full client-side
  timeout with no response body. At the time of this run, that timeout was still `probe.js`'s
  unfixed `30s` — meaning these 16 are exactly the failure mode the 2026-09-10 `probe.js` fix
  (30s → 130s) targets. Whether they'd have succeeded under a 130s timeout is unverified without a
  rerun, but they are no longer a mystery category — they're the expected signature of a client
  timeout shorter than the Shield's own 130.0s forward-timeout ceiling.

So the honest updated picture: 16 of the 32 (`dial` errors) need PR #3 (or an equivalent Shield-side
fix) to improve; the other 16 (`request timeout`) need the `probe.js` timeout fix already made; **both
independently discovered fixes target real, distinct, now-identified parts of the same 32-count gap**,
rather than one fix explaining 10 and 22 remaining a mystery. This is still not proof either fix works
— that still requires the live rerun both prior entries already call for — but it substantially narrows
what that rerun needs to check: does the `dial`-error count drop after PR #3, and does the
`request timeout` count drop after the `probe.js` fix, independently of each other.

**Files committed** (the normalized per-request CSVs only — see each file's `error_message` column for
the raw k6 strings above; the much larger raw `--out csv` k6 dumps and `.log`/`.json` files were left
out, consistent with this repo's own `.gitignore` reasoning that `/results` should stay
small/regenerable, and nothing in them isn't already captured in these normalized files):
- `results/run_20260909_181820_phase1_baseline.csv` (Phase 1, 31 rows)
- `results/run_20260909_182017_phase2_attack_noshield.csv` (Phase 2 attack, 1200 rows)
- `results/run_20260909_182017_phase2_probe_noshield.csv` (Phase 2 probe, 45 rows)
- `results/run_20260909_190310_phase3_attack_shield.csv` (Phase 3 attack, 4953 rows)
- `results/run_20260909_190310_phase3_probe_shield.csv` (Phase 3 probe, 52 rows — the one referenced
  above)

**Updated next actions:** item (2) from the status block above ("get k6's raw output to break down the
22 failures") is done as of this entry. (1) and (3) — decide on PR #3 and rerun Phase 3 to confirm both
fixes — still stand, and should now check both the `dial`-error and `request timeout` counts
separately, not just the total `response_code=0` count.

## Run Table

| Date | Server Host | Load Generator Host | Scenario | Duration | Requests | Success Rate | p95 Latency | Key Findings | File |
|------|-------------|---------------------|----------|----------|----------|--------------|-------------|--------------|------|
| 2026-09-09 | Syeda's laptop (10.185.191.119, Qwen2.5-1.5B, -np 4) | Negar's laptop | Phase 1: baseline probe, no attack | 1m | 31 | 100% | ~6.8s | Clean baseline; server healthy, slow (CPU-only) but zero failures | results/run_20260909_181820_phase1_baseline.csv (now committed) |
| 2026-09-09 | same | Negar's laptop | Phase 2: sustained attack (50 req/s) straight at server, no Shield | 2m | attack: 1200 sent (80% dropped by k6 itself before send); probe: 45 | probe: 2.2% (1/45) | probe p50 ~30s (timeout) | No defense = one attacker takes down the service for everyone; 99.6% attack error rate too | results/run_20260909_182017_phase2_*_noshield.csv (now committed) |
| 2026-09-09 | same | Negar's laptop, through Umar's Shield (10.185.191.136:9090) | Phase 3: same attack, through Shield | 2m | attack: 4953; probe: 52 | probe: 17.3% (9/52) | n/a (bimodal — 200s fast, 503s fast, 0-code entries effectively timed out) | ~8x better than no defense, but 82.7% of legitimate traffic still failed. Breakdown: 9×200, 8×503 (Shield correctly shedding), 3×500, 32×response_code=0 (no response at all — now broken down further, 16 `dial` errors + 16 `request timeout`, see 2026-09-10 entry above). Shield's own reconciliation log shows 19 legitimate 200s were actually forwarded successfully, but only 9 reached the client — a 10-request gap, unverified fix in PR #3. | results/run_20260909_190310_phase3_*_shield.csv (now committed) |

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

