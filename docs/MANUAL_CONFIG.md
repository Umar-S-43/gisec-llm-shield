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
| llama-server's `-np`/`--parallel` flag | `service/start.sh` and `service/start.ps1` (`NUM_PARALLEL`, default **4** as of 2026-09-09) **and** `shield/main.py` → `Settings.total_llama_slots` (env: `TOTAL_LLAMA_SLOTS`, default **4**, matched to the launchers) | Defense C's slot-reservation math needs to know the real concurrency limit | Reservation fraction becomes meaningless — either over-reserves (wastes capacity the Shield thinks doesn't exist) or under-reserves (Defense C does nothing, attack traffic can fill every real slot). **Also watch the `_default_slot_capacity <= 0` case**: with `total_llama_slots=1` and the default 0.5 fraction, default-tier traffic gets 100% rejected by slot reservation alone, before the token budget ever runs — the Shield now logs a loud warning for this at startup, but it's still a real trap if you deliberately drop back to `-np 1`. |
| `LLAMA_SERVER_URL` | `.env` (not committed) on every team member's machine, changes every session per CLAUDE.md's session-start checklist | Shield and every loadgen script need to reach the same live server address | Requests fail outright — looks like a crash, but is actually a stale/wrong IP from a previous session |
| llama-server's `--host` flag | `service/start.sh` / `service/start.ps1` (`LLAMA_SERVER_HOST`, default `0.0.0.0`) | llama-server's own default is `127.0.0.1` (loopback-only) if `--host` is omitted — unreachable from any other laptop | **Fixed 2026-09-09**: both launchers now pass `--host 0.0.0.0` explicitly. Before this fix, the session-start checklist (post IP, everyone updates `.env`) could not work at all — the server would refuse every connection that wasn't from `localhost`. |
| Context size (`-c`/`--ctx-size`) | `service/start.sh` / `service/start.ps1` (`CONTEXT_SIZE`, now derived as `NUM_PARALLEL × CONTEXT_SIZE_PER_SLOT`, default per-slot 2560) **and** `loadgen/profiles/profile-d.js` (`MAX_PROMPT_WORDS` + `MAX_OUTPUT_TOKENS`, whose comment already says "keep aligned with -c") | Profile D is only a valid "maximum request" if its prompt+output token budget is actually what a single SLOT can accept | **Root cause found 2026-09-09, not just "not in sync" — the old doc entry undersold it**: `-c`/`--ctx-size` is llama-server's TOTAL context, and it is divided EVENLY across `-np` slots. Confirmed empirically: `--parallel 4 --ctx-size 2048` produces `n_ctx_slot=512`, NOT 2048 per slot. So the old `CONTEXT_SIZE=2048` default gave each of 4 slots only 512 tokens — nowhere near Profile D's ~2112-token requests, which would be truncated/rejected by llama-server itself, not the Shield. Launchers now compute `CONTEXT_SIZE = NUM_PARALLEL × CONTEXT_SIZE_PER_SLOT` so this scales automatically; if you change `NUM_PARALLEL` by hand instead of via the env var, re-check that per-slot context still covers your largest loadgen profile. |
| Shield's forward timeout to llama-server (`Settings.forward_timeout_seconds`, `shield/main.py`) | `shield/main.py` (`_do_forward`, now reads `settings.forward_timeout_seconds`, default **120.0**) **and** `loadgen/profiles/profile-d.js` (client-side `timeout: '120s'`) | The Shield's internal HTTP client timeout must be at least as long as the slowest legitimate generation the load profiles ask for, especially on slow CPU-only hardware | **Fixed 2026-09-09**: was hardcoded to 60.0, half of profile-d.js's 120s client timeout — the Shield could kill and report a proxy error on a request that would have succeeded if given the same 120s the load generator itself allows. Now both default to 120s; if you raise profile-d's `timeout`, raise `FORWARD_TIMEOUT_SECONDS` in `.env` too. |
| Model filename (`Mistral-7B-Instruct-v0.1.Q4_K_M.gguf` by default) | `service/start.sh` / `service/start.ps1` (`MODEL_PATH` default) **and** `service/README.md` (download instructions) | The default launcher expects to find exactly the file the README tells you to download | If someone downloads a different quantization/model without updating both places, the launcher fails its own "model file not found" check — annoying but at least loud, not silent. On this repo's dev machine the actually-downloaded model is `models/qwen2.5-1.5b-instruct-q4_k_m.gguf` (Qwen preset), so `MODEL_PATH` must be set explicitly in `.env` — the launcher default was never changed to match, by design (see `service/README.md`'s Windows setup instructions). |
| Documented flag values in prose (`-np`, `-t`, `-c`) | `service/README.md` (written out as bullet points) **and** `service/start.sh`/`service/start.ps1` (`NUM_PARALLEL`/`NUM_THREADS`/`CONTEXT_SIZE` defaults, the actual source of truth) | The README's bullet list is meant to describe what the launchers actually do | If the launchers' defaults change and the README bullets aren't updated, the README silently becomes wrong documentation — no functional break, but anyone reading the README instead of the script will be misled about what's actually running. |
| `SHIELD_ACTIVE` env var vs. runtime state | `shield/main.py` → `Settings.shield_active` (startup value only) **and** the mutable `_shield_active` global, toggled via `POST /admin/shield-active` | `loadgen/run_comparison.sh` needs to flip defense-off/defense-on between rounds WITHOUT restarting the Shield process (restarting mid-comparison would reset in-flight counters/token buckets and break the "identical process, only the policy differs" design) | **Added 2026-09-09**: before this, `SHIELD_ACTIVE` could only be set at process start, so `run_comparison.sh` bypassed the Shield entirely for its "off" leg — hitting `llama-server` directly instead of the Shield with defenses disabled. That confounded every published on/off comparison with an extra network hop / proxy overhead that has nothing to do with the defense. Both legs now target the Shield; only `/admin/shield-active` differs between them. |

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
