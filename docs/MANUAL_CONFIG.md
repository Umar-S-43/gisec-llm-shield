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
| llama-server's `-np` flag | `service/start.sh` (`NUM_PARALLEL`, actual flag passed to llama-server) **and** `shield/main.py` → `Settings.total_llama_slots` (env: `TOTAL_LLAMA_SLOTS`) | Defense C's slot-reservation math needs to know the real concurrency limit | Reservation fraction becomes meaningless — either over-reserves (wastes capacity the Shield thinks doesn't exist) or under-reserves (Defense C does nothing, attack traffic can fill every real slot) |
| `LLAMA_SERVER_URL` | `.env` (not committed) on every team member's machine, changes every session per CLAUDE.md's session-start checklist | Shield and every loadgen script need to reach the same live server address | Requests fail outright — looks like a crash, but is actually a stale/wrong IP from a previous session |
| Context size (`-c` flag, `CONTEXT_SIZE` in `service/start.sh`, default 2048) | `service/start.sh` **and** `loadgen/profiles/profile-d.js` (`MAX_PROMPT_WORDS` + `MAX_OUTPUT_TOKENS`, whose comment already says "keep aligned with -c") | Profile D is only a valid "maximum request" if its prompt+output token budget is actually what the running server can accept | **Currently NOT in sync at time of writing**: profile-d.js's defaults are ~1600 prompt tokens + 512 output tokens = ~2112, which exceeds the 2048 default context size. If `-c` isn't raised (or profile-d's numbers lowered) to match, Profile D requests may get truncated or rejected by llama-server itself for reasons unrelated to the Shield — muddying the "Shield caught it on cost" result the profile exists to demonstrate. |
| Shield's forward timeout to llama-server (hardcoded `timeout=60.0` in `_do_forward()`, `shield/main.py`) | `shield/main.py` (`_do_forward`) **and** `loadgen/profiles/profile-d.js` (client-side `timeout: '120s'`) | The Shield's internal HTTP client timeout must be at least as long as the slowest legitimate generation the load profiles ask for, especially on slow CPU-only hardware | **Currently NOT in sync**: profile-d.js's k6 client is willing to wait 120s for a 512-token generation, but the Shield's own forward call to llama-server times out at 60s. On a slow laptop, the Shield may kill and report a proxy error on a request that would have succeeded if given the same 120s the load generator itself allows — this looks like a Shield bug in the results, not a timeout mismatch. |
| Model filename (`Mistral-7B-Instruct-v0.1.Q4_K_M.gguf`) | `service/start.sh` (`MODEL_PATH` default) **and** `service/README.md` (download/`wget`/`mv` instructions) | The default `start.sh` expects to find exactly the file the README tells you to download | If someone downloads a different quantization/model without updating both places, `start.sh` fails at its own "model file not found" check — annoying but at least loud, not silent. Listed here anyway because it's plain-text duplication with no single source of truth. |
| Documented flag values in prose (`-np 1`, `-t 4`, `-c 2048`) | `service/README.md` (written out as bullet points) **and** `service/start.sh` (`NUM_PARALLEL`/`NUM_THREADS`/`CONTEXT_SIZE` defaults, the actual source of truth) | The README's bullet list is meant to describe what `start.sh` actually does | If `start.sh`'s defaults change and the README bullets aren't updated, the README silently becomes wrong documentation — no functional break, but anyone reading the README instead of the script will be misled about what's actually running. |

## Unsure — flagging rather than deciding

These looked like the same category of problem, but they're tuning assumptions
rather than a literal duplicated value, so it's a judgment call whether they belong
above. Listed here instead of silently included or excluded:

- **`deferred_shed_threshold_default` / `_legitimate`** (2 / 8, `shield/main.py`)
  implicitly assume a particular `total_llama_slots`/`-np`. A deferred-queue depth
  of "2" is a meaningfully different signal when `-np=1` versus `-np=8` — the
  thresholds were not derived from `total_llama_slots` by any formula, they're
  separate hand-picked constants. If `-np` changes, these may need to change too,
  but nothing ties them together even conceptually the way the slot-reservation
  fraction is at least computed from `total_llama_slots`.

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
