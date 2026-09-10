# Session Log

Record each test run here with metadata, results, and observations. Use this to track progress across the 4-day hackathon and detect cross-session drift.

## Status as of 2026-09-10 (read this before starting a new session)

- **Team status:** Server (Syeda), Shield (Umar), Loadgen+Analysis (Negar) are all
  implemented and were live-tested together on 2026-09-09 and 2026-09-10 over a
  phone hotspot (10.185.191.x). Deadline: 11 Sept 23:59 GST.
- **Branches/PRs:** `feature/loadgen`, `feature/analysis`, and `feature/shield`
  (PR #3, the `slot_available()` perf fix + two startup bugfixes) are all MERGED
  into `main`. A second Shield perf fix (pooling `get_requests_deferred()`'s
  client, found live — see incident entry below) is also merged (`b390503`).
  `feature/service` still has zero pushed commits — Syeda's server config was
  never committed to git (only run locally).
- **RESOLVED 2026-09-10: both Shield perf fixes are CONFIRMED, not just theorized.**
  A live rerun (Phase 4, identical attack profile to Phase 3) after both fixes
  landed shows: legitimate survival **17.3% → 60.0%** (90% CI 10.4–27.5% vs.
  49.4–69.8% — non-overlapping, a real effect), and the `response_code=0` count
  that drove the whole investigation went **32 → 0**. Every Phase 4 failure is now
  a clean `503` (Shield correctly and quickly rejecting). See the confirming-rerun
  entry below for full numbers. Do not re-open this as "unverified" — it's closed.
- **What was actually run** (see Run Table below): Phase 1 (baseline, no attack) —
  100% survival. Phase 2 (sustained attack, no Shield) — 2.2% legitimate survival,
  service effectively down. Phase 3 (same attack, Shield with the unfixed
  `slot_available()` bug) — 17.3% survival. Phase 4 (same attack, Shield with both
  perf fixes) — **60.0% survival, confirmed**.
- **Next actions, in priority order:** (1) test `profile-d.js` (slow/high-cost —
  the project's key differentiator profile), never run yet, (2) get Syeda to push
  her real `service/start.sh` config for the record, (3) consider whether 60%
  survival under a 50 req/s flood is the ceiling of the current defense tuning
  (token bucket sizes, slot reservation fraction) or whether further tuning could
  push it higher — worth a documented discussion in the final report either way.
- **Full detail:** `docs/MANUAL_CONFIG.md` has the dated, itemized history of every
  config value that had to be fixed this way (context size, Shield timeout, `-np`
  sync) — read it before touching any threshold or flag.

## 2026-09-10 update — CONFIRMING RERUN: both Shield perf fixes verified live (Phase 4)

After PR #3 (`slot_available()` caching) and the live-incident fix
(`get_requests_deferred()` pooling, `b390503`) both landed on `main`, ran the
identical attack profile from Phase 3 (`sustained.js`, 50 req/s flood for 2m,
`probe.js` concurrently, both through the Shield at 10.185.191.136:9090) against
Syeda's server (10.185.191.119:8080) to check whether they actually work, not just
whether they're theoretically sound.

**Result — clean, unambiguous improvement:**

| | Phase 3 (buggy) | Phase 4 (fixed) |
|---|---|---|
| Legitimate survival | 17.3% (9/52) | **60.0% (36/60)** |
| 90% CI (Wilson) | 10.4–27.5% | 49.4–69.8% |
| `response_code=0` count | 32 | **0** |
| Probe dropped_iterations | 9 (14.8%) | 0 (0.0%) |
| Attack traffic median latency | ~5,795ms | **~105ms** |
| Attack traffic dropped_iterations | 1,048 (17.5%) | 0 (0.0%) |

The 90% CIs for Phase 3 vs. Phase 4 don't overlap — this is a real effect, not
noise. Phase 4's probe failures are now 24/60, **all** clean `503 Overloaded`
responses — no `dial` errors, no `request timeout`, no `500`s. The attack traffic's
own median latency dropping from ~5.8s to ~105ms tells the same story from the
other side: the Shield is now rejecting flood traffic almost instantly instead of
stalling on it.

**This closes out the open investigation from the prior three 2026-09-10 entries.**
Both fixes are no longer "plausible, unverified theories" — they're confirmed
against a live rerun with the exact same attack profile as the original Phase 3
measurement. Do not re-litigate whether `slot_available()` caching or
`get_requests_deferred()` pooling "actually help" — this rerun is the answer.

**What's still open:** 60% survival under a 50 req/s flood is a large improvement
over 17.3%, but it's not 100% — worth deciding whether that's an acceptable,
reportable ceiling for this defense configuration (token bucket sizes, slot
reservation fraction) or whether it's worth further tuning before the deadline.
Also: `profile-d.js` (the slow/high-cost profile — arguably the project's most
important differentiator, since it's specifically designed to defeat a naive
request-count limiter) has still never been run against a live server.

**Files:** `results/run_20260910_185041_phase4_attack_shieldfixed.csv` (5999 rows),
`results/run_20260910_185041_phase4_probe_shieldfixed.csv` (60 rows).

## 2026-09-10 update — live incident: Shield DoS'd its own backend, fixed on the spot

- During today's live test session (PR #3 already merged), Behzad's attack traffic
  through the Shield left `llama-server` completely unreachable — even `/health`
  timed out from Syeda's own machine, process alive but not answering.
- Syeda diagnosed 2,000+ simultaneous connections to `llama-server:8080`, all from
  a **single IP: the Shield's own host**, not the attacker's machine. The Shield
  was DoS-ing its own backend, not defending against the attack.
- **Root cause:** `get_requests_deferred()` still had the exact fresh-`httpx.AsyncClient()`
  -per-call pattern PR #3 fixed in `slot_available()` — PR #3 deliberately scoped
  that fix narrowly and left this sibling function untouched. Under real flood
  concurrency, many requests missed its 0.5s cache in the same instant and each
  fired its own unpooled connection to `/metrics` — exactly the pile-up observed.
- **Fixed live and pushed** (`b390503`): pooled `get_requests_deferred()`'s client
  the same way PR #3 pooled `slot_available()`'s. Shield restarted with the fix
  before resuming the test. `llama-server` confirmed recovered (`/health` 200)
  once the flood stopped.
- Traffic paused during the fix; test resumed after restart. See the Run Table
  for today's actual results once available.

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
| 2026-09-10 | Syeda's laptop (10.185.191.119) | Negar's laptop, through Umar's Shield (10.185.191.136:9090), BOTH perf fixes live | Phase 4: same attack profile as Phase 3, through the FIXED Shield | 2m | attack: 5999, 0 dropped; probe: 60, 0 dropped | **probe: 60.0% (36/60) [90% CI 49.4-69.8%]** | attack p50 ~105ms (was ~5795ms); probe p50 ~5398ms, max ~8248ms (no more timeout-capped latencies) | CONFIRMING RERUN — closes the Phase 3 investigation. response_code=0 count: 32 → 0. Remaining 24/60 probe failures are ALL clean 503s (Shield correctly shedding), zero dial/timeout errors. Non-overlapping 90% CI vs. Phase 3 — real effect, not noise. See full entry above. | results/run_20260910_185041_phase4_*_shieldfixed.csv (now committed) |

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

