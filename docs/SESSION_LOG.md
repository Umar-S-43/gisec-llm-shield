# Session Log

Record each test run here with metadata, results, and observations. Use this to track progress across the 4-day hackathon and detect cross-session drift.

## Status as of 2026-09-11 (read this before starting a new session — DEADLINE TODAY 23:59 GST)

- **Team status:** Server (Syeda), Shield (Umar), Loadgen+Analysis (Negar) are all
  implemented and were live-tested together on 2026-09-09, 2026-09-10, and
  2026-09-11 over a phone hotspot (10.185.191.x).
- **Branches/PRs:** `feature/loadgen`, `feature/analysis`, and `feature/shield`
  (PR #3, the `slot_available()` perf fix + two startup bugfixes) are all MERGED
  into `main`. A second Shield perf fix (pooling `get_requests_deferred()`'s
  client) is also merged (`b390503`). `feature/service` still has zero pushed
  commits — Syeda's server config was never committed to git (only run locally).
- **RESOLVED 2026-09-10: both Shield perf fixes CONFIRMED live.** Phase 4 (50
  req/s flood, identical to Phase 3) after both fixes: legitimate survival
  **17.3% → 60.0%**, `response_code=0` count **32 → 0**. Closed, not re-opened.
- **RESOLVED 2026-09-11: `LEGITIMATE_SLOT_FRACTION` was undersized — this IS the
  dominant fix, confirmed after catching and correcting a confound.** Initial
  test found survival at only 50.8% (3 req/s, fraction=0.5, the default) —
  diagnosed as undersized slot reservation (Little's Law: the probe alone needs
  ~3 concurrent slots, only 2 were reserved), NOT a differentiation failure
  (attack was still ~98% rejected throughout). An UNRELATED architecture change
  landed on `main` mid-investigation (pipeline reordered A→C→B + a token-refund
  fix, `78d67ee`/`5bf923f`), which briefly looked like it might be the bigger
  driver — re-testing the SAME fraction (0.75) on both the old and new pipeline
  isolated its real effect at only **+2.0 points (75.0% → 77.0%), likely within
  noise, NOT dominant.** The fraction itself remains the clearly dominant driver:
  **50.8% (0.5) → 75-77% (0.75) → 93.4% (1.0)**. Config decision:
  **`LEGITIMATE_SLOT_FRACTION=1.0` is the recommended final value** — see the
  dated entry below for full
  reasoning and the intermediate (confounded) numbers, kept for transparency
  rather than deleted.
- **What was actually run** (see Run Table below): Phase 1 (baseline) — 100%.
  Phase 2 (attack, no Shield) — 2.2%. Phase 3 (attack, Shield with the unfixed
  perf bug) — 17.3%. Phase 4 (attack, Shield with both perf fixes) — 60.0%.
  2026-09-11 (all at 3 req/s): fraction=0.5/old pipeline — 50.8%;
  fraction=0.75/old pipeline — 75.0%; fraction=0.75/NEW pipeline — **77.0%
  (isolates the architecture fix at +2.0 pts, not dominant)**; fraction=1.0/NEW
  pipeline — **93.4% (recommended final config)**.
- **Next actions, in priority order:** (1) test `profile-d.js` (slow/high-cost —
  the project's key differentiator profile, tests token-cost admission control
  specifically), STILL never run live as of this entry, (2) get Syeda to push
  her real `service/start.sh` config for the record, (3) write the final report
  incorporating the perf-fix story, the pipeline-reorder story, AND the
  decomposed slot-fraction finding — three distinct, real findings, not one.
- **Operational note:** during today's session, the load-generator laptop
  silently fell off the hotspot and onto campus WiFi mid-session, producing a
  test result where 100% of ALL traffic (attack AND probe) showed
  `response_code=0` — this looked like a total Shield failure but was actually
  a network-layer disconnect (confirmed via `ipconfig` showing a `10.2.x.x`
  campus-WiFi address instead of the hotspot's `10.185.191.x`). That specific
  run was discarded, not recorded in the Run Table below. Always sanity-check
  your own IP before treating a 100%-failure result as a defense finding.
- **Full detail:** `docs/MANUAL_CONFIG.md` has the dated, itemized history of every
  config value that had to be fixed this way (context size, Shield timeout, `-np`
  sync) — read it before touching any threshold or flag.

## 2026-09-11 update — LEGITIMATE_SLOT_FRACTION was undersized: diagnosis, sweep, fix

Using the new demo control panel (`demo/`, a local button-driven attack UI built this
session for live demos — see `demo/README.md`), ran `sustained.js` at a LOW rate
(3 req/s, well below the 50 req/s used in Phases 1-4) through the perf-fixed Shield,
expecting a near-100% legitimate survival "sanity check" floor. Got only **50.8%**
(31/61) instead — surprising, and worth investigating rather than assuming it was
just noise.

**Diagnosis — this is a capacity-sizing issue, not a differentiation failure.**
Attack traffic was still being rejected ~98% of the time throughout — the Shield
was correctly telling attack and legitimate traffic apart. The problem is
`LEGITIMATE_SLOT_FRACTION`'s default (0.5) reserves only `ceil(4 × 0.5) = 2` of
`llama-server`'s 4 real slots for legitimate traffic. By Little's Law
(`concurrent requests ≈ arrival rate × service time`), the probe's own traffic
alone — 0.5 req/s at a measured ~6s median response time — needs **~3 concurrent
slots on average**, not 2. So even with zero attack traffic, a meaningful fraction
of the probe's own requests would arrive while its own prior requests were still
in flight and find `slot_available()` (a real-time, tier-blind check against
`llama-server` itself, not just the Shield's own bookkeeping) reporting "no slot" —
because the 2-slot reservation was undersized for the workload's own natural
concurrency, given how slow the model is.

**Important constraint found while tuning:** with only 4 total slots,
`_reserved_for_legitimate = ceil(4 × fraction)` does NOT tune smoothly. The only
reachable values are 2 (fraction ≤ 0.5), 3 (0.5 < fraction ≤ 0.75), or 4 (fraction >
0.75, which also means `_default_slot_capacity` becomes 0 — attack/default traffic
can never be admitted again, not just rarely). There is no "just above 0.75" middle
ground at this slot count.

**First sweep result** (all at 3 req/s, `sustained.js`, through the Shield):

| `LEGITIMATE_SLOT_FRACTION` | Reserved slots | Legitimate survival |
|---|---|---|
| 0.5 (old default) | 2 | 50.8% (31/61) |
| 0.75 | 3 | 75.0% (45/60) |
| 1.0 | 4 (all) | 93.4% (57/61) |

**This sweep turned out to be CONFOUNDED — caught before it was reported as final.**
While these three tests ran, an unrelated architecture change landed on `main`
mid-investigation: the Shield's defense pipeline was reordered from B→C→A to
A→C→B, with a new `TokenBucket.refund()` to stop the new order from wasting
budget on doomed requests (`78d67ee`, `5bf923f` — see `docs/MANUAL_CONFIG.md` for
the full diff). Checking commit timestamps against test timestamps: the 0.5 test
(11:54) ran on the OLD pipeline; the 0.75 test (13:11) ran after an unrelated
`.env`-restart bugfix but STILL the old pipeline; the 1.0 test (13:36) ran AFTER
the pipeline reorder. So the 75.0% → 93.4% jump was not "fraction alone" — the
Shield's own code changed between those two tests, not just the config.

**Resolved by re-testing at fraction=0.75 again on the NEW (post-reorder) code**
(NOTE: an earlier draft of this entry mistakenly recorded this re-test as
fraction=0.5 — corrected after the team caught the error; the re-test was
actually at 0.75, which is the fraction that isolates the architecture change
correctly since it's the value tested on BOTH pipeline versions):

| Test | Code | Fraction | Survival |
|---|---|---|---|
| 1 | Old pipeline (B→C→A) | 0.5 | 50.8% |
| 2 | Old pipeline | 0.75 | 75.0% |
| 3 (re-test) | **New pipeline (A→C→B) + refund** | **0.75 (same as test 2)** | **77.0%** |
| 4 | New pipeline + refund | 1.0 | 93.4% |

Tests 2→3 isolate the architecture fix (fraction held constant at 0.75):
**+2.0 points — small, plausibly within sampling noise for a ~60-request test,
not a dominant effect.** The fraction itself remains the clearly dominant driver:
1→2 (+24.2 points, fraction 0.5→0.75, old code) and 3→4 (+16.4 points, fraction
0.75→1.0, new code) are both large, and both isolate the fraction change with
the pipeline version held constant on at least one side. The pipeline
reorder/refund fix is a real, separate, and independently-justified change (see
its own commit messages), but it should NOT be reported as a major contributor
to today's survival improvement — that credit belongs to the fraction increase.

**Decision: `LEGITIMATE_SLOT_FRACTION=1.0` is the recommended final value.**
Reasoning: with only 4 total slots, `ceil(4 × fraction)` has no smooth middle
ground between 3 and 4 reserved slots, so 1.0 isn't a more extreme choice than
0.75 so much as the only other option that exists; and this project's central
scientific claim is about COST-AWARE admission control (Defense A, token budgets)
beating naive request-counting — `profile-d.js` tests that directly, not this
slot-fraction knob, so tuning Defense C's fraction all the way doesn't undermine
the more central A/B story. A compromise value (0.75) remains defensible if the
team prefers a "shared" fairness narrative over the cleanest number.

**Lesson for the rest of this report:** when a config sweep spans more than a
couple of minutes on a shared, actively-developed repo, check `git log` for
unrelated commits landing mid-sweep before attributing the full delta to the one
variable being changed on purpose. This is the second time this project has found
a confound this way (see the `probe.js` timeout / PR #3 double-fix on 2026-09-10)
— worth stating as a general methodology note in the final report, not just fixing
quietly each time it happens.

**Not yet done:** re-verifying any of this at the ORIGINAL 50 req/s rate (Phase
1-4's rate) rather than only at 3 req/s — every number above is from the LOW-rate
scenario. If time allows, confirm `fraction=1.0` + the new pipeline also holds up
under the heavier 50 req/s flood before treating it as fully final for the report.

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
| 2026-09-11 | Syeda's laptop (10.185.191.119) | Negar's laptop, via demo control panel, through Shield (10.185.191.136:9090) | Fraction sweep #1: LEGITIMATE_SLOT_FRACTION=0.5 (default), OLD pipeline (B→C→A), 3 req/s sustained | 2m | attack: 361; probe: 61 | probe: 50.8% (31/61) | probe median ~n/a (see CSV) | Surprisingly low for such a low attack rate — diagnosed as undersized slot reservation (Little's Law: probe alone needs ~3 concurrent slots, only 2 reserved), NOT a differentiation failure (attack still ~98% rejected). See full entry above. | results/run_demo_sustained_*_20260911_115408.csv (now committed) |
| 2026-09-11 | same | same | Fraction sweep #2: LEGITIMATE_SLOT_FRACTION=0.75, OLD pipeline, 3 req/s sustained | 2m | attack: ~360; probe: 60 | probe: 75.0% (45/60) | — | 3 reserved slots — closer to the ~3 concurrency Little's Law predicts the probe needs on its own | results/run_demo_sustained_*_20260911_131133.csv (now committed) |
| 2026-09-11 | same | same | Confound check: LEGITIMATE_SLOT_FRACTION=0.75 (SAME as row above), but on the NEW pipeline (A→C→B + refund), 3 req/s sustained | 2m | attack: ~360; probe: 61 | probe: 77.0% (47/61) | probe median 6599ms | Re-test at the SAME fraction as the row above, after the pipeline reorder landed — isolates the architecture change's own effect at only +2.0 points vs. the row above (75.0%→77.0%), confirming it is NOT the dominant driver. See full entry above. | results/run_demo_sustained_*_20260911_135848.csv (now committed) |
| 2026-09-11 | same | same | Fraction sweep #3: LEGITIMATE_SLOT_FRACTION=1.0, NEW pipeline, 3 req/s sustained | 2m | attack: 361; probe: 61 | **probe: 93.4% (57/61)** | probe median 5740ms | All 4 slots reserved for legitimate (default capacity → 0). RECOMMENDED FINAL VALUE — see full entry above for reasoning and the caveat that this was only tested at 3 req/s, not yet re-confirmed at 50 req/s. | results/run_demo_sustained_*_20260911_133653.csv (now committed) |

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

