# Manual Configuration — Values That Must Be Kept In Sync By Hand

**Check this file before changing `-np`, before starting a new session, and before
tuning any threshold — a mismatch here is silent, not an error.**

Everything below is a value that appears in more than one place, or that was tuned
assuming a value defined somewhere else, with **no code enforcing that they match**.
Nothing will throw, log, or fail loudly when one of these drifts — the system just
quietly stops doing what it's supposed to. Skim this table any time you touch a flag,
a constant, or a `.env` value.

## Confirmed — currently must be kept in sync

| Value | Locations | Must match because | Breaks if out of sync |
|---|---|---|---|
| llama-server's `-np` flag | `service/start.sh` (`NUM_PARALLEL`, actual flag passed to llama-server) **and** `shield/main.py` → `Settings.total_llama_slots` (env: `TOTAL_LLAMA_SLOTS`) | Defense C's slot-reservation math needs to know the real concurrency limit | **Now actually in sync (fixed 2026-09-09): both = 4.** `service/start.sh` had never been updated past llama-server's implicit default of 1, even after `shield/main.py`'s `total_llama_slots` was raised to 4 in an earlier, undocumented decision — so the two sides had silently drifted apart since before this file existed. `-np 4` is now written out explicitly in `start.sh` (matching how `-t`/`-c` are already handled) instead of left as an implicit default. Before the fix, this would have over-reserved: Defense C's slot math would have assumed 4 real slots when llama-server only had 1. |
| `LLAMA_SERVER_URL` | `.env` (not committed) on every team member's machine, changes every session per CLAUDE.md's session-start checklist | Shield and every loadgen script need to reach the same live server address | Requests fail outright — looks like a crash, but is actually a stale/wrong IP from a previous session |
| Context size (`-c` flag, `CONTEXT_SIZE` in `service/start.sh`, now **4096**) | `service/start.sh` **and** `loadgen/profiles/profile-d.js` (`MAX_PROMPT_WORDS` + `MAX_OUTPUT_TOKENS`, whose comment already says "keep aligned with -c") | Profile D is only a valid "maximum request" if its prompt+output token budget is actually what the running server can accept | **Fixed 2026-09-09** (was 2048, now 4096): profile-d.js's defaults are ~1600 prompt tokens + 512 output tokens ≈ 2112 — that alone left almost no margin against the old 2048 limit, and other overhead (chat template, system prompt, tokenizer rounding) could push it over. 4096 was chosen for real headroom above Profile D's known worst case, not just to clear it. If profile-d.js's token budget is ever raised further, re-check it still leaves headroom under 4096 — this entry doesn't stop mattering just because it's fixed once. |
| Shield's forward timeout to llama-server (`timeout=` in `_do_forward()`, `shield/main.py`, now **130.0s**) | `shield/main.py` (`_do_forward`) **and every loadgen script's client-side `timeout`** — `loadgen/profiles/profile-d.js` (`120s`) **and** `loadgen/profiles/probe.js` (now **`130s`**, fixed 2026-09-10 — see below) | The Shield's internal HTTP client timeout must stay comfortably ABOVE the longest client-side timeout any loadgen script sets, not equal to it — otherwise the Shield can kill a request the client itself was still willing to wait for, OR (the `probe.js` case below) the k6 client gives up before the Shield legitimately could have answered | **Fixed 2026-09-09** for the Shield/`profile-d.js` pair (was 60.0s, now 130.0s — 10s of margin above profile-d.js's 120s client timeout). **A second instance of the same bug class was found and fixed 2026-09-10:** `probe.js` — the script that generates the "legitimate user" cohort measured in Phase 3 — was still at its original `30s` timeout, never updated when the Shield's ceiling was raised to 130.0s. This meant any probe request the Shield legitimately took >30s to service (very plausible under Phase 3's sustained-flood load) would read to k6 as a hard failure (`response_code=0`) even though the Shield/server might still have answered correctly. Raised to `130s` to match the same "comfortably above, not equal to" pairing logic as `profile-d.js`. `baseline.js`, `spike.js`, and `sustained.js` remain at `60s` — below the Shield's 130.0s ceiling — and should be checked against the same logic if they're ever used to measure legitimate-cohort survival under heavy load rather than just baseline/attack shaping. If `profile-d.js` or `probe.js`'s client timeout is ever raised further, the Shield's 130.0s must be raised to stay above it. |
| Model filename (`Mistral-7B-Instruct-v0.1.Q4_K_M.gguf`) | `service/start.sh` (`MODEL_PATH` default) **and** `service/README.md` (download/`wget`/`mv` instructions) | The default `start.sh` expects to find exactly the file the README tells you to download | If someone downloads a different quantization/model without updating both places, `start.sh` fails at its own "model file not found" check — annoying but at least loud, not silent. Listed here anyway because it's plain-text duplication with no single source of truth. |
| Documented flag values in prose (`-np 4`, `-t 4`, `-c 4096`) | `service/README.md` (written out as bullet points) **and** `service/start.sh` (`NUM_PARALLEL`/`NUM_THREADS`/`CONTEXT_SIZE` defaults, the actual source of truth) | The README's bullet list is meant to describe what `start.sh` actually does | If `start.sh`'s defaults change and the README bullets aren't updated, the README silently becomes wrong documentation — no functional break, but anyone reading the README instead of the script will be misled about what's actually running. Updated alongside the `-c` fix above (2026-09-09) so this row doesn't itself go stale. |

## Performance tuning knobs — implemented but unverified against real load

Unlike the table above, these aren't cross-file sync pairs — each is a single
tunable with no "other side" to drift out of sync with. Listed here because they
were changed in response to a specific incident and haven't been confirmed to
actually fix it yet; don't cite these as "fixed" in the report until a rerun says so.

- **`SLOT_CHECK_TTL`** (`shield/main.py` → `Settings.slot_check_ttl`, env:
  `SLOT_CHECK_TTL`, default **0.5s**) — added 2026-09-10, after the Phase 3
  sustained-flood test (50 req/s through the Shield, `llama-server` saturated by
  ~4,950 attack requests) showed a large gap between requests the Shield's own
  reconciliation log recorded as successfully forwarded (19 legitimate-tier 200s)
  and what the k6 client actually observed as successes (9). The theory: before
  this fix, `slot_available()` opened a brand-new `httpx.AsyncClient()` and made an
  uncached network round trip to `/slots?fail_on_no_slot=1` on **every single
  incoming request**, with up to `metrics_poll_timeout` (2s) to wait — on the
  Shield's single asyncio event loop (no worker pool), this could plausibly queue
  up under flood volume and delay responses (including already-successful ones)
  past the client's own timeout.

  **Status: implemented, NOT confirmed.** The fix mirrors `get_requests_deferred()`'s
  existing cache pattern (short TTL + shared connection-pooled client instead of a
  fresh one per call) but changes nothing about admission logic — same
  200-means-available check, same fail-open behavior. Confirming this requires
  rerunning the *same* Phase 3 profile (same seed/schedule where possible) and
  comparing the `response_code: 0` ("no response at all") count before vs. after.
  If that count doesn't drop meaningfully, this fix should be written up as "did
  not resolve it" rather than left silently claiming success — see the
  investigation notes for what else was ruled in/out (e.g. whether the results
  folder being inside a OneDrive-synced directory was a contributing factor,
  independent of this code path).

  0.5s was chosen to match `get_requests_deferred()`'s existing `_DEFERRED_CACHE_TTL`
  for consistency, not because 0.5s specifically was measured to be correct here —
  tune it once real rerun data exists rather than guessing a "better" number now.

## Unsure — flagging rather than deciding

These looked like the same category of problem, but they're tuning assumptions
rather than a literal duplicated value, so it's a judgment call whether they belong
above. Listed here instead of silently included or excluded.

**Correction (2026-09-09):** both inference write-ups below were originally done
against `-np=1`, reasoning that `-np=4` "doesn't appear configured anywhere in this
repo." That was true at the time, but it turned out to be the bug, not a correct
read of intent — `shield/main.py`'s `total_llama_slots` had already been decided as 4
in an earlier step, just never actually applied to `service/start.sh`. Now that both
sides are fixed to 4 (see table above), the inferences below have been redone against
the correct value.

- **`deferred_shed_threshold_default` / `_legitimate`** (2 / 8, `shield/main.py`)
  implicitly assume a particular `total_llama_slots`/`-np`. A deferred-queue depth
  of "2" is a meaningfully different signal when `-np=1` versus `-np=8` — the
  thresholds were not derived from `total_llama_slots` by any formula, they're
  separate hand-picked constants. If `-np` changes, these may need to change too,
  but nothing ties them together even conceptually the way the slot-reservation
  fraction is at least computed from `total_llama_slots`.

  **Unverified inference (corrected 2026-09-09), against the actual `-np=4` /
  `total_llama_slots=4`** — see the correction note above the table row; this was
  previously reasoned against `-np=1` by mistake. With `total_llama_slots=4` and
  `legitimate_slot_fraction=0.5`, Defense C's own math reserves 2 slots for
  legitimate traffic and leaves `default_capacity=2` slots for everything else
  (`ceil(4*0.5)=2`, `4-2=2`). Read against those numbers, `deferred_shed_threshold_
  default=2` lines up exactly with `default_capacity=2` — plausibly "shed default
  traffic once its own deferred backlog equals its own slot allocation," which is a
  cleaner, more deliberate-looking relationship than the `-np=1` reading produced.
  `deferred_shed_threshold_legitimate=8` is then `2× total_llama_slots` (4), which
  reads as "tolerate a queue twice the size of the whole server's concurrency before
  even legitimate traffic gets shed" — a much more generous, "only shed under severe
  backlog" setting, consistent with the code comment beside it. This is a tighter,
  more plausible-looking fit than the `-np=1` version, but it is still an inferred
  pattern-match on the numbers, not something confirmed by a comment, commit message,
  or measured test in the repo — flagging as inference, not verified constraint.

  **Cross-reference (2026-09-09):** the `default_capacity=2` figure above comes from
  Defense C's own slot-reservation formula, which uses `total_llama_slots` directly —
  so this "unsure" bucket-threshold inference is at least partially anchored to
  reasoning that already appears in confirmed, executed code, not just an outside
  guess. That's why it's included here rather than dismissed outright, while still
  not being promoted to the confirmed table above.

- **Token bucket capacities/refill rates** (`legitimate_bucket_capacity=2000`,
  `default_bucket_capacity=500`, and their refill rates, `shield/main.py`) appear
  to have been sized with the loadgen profiles' actual prompt/`n_predict` values in
  mind (e.g. `sustained.js`'s cost of ~207/request against a 500-capacity bucket
  refilling at 50/sec is clearly meant to shed quickly; `profile-d.js`'s cost of
  ~2112 exceeds even the legitimate bucket's 2000 capacity outright). But this is
  an inferred design intent, not a value copied from one file into another — there's
  no single number that's "the same" in two places to point at. Included here as a
  flag rather than a confirmed table row: if someone changes a loadgen profile's
  `n_predict` significantly, it's worth re-checking whether the bucket constants
  still produce the intended demonstration (shed vs. admit) rather than assuming
  they'll silently keep working.

  **Unverified inference (corrected 2026-09-09), against the actual `-np=4` /
  `total_llama_slots=4`** — previously reasoned against `-np=1` by mistake (see
  correction note above). Dividing `default_bucket_refill_rate=50` cost-units/sec
  across the 4 real slots gives ~12.5 tokens/sec/slot as the implied assumed
  generation speed on the target CPU hardware — a noticeably more plausible number
  for CPU-only inference on a 7B-class model than the ~50 tokens/sec a single-slot
  (`-np=1`) reading implied. That makes the `-np=4` reading the more credible of the
  two, though still unconfirmed by any benchmark in this repo. `default_bucket_
  capacity=500` against Defense C's `default_capacity=2` reserved slots (see the
  deferred-shed-threshold entry above) is close to "2 concurrent `sustained.js`-shaped
  requests' worth of cost (~207 each, ~414 total) plus a bit of burst room" — i.e. the
  token budget and the concurrency reservation both land on roughly "2 default-tier
  requests" as their effective cap, independently of each other. Whether that
  agreement was deliberate or coincidental is not knowable from the repo alone — still
  an inferred pattern-match, not a confirmed constraint. If the target hardware's real
  generation speed turns out to be far from ~12.5 tokens/sec/slot, these constants are
  worth re-measuring rather than trusting as-is.
