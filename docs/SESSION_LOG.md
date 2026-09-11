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
- **SUPERSEDED, then RE-RESOLVED 2026-09-11: a THIRD caching bug invalidated the
  first fraction sweep below; clean data exists only after it was fixed.**
  Sequence: (1) diagnosed `LEGITIMATE_SLOT_FRACTION=0.5` as undersized via
  Little's Law (probe needs ~3 concurrent slots, only 2 reserved) — a capacity
  issue, NOT a differentiation failure, since attack was still ~98% rejected
  throughout; (2) swept 0.5→0.75→1.0 (50.8%→75.0%→93.4%), then caught an
  architecture-reorder confound (`78d67ee`/`5bf923f` landing mid-sweep) and
  "corrected" for it, concluding the reorder contributed only +2.0 points; (3)
  THEN discovered the dashboard (`shield/dashboard_server.py`) had NEVER
  actually been restarted between any of those fraction changes — confirmed by
  the team's own fix `57a56a2` "Fix dashboard control endpoints inheriting a
  stale cached .env value" (it caches `.env` at import and hands the stale copy
  to every "restart"). **This means the 0.75 and 1.0 readings above (75.0%,
  77.0%, 93.4%) cannot be trusted and must NOT be cited in the report.** The
  0.75 "confound correction" built on top of them is therefore also invalid.
  (4) Re-tested with the dashboard properly killed and relaunched each time:
  **fraction=0.5 confirmed clean across FOUR rates (3/10/50/150 req/s): 54.1%,
  50.8%, 58.3%, 50.8% — a tight, rate-independent band.** **fraction=1.0
  confirmed clean at 3 req/s: 96.7% (59/61), attack 100% blocked.** These two
  are the only trustworthy fraction data points from today.
  **NO valid fraction=0.75 reading exists — if the report needs one, it must be
  re-run.** Config decision stands: **`LEGITIMATE_SLOT_FRACTION=1.0`**, based on
  the clean 96.7% number, not the discarded 93.4%.
- **What was actually run** (see Run Table below): Phase 1 (baseline) — 100%.
  Phase 2 (attack, no Shield) — 2.2%. Phase 3 (attack, Shield with the unfixed
  perf bug) — 17.3%. Phase 4 (attack, Shield with both perf fixes) — 60.0%.
  2026-09-11, confirmed clean only: fraction=0.5 at 3/10/50/150 req/s — 54.1%/
  50.8%/58.3%/50.8%. fraction=1.0 at 3 req/s — **96.7% (recommended final)**.
  Profile D (cost-based attack) at fraction=0.5 — attack 100% rejected as 429
  token-budget (not 503), probe **98.4% survival**. Spoofed-as-legitimate attack
  (X-Priority header has zero authentication) collapsed survival to single
  digits until a new per-identity concurrency cap (`cf8bf91`) was added; tested
  with a genuinely separate second laptop, survival recovered to **49.2%**
  (sustained flood) and **35-49%** (Profile D, 2min/5min) against a
  fully-spoofing attacker. Full detail in the dated entries below.
- **Next actions, in priority order:** (1) get Syeda to push her real
  `service/start.sh` config for the record — still not done, (2) if the final
  report wants a `LEGITIMATE_SLOT_FRACTION=0.75` number, it must be freshly
  re-run (no valid reading exists), (3) write the final report — see
  `docs/SESSION_LOG.md`'s dated entries in order for the complete, honest
  narrative including the two invalidated/corrected findings above; do not
  present the fraction-sweep story as cleaner than it actually was.
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

## 2026-09-11 update — third caching bug, clean re-verification, Profile D, spoofing vulnerability, per-identity cap, two-laptop test, duration control

This entry covers everything after the fraction-sweep confusion documented below it
(kept, not deleted, for the full honest record) up through the last test of the day.

### Third caching bug: dashboard never restarted between fraction changes

After writing up the fraction sweep below (0.5→50.8%, 0.75→75.0%/77.0%, 1.0→93.4%)
and "correcting" it for the pipeline-reorder confound, asked directly whether the
Shield's dashboard (`shield/dashboard_server.py`) had been fully killed and relaunched
between each fraction change, or just clicked "restart" within it. Answer: **never
restarted, only reset via its own button.** At almost the same time, `57a56a2` "Fix
dashboard control endpoints inheriting a stale cached .env value" landed on `main`:
the dashboard calls `load_dotenv()` once at import and stays running for the session;
`subprocess.Popen()` hands that cached `os.environ` to every child by default, and
`pydantic-settings` prefers real env vars over `.env` file contents — so every
"restart" after the first was silently reusing whatever fraction was cached at
dashboard startup, not the value actually written to `.env` moments before. The
commit's own account: "edited .env back to 0.5, reset via the dashboard, log still
showed the old 3/1 split."

**Consequence stated plainly: the 0.75 and 1.0 readings from the sweep below (75.0%,
77.0%, 93.4%) cannot be trusted, and neither can the "+2.0 points, not dominant"
architecture-effect conclusion built on top of the 75.0%/77.0% pair — that comparison
itself may have been comparing two runs at some other stale fraction, not genuinely
0.75 both times.** Not deleting those numbers from this log, but flagging them here
as invalid for the report.

### Clean re-verification, dashboard properly killed and relaunched each time

Fraction=0.5, `sustained.js`, through the Shield, four different rates:
```
3 req/s:   54.1% (33/61)
10 req/s:  50.8% (31/61)   [one earlier attempt at this rate, 28.1% (16/57), discarded/unexplained — possibly interrupted, not diagnosed]
50 req/s:  58.3% (35/60)
150 req/s: 50.8% (31/61)   [also: 113/18001 (0.6%) attack requests got response_code=0 at this rate — minor strain signal, didn't touch the probe]
```
Tight 50-58% band across a 50x range in attack rate — real finding: survival at a
fixed fraction is rate-independent once above the server's real capacity, not a
floor that keeps eroding as the attacker pushes harder.

Fraction=1.0, `sustained.js`, 3 req/s, same properly-restarted dashboard:
**96.7% survival (59/61), attack traffic 100% blocked (0/360 got through).** This is
the number to cite for fraction=1.0 — not the earlier, invalidated 93.4%.

**No valid fraction=0.75 reading exists as of this entry.**

### Profile D baseline (cost-based admission control, proven live for the first time)

Fraction=0.5, `profile-d.js` (3 req/s, ~1600 prompt tokens + 512 output tokens/request),
through the Shield:
```
Attack: 360/360 rejected — ALL as HTTP 429 "Token budget exceeded" (zero 503s)
Probe:  60/61 succeeded = 98.4% survival
```
This is the cleanest live evidence in the project for its central thesis: the attack
was caught on ESTIMATED COST, not rate or queue pressure — a request-counting limiter
would see "3 req/s" and do nothing. Survival here is higher than any sustained-flood
result at the same fraction (50-58%) because the attack never passed the token-budget
check, so it never occupied a real slot at all.

### Spoofing vulnerability: X-Priority is an unauthenticated header

Read `shield/main.py`'s `is_priority_request()`:
```python
def is_priority_request(request: Request) -> bool:
    return request.headers.get("X-Priority", "").lower() == "legitimate"
```
No authentication at all — matches "client-supplied identity spoofing," a named
failure mode in the project's own cited research (VTC-style fairness).

**Implemented `ATTACK_SPOOF_LEGITIMATE`** (env var, shared name across `sustained.js`
and `profile-d.js`) — when set, the attack script sends `X-Priority: legitimate` on
its own traffic. Added a checkbox to `demo/index.html`, wired through
`demo/server.py`.

**First measurement — Profile D, spoofed, fraction=0.5:**
```
Attack: 359/360, 100% rejected (82×429, 276×503, 1×0)
Probe:  61 total, only 6 succeeded = 9.8% survival (down from 98.4% unspoofed)
Probe median latency: 43,477ms (was ~7,000ms)
```
Every attack request still failed, but merely COMPETING for the legitimate tier
(shared token bucket; any admitted huge Profile-D request occupies a real slot for a
long time) was enough to crush the real user. At fraction=1.0 (pre-caching-bug-fix,
so treat the exact number as unreliable per above): further collapse to ~3%.

### Per-identity concurrency cap (team's fix, found independently on their end too)

New commit `cf8bf91` "Add per-identity concurrency cap: defense when tiering is
defeated". Their own account: with `LEGITIMATE_SLOT_FRACTION=1.0` (simulating an
attacker with many accounts all legitimately carrying the header), the tier check
provided ZERO protection — every rejection was raw concurrency exhaustion
(`legitimate_in_flight >= 4`), not the tier check, since there was no "default" tier
left to separate anyone from. Their measured collapse: 1.4% success rate.

**Fix:** new `per_identity_concurrency_cap` setting (default 2) — caps in-flight
requests per SOURCE IP, trusting no claimed tier at all. Refund-safe (reuses
`bucket.refund(cost)`). Explicit, undeleted, documented limitation: source IP is a
practical identity proxy, not real per-account authentication — reasonable against a
single-machine attacker (what this project's load tests simulate), not a fully-solved
answer to a distributed attacker with many real IPs.

### Two-laptop test: does the identity cap actually protect a REAL, separate user?

Testing this from one laptop is invalid — the attack and probe would share this
laptop's IP, and the per-identity cap can't tell them apart, defeating the test.
Set up a second laptop running `probe.js` directly (not through the demo panel):
```
LLAMA_SERVER_URL=http://10.185.191.136:9090 PROBE_DURATION=2m k6 run --out csv=results/second_laptop_probe.csv loadgen/profiles/probe.js
```

**Sustained flood, spoofed, fraction=1.0:**
```
Same-IP probe (this laptop, confounded):  1.6% (1/61)
Different-IP probe (second laptop, real): 49.2%
```
**Profile D, spoofed, 2-minute run:**
```
Same-IP probe:  3.3% (2/61)
Different-IP:   35%
```
~30x difference between same-IP and different-IP in the sustained-flood case — real
confirmation the identity cap works when identities are genuinely separate, and the
same-IP numbers aren't a defense failure, they're the documented IP-as-identity-proxy
limitation showing up exactly as predicted.

Secondary finding: Profile D's different-IP survival (35%) is lower than sustained
flood's (49.2%) under the identical defense — a COUNT-based cap (2 concurrent) doesn't
fully neutralize a COST-based attack, since one admitted huge request occupies a slot
for a long time even at a cap of 2. This reinforces rather than contradicts the
project's thesis (price the request, not just cap its count) — the identity cap and
the token budget are complementary, neither alone is complete.

### Duration control added; final 5-minute confirming test

Added `ATTACK_DURATION` (shared env var, both attack scripts; was hardcoded `'2m'`),
wired through `demo/server.py` so probe and attack share the same duration for the
whole run, and a 1-15 minute slider in `demo/index.html`.

**Final test — Profile D, 5 minutes, spoofed as legitimate, two laptops:**
```
Attack: 898 total over 5 min (~3/s — confirms duration control works correctly)
Same-IP probe (this laptop):        150 total, 3 succeeded = 2.0% survival, median 6509ms
Different-IP probe (second laptop): 49% survival
```
Same pattern as the 2-minute version (3.3%/35%), now with a much larger sample (150 vs
61 probe requests) — a more statistically reliable confirmation, not a new finding.
The different-IP number moved from 35% to 49% between durations; with only two data
points this could be genuine variance or a real duration-dependent effect — not
enough data to say which, not asserting a cause.

### Explicit open gaps from today, stated plainly

- No valid `LEGITIMATE_SLOT_FRACTION=0.75` reading exists post-caching-fix. Must be
  re-run if the report needs one.
- The Profile D two-laptop test's exact fraction value at the moment of each run was
  not independently re-confirmed the way the sustained-flood one was — worth
  double-checking before citing in the report.
- `service/start.sh` still doesn't have the `--host 0.0.0.0` / `-np` (not `--np`) fixes
  committed — worked around manually on the host machine each session, never landed
  in the script itself.
- The one discarded 10 req/s reading (28.1%, n=57) was never diagnosed, only assumed
  to be an interrupted run.

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

