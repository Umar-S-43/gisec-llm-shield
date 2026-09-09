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
| Context size (`-c` flag, `CONTEXT_SIZE` in `service/start.sh`, now **4096**) | `service/start.sh` **and** `loadgen/profiles/profile-d.js` (`MAX_PROMPT_WORDS` + `MAX_OUTPUT_TOKENS`, whose comment already says "keep aligned with -c") | Profile D is only a valid "maximum request" if its prompt+output token budget is actually what the running server can accept | **Fixed 2026-09-09** (was 2048, now 4096): profile-d.js's defaults are ~1600 prompt tokens + 512 output tokens ≈ 2112 — that alone left almost no margin against the old 2048 limit, and other overhead (chat template, system prompt, tokenizer rounding) could push it over. 4096 was chosen for real headroom above Profile D's known worst case, not just to clear it. If profile-d.js's token budget is ever raised further, re-check it still leaves headroom under 4096 — this entry doesn't stop mattering just because it's fixed once. |
| Shield's forward timeout to llama-server (`timeout=` in `_do_forward()`, `shield/main.py`, now **130.0s**) | `shield/main.py` (`_do_forward`) **and** `loadgen/profiles/profile-d.js` (client-side `timeout: '120s'`) | The Shield's internal HTTP client timeout must stay comfortably ABOVE the longest client-side timeout any loadgen script sets, not equal to it — otherwise the Shield can kill a request the client itself was still willing to wait for | **Fixed 2026-09-09** (was 60.0s, now 130.0s — 10s of margin above profile-d.js's 120s client timeout). Both values are written out here on purpose: if profile-d.js's client timeout is ever raised above ~120s, the Shield's 130.0s must be raised to stay above it, or a slow-but-legitimate generation will get killed by the Shield and misread as "the Shield is broken" rather than a timeout mismatch. |
| Model filename (`Mistral-7B-Instruct-v0.1.Q4_K_M.gguf`) | `service/start.sh` (`MODEL_PATH` default) **and** `service/README.md` (download/`wget`/`mv` instructions) | The default `start.sh` expects to find exactly the file the README tells you to download | If someone downloads a different quantization/model without updating both places, `start.sh` fails at its own "model file not found" check — annoying but at least loud, not silent. Listed here anyway because it's plain-text duplication with no single source of truth. |
| Documented flag values in prose (`-np 1`, `-t 4`, `-c 4096`) | `service/README.md` (written out as bullet points) **and** `service/start.sh` (`NUM_PARALLEL`/`NUM_THREADS`/`CONTEXT_SIZE` defaults, the actual source of truth) | The README's bullet list is meant to describe what `start.sh` actually does | If `start.sh`'s defaults change and the README bullets aren't updated, the README silently becomes wrong documentation — no functional break, but anyone reading the README instead of the script will be misled about what's actually running. Updated alongside the `-c` fix above (2026-09-09) so this row doesn't itself go stale. |

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

  **Unverified inference (2026-09-09), against the repo's actual current default of
  `-np=1` / `total_llama_slots=1`** — not `-np=4`, which doesn't appear configured
  anywhere in this repo; if `-np` is meant to be 4 that change hasn't been made yet.
  With `total_llama_slots=1`, `requests_deferred` can only ever be 0 or grow one at a
  time as requests queue behind the single busy slot, so a threshold of "2" for
  default-tier traffic plausibly means "shed as soon as even one extra request is
  waiting behind the one in flight" — an aggressive, close-to-zero-tolerance setting
  that makes sense if the goal is to keep the single slot free for legitimate traffic
  as much as possible. The legitimate threshold of "8" would then mean "tolerate a
  queue of 8 waiting requests behind 1 slot before even legitimate traffic gets shed"
  — a much larger absolute number than the slot count itself, which only makes sense
  as "don't shed legitimate traffic until things are severely backed up." Both readings
  are plausible with `-np=1`, but neither was confirmed against actual measured
  behavior — flagging as inference, not verified constraint. If `-np` is later
  increased, these absolute thresholds (2 and 8) will represent a different relative
  backlog than they do today, and should be re-examined rather than assumed to scale.

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

  **Unverified inference (2026-09-09):** lining the numbers up loosely against
  `total_llama_slots=1` — `default_bucket_refill_rate=50` cost-units/sec against a
  single slot implies an assumed average generation speed of roughly 50 tokens/sec
  on the target CPU hardware (i.e. the bucket refills at roughly the rate one busy
  slot can actually consume tokens, so a single legitimate-shaped request mostly
  keeps up with its own refill). `default_bucket_capacity=500` is then close to "one
  `sustained.js`-shaped request's cost (~207) plus a bit of burst room," which would
  explain why a handful of default-tier requests are admitted before shedding kicks
  in rather than the very first one. This is a plausible reverse-engineering of
  intent, not something confirmed by a comment, commit message, or benchmark in the
  repo — if the actual target hardware generates meaningfully faster or slower than
  ~50 tokens/sec, these constants may be tuned around the wrong assumption and worth
  re-measuring rather than trusting as-is.
