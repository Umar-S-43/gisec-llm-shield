# CLAUDE.md — GISEC Hackathon: Defending an LLM Inference Server Against Availability Stress

This file is read automatically by Claude Code at the start of every session in this repo.
It is also meant to be readable by any human on the team — if you're confused about why a
folder exists or why we made a decision, read this before asking. Everything here is
written assuming you know general software engineering but NOT cybersecurity jargon.

---

## What we're actually building, in plain terms

An AI chatbot server (like a mini version of ChatGPT, running on a laptop instead of a
data center) can be knocked offline or made unusably slow just by flooding it with
requests — this is called a Denial-of-Service (DoS) attack. Our project builds:

1. A small AI server (`llama-server`) that intentionally has very little capacity, so it's
   easy to overload on a laptop without needing expensive cloud hardware.
2. A "Shield" — a small program that sits in front of the AI server and decides which
   requests to let through, which to slow down, and which to reject, based on how
   expensive each request actually is (not just how many requests there are).
3. A load-testing harness that throws different attack patterns at the server so we can
   prove the Shield actually works — and prove it with real statistics, not "trust me."

**The core idea we're proving:** most existing defenses count *requests* — "no more than
100 requests per minute." That's blind to cost. One request asking for a 1-word answer and
one request asking for a 4000-word answer count the same to a request-counter, but the
second one costs 100x more compute. Our Shield counts *tokens* (roughly: words) instead of
requests, which is a smarter, cost-aware way to defend the server.

---

## Why CPU-only / llama.cpp, not GPU / vLLM (read this before touching config)

Early planning assumed we'd need a GPU and the `vLLM` software. We dropped that. Reasons:

- `vLLM` on CPU needs a specific CPU feature (`avx512f`) most laptops don't have, has no
  ready-to-install version for CPU, and would need to be built from source — a full day of
  risk for a 4-day project, for zero benefit.
- `llama.cpp` (specifically its `llama-server` program) is a single file you run directly,
  works fine on CPU, and already reports the exact metrics our Shield needs.
- The science doesn't care about scale. Whether the server handles 5 requests/second on a
  laptop or 500/second on a data-center GPU, the *comparison* — smart limiter vs dumb
  limiter, under identical attack traffic — works the same either way. A weak laptop
  server actually *helps* us: it gets overloaded fast, so we don't need hours per test run.

**Rule: never write code, comments, or docs that reference vLLM metric names, GPU flags,
or CUDA. This project is CPU-only, llama.cpp-only.** If you see `vllm:` anywhere, it's
wrong — flag it, don't just extend it.

---

## Metric name reference — use ONLY the right-hand column

| What we're measuring | ❌ vLLM name (do NOT use) | ✅ llama.cpp name (use this) |
|---|---|---|
| Requests currently being processed | `vllm:num_requests_running` | `llamacpp:requests_processing` |
| Requests waiting in queue (our "shed now?" signal) | `vllm:num_requests_waiting` | `llamacpp:requests_deferred` |
| Server memory/capacity full | `vllm:kv_cache_usage_perc` | **No equivalent exists.** Use `GET /slots?fail_on_no_slot=1` (returns HTTP 503 when full) and `GET /slots` (per-slot detail) instead. |
| Prompt vs. generation speed | n/a | `llamacpp:prompt_tokens_seconds` and `llamacpp:predicted_tokens_seconds` |
| How efficiently requests are batched together | n/a | `llamacpp:n_busy_slots_per_decode` |
| Total tokens processed | n/a | `llamacpp:prompt_tokens_total`, `llamacpp:tokens_predicted_total` |

Metrics only appear at all if `llama-server` is started with the `--metrics` flag. Forgetting
this flag is the single easiest mistake to make — `/metrics` will just 404 silently.

---

## Repo layout, and *why* each folder exists

- **`/service`** — Starts `llama-server` itself. This is the actual AI model, deliberately
  hobbled (`-np` low = few concurrent request "slots", `-t` pinned = fixed thread count,
  `-c` set explicitly = fixed memory ceiling) so it's easy to overload on a laptop. Owned
  by Syeda.

- **`/shield`** — Our actual contribution. A small web server (FastAPI) that every request
  passes through *before* reaching `llama-server`. On Day 1 it just logs (pass-through, no
  blocking). By Day 3 it does three things in order: (A) checks a token budget and rejects
  cheaply-overpriced requests, (B) watches `llamacpp:requests_deferred` and sheds load
  before the real server chokes, (C) makes sure "legitimate" traffic gets priority over
  "attack" traffic even under load. Owned by Umar.

- **`/loadgen`** — Traffic generators. `k6` scripts simulate different attack shapes
  (steady traffic, sudden spikes, sustained floods, and slow-but-expensive requests).
  A separate small constant stream simulates a "real, legitimate user" running alongside
  the attack, so we can measure whether the Shield protects them. Owned by Behzad.

- **`/analysis`** — Turns raw CSV output from test runs into actual statistics: confidence
  intervals, not just a single "it worked" number. This is what makes our results
  defensible to judges instead of "trust me, the chart looks good." Owned by Negar.

- **`/results`** — Where raw CSV data from real test runs lands. Gitignored (too large,
  regenerable) except for a placeholder so the folder exists in git.

- **`/docs`** — Architecture diagram, the evaluation protocol we're following, a log of
  which session produced which data, and the final report.

---

## The `.env` file — read this, this affects every session

`LLAMA_SERVER_URL` is the one place the AI server's network address lives. It is **not**
committed to git (security + it changes every session anyway). Every component (`/shield`,
`/loadgen`) reads this same variable — nobody hardcodes an IP into their own code.

**Why this matters practically:** we are not on a permanent network. Each working session,
whoever's laptop is hosting `llama-server` is on a different network (library WiFi, student
centre WiFi, wherever), so the IP address changes every time. Only Umar has Claude Code —
Syeda and Behzad don't need it for this step, they just open `.env` in a plain text editor
and paste in whatever the current host's IP is.

**Session-start checklist (do this before running anything):**
1. Whoever is hosting `llama-server` finds their laptop's local IP on the current network.
2. That IP gets said out loud / posted in the team chat.
3. Everyone else updates their own local `.env` file (`LLAMA_SERVER_URL=http://<that-ip>:8080`).
4. Only then does anyone run k6, the shield, or anything that talks to the server.

Skipping step 2/3 is the most likely reason a session "isn't working" — someone's still
pointed at last session's IP.

`LLAMA_SERVER_URL` isn't the only value that has to be kept in sync by hand across
files — see [docs/MANUAL_CONFIG.md](docs/MANUAL_CONFIG.md) for the full list (e.g.
`-np` vs. the Shield's slot count) before changing `-np` or tuning any threshold.

---

## Non-negotiables — do not cut these even under time pressure

- Load generation must be **open-loop** (k6 arrival-rate executors). Closed-loop generators
  silently slow down when the server struggles, which hides the exact overload we're trying
  to demonstrate ("coordinated omission").
- Always report `dropped_iterations` next to every latency number.
- Report percentiles (p50/p95/p99) and Max. **Never report standard deviation of latency**
  — it's statistically misleading for this kind of data.
- Always run a small, constant-rate "legitimate user" stream (the probe cohort) alongside
  attack traffic, and report whether it survives.
- Defense-off vs. defense-on runs must use the *identical* seeded traffic pattern, and must
  be interleaved (off, on, off, on...) — not run in two separate blocks — because laptops
  heat up and slow down under sustained load, and that would unfairly make "defense on"
  look better just because it happened to run when the laptop was cooler.

## The four load profiles (Profile D is our top differentiator — do not skip it)

- **A — Normal:** steady request rate, for baseline behavior.
- **B — Spike:** sudden ramp-up in rate.
- **C — Sustained flood:** high, constant rate for a long period.
- **D — Slow/low-rate, high-cost:** *few* requests per second, but each one is huge
  (maximum input + output tokens). This is the profile that **defeats a naive
  request-counting limiter** while our token-cost-aware Shield catches it — it's the single
  clearest proof that our approach is better than "just rate-limit requests." If this
  profile is missing from `/loadgen`, the project's main argument has no evidence behind it.

---

## Cut list, if we fall behind (cut in this order, don't reorder it)

1. Statistical anomaly detection (a 4th, optional defense) — highest risk of false
   positives, least credit from judges.
2. The optional paid GPU confirmation run — a nice-to-have footnote, not required.
3. Graceful degradation (shrinking response length instead of rejecting outright).
4. The anti-starvation "aging" part of the priority queue — fall back to a fixed
   reservation with no aging, and say so explicitly in the report.
5. Reduce repeated runs from 5 to 3 per test (keep the statistics, just wider intervals).

**Never cut:** open-loop load generation, `dropped_iterations` reporting, percentiles+Max,
the legitimate probe cohort, or the paired seeded on/off comparison. These five are what
make the whole project's results trustworthy instead of a demo.
