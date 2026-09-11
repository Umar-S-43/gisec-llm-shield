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
| llama-server's `-np`/`--parallel` flag | `service/start.sh` and `service/start.ps1` (`NUM_PARALLEL`, default **4**) **and** `shield/main.py` → `Settings.total_llama_slots` (env: `TOTAL_LLAMA_SLOTS`, default **4**) | Defense C's slot-reservation math needs to know the real concurrency limit — AND the actual launch flag has to be one llama-server accepts | **Two separate bugs, fixed at different times.** Value sync (fixed 2026-09-09): `service/start.sh`'s `NUM_PARALLEL` had never been updated past llama-server's implicit default of 1, even after `shield/main.py`'s `total_llama_slots` was raised to 4 — the two sides had silently drifted apart. **Flag name (fixed 2026-09-09, in the `feature/service` branch — not caught by the value-sync fix above):** independently of the *value* being right, `service/start.sh` was invoking llama-server with `--np "$NUM_PARALLEL"` — `--np` as a long option is not a flag this llama.cpp build accepts (confirmed directly against the binary: `--np 4` returns `error: invalid argument: --np`). The correct flag is `-np`/`--parallel`. This meant the launcher could not start the server AT ALL, regardless of what `NUM_PARALLEL` was set to, until this fix landed — worth re-confirming against whichever `llama-server` binary you actually run, since a different build might alias `--np` differently. Also watch the `_default_slot_capacity <= 0` case: with `total_llama_slots=1` and the default 0.5 fraction, default-tier traffic gets 100% rejected by slot reservation alone, before the token budget ever runs — the Shield logs a loud warning for this at startup, but it's still a real trap if you deliberately drop back to `-np 1`. |
| `LLAMA_SERVER_URL` | `.env` (not committed) on every team member's machine, changes every session per CLAUDE.md's session-start checklist | Shield and every loadgen script need to reach the same live server address | Requests fail outright — looks like a crash, but is actually a stale/wrong IP from a previous session |
| llama-server's `--host` flag | `service/start.sh` / `service/start.ps1` (`LLAMA_SERVER_HOST`, default `0.0.0.0`) | llama-server's own default is `127.0.0.1` (loopback-only) if `--host` is omitted — unreachable from any other laptop | **Fixed 2026-09-09, in `feature/service` — not present anywhere before this merge**: neither launcher passed `--host` at all. The server was loopback-only, unreachable from a load-generator machine over the hotspot, which breaks the session-start checklist's entire premise. Both launchers now pass `--host 0.0.0.0` explicitly. |
| Context size (`-c`/`--ctx-size`) | `service/start.sh` / `service/start.ps1` (`CONTEXT_SIZE`, now derived as `NUM_PARALLEL × CONTEXT_SIZE_PER_SLOT`, default per-slot 2560) **and** `loadgen/profiles/profile-d.js` (`MAX_PROMPT_WORDS` + `MAX_OUTPUT_TOKENS`) | Profile D is only a valid "maximum request" if its prompt+output token budget is actually what a single SLOT can accept | **Root cause found 2026-09-09, in `feature/service` — supersedes an earlier interim fix.** `-c`/`--ctx-size` is llama-server's TOTAL context, and it is divided EVENLY across `-np` slots. Confirmed empirically: `--parallel 4 --ctx-size 2048` produces `n_ctx_slot=512`, NOT 2048 per slot. The old flat `CONTEXT_SIZE=2048` default gave each of 4 slots only 512 tokens — nowhere near Profile D's ~2112-token requests. **An earlier interim fix (also 2026-09-09) raised the flat total to 4096 without knowing about the per-slot division** — at `-np=4` that's still only 1024 tokens/slot, likely still short of Profile D's needs. Since Profile D had not yet been run live as of this merge (see `docs/SESSION_LOG.md`'s next-actions list), no previously reported result is invalidated by this — but the corrected sizing needs to land *before* Profile D's first live run, not after. Launchers now compute `CONTEXT_SIZE = NUM_PARALLEL × CONTEXT_SIZE_PER_SLOT` so it scales automatically; if you change `NUM_PARALLEL` by hand, re-check that per-slot context still covers your largest loadgen profile. |
| Shield's forward timeout to llama-server (`Settings.forward_timeout_seconds`, `shield/main.py`, default **130.0s**) | `shield/main.py` (`_do_forward`, reads `settings.forward_timeout_seconds`) **and every loadgen script's client-side `timeout`** — `loadgen/profiles/profile-d.js` (`120s`) **and** `loadgen/profiles/probe.js` (`130s`, fixed 2026-09-10 — see below) | The Shield's internal HTTP client timeout must stay comfortably ABOVE the longest client-side timeout any loadgen script sets, not equal to it — otherwise the Shield can kill a request the client itself was still willing to wait for, OR (the `probe.js` case below) the k6 client gives up before the Shield legitimately could have answered | **Fixed 2026-09-09** for the Shield/`profile-d.js` pair (was hardcoded 60.0s, half of profile-d.js's 120s client timeout). **A second instance of the same bug class was found and fixed 2026-09-10:** `probe.js` — the script generating the "legitimate user" cohort measured in Phase 3 — was still at its original `30s` timeout, never updated when the Shield's ceiling was raised. Any probe request the Shield legitimately took >30s to service under flood load would read to k6 as a hard failure (`response_code=0`) even though the Shield/server might still have answered correctly. Raised to `130s`. `baseline.js`, `spike.js`, and `sustained.js` remain at `60s` — below the Shield's ceiling — check against the same logic if they're ever used to measure legitimate-cohort survival under heavy load. **Made configurable (2026-09-09, `feature/service`):** was a hardcoded literal inside `_do_forward()`; now `Settings.forward_timeout_seconds`, settable via `.env`'s `FORWARD_TIMEOUT_SECONDS`, still defaulting to the same already-vetted 130.0. If `profile-d.js` or `probe.js`'s client timeout is ever raised further, raise this to stay above it. |
| Model filename (`Mistral-7B-Instruct-v0.1.Q4_K_M.gguf` by default) | `service/start.sh` / `service/start.ps1` (`MODEL_PATH` default) **and** `service/README.md` (download instructions) | The default launcher expects to find exactly the file the README tells you to download | If someone downloads a different quantization/model without updating both places, the launcher fails its own "model file not found" check — annoying but at least loud, not silent. On this repo's dev machine the actually-downloaded model is `models/qwen2.5-1.5b-instruct-q4_k_m.gguf` (Qwen preset), so `MODEL_PATH` must be set explicitly in `.env` — the launcher default was never changed to match, by design (see `service/README.md`'s Windows setup instructions). |
| Documented flag values in prose (`-np`, `-t`, `-c`) | `service/README.md` (written out as bullet points) **and** `service/start.sh`/`service/start.ps1` (`NUM_PARALLEL`/`NUM_THREADS`/`CONTEXT_SIZE` defaults, the actual source of truth) | The README's bullet list is meant to describe what the launchers actually do | If the launchers' defaults change and the README bullets aren't updated, the README silently becomes wrong documentation — no functional break, but anyone reading the README instead of the script will be misled about what's actually running. |
| `SHIELD_ACTIVE` env var vs. runtime state | `shield/main.py` → `Settings.shield_active` (startup value only) **and** the mutable `_shield_active` global, toggled via `POST /admin/shield-active` | `loadgen/run_comparison.sh` needs to flip defense-off/defense-on between rounds WITHOUT restarting the Shield process (restarting mid-comparison would reset in-flight counters/token buckets and break the "identical process, only the policy differs" design) | **Added 2026-09-09, in `feature/service`**: before this, `SHIELD_ACTIVE` could only be set at process start, so `run_comparison.sh` bypassed the Shield entirely for its "off" leg — hitting `llama-server` directly instead of the Shield with defenses disabled. That confounded every on/off comparison with an extra network hop / proxy overhead unrelated to the actual defense. Both legs now target the Shield; only `/admin/shield-active` differs between them. |

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
