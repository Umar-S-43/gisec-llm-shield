# Shield: Cost-Aware Reverse Proxy with Admission Control

FastAPI-based reverse proxy implementing four defense checks (see CLAUDE.md), applied
at runtime in this order: **A → C → B** (changed 2026-09-11; was B → C → A).

**1. (A) Token-budget admission control** — checked first, so every request's cost is
judged before any capacity/queue concern, matching the project's core thesis (price
the request, not just the slot) as directly as possible. Rejects requests based on
their *estimated cost* (prompt tokens + requested output tokens), not just request
count. This is what catches Profile D (`/loadgen/profiles/profile-d.js`): few
requests/sec, each one huge. Legitimate and default traffic draw from separate cost
budgets.

**Bucket deduction is immediate on success (`consume()`), not deferred** — necessary
because on an async event loop many requests can be mid-pipeline at once, and a
peek-only check would let two concurrent requests each see enough budget for
themselves while jointly overspending it (a time-of-check-to-time-of-use race).
Every downstream rejection point in C and B below calls `bucket.refund(cost)`, so
the bucket is only ever actually spent, net, on requests that make it all the way
to `llama-server` — a request shed later doesn't lose its budget permanently.

**2. (C, concurrency layer) Two independent fairness checks, both must pass:**

- **Fixed-fraction slot reservation** — caps how many requests per *tier* may be
  **in-flight** at once. A fraction of `TOTAL_LLAMA_SLOTS` (`LEGITIMATE_SLOT_FRACTION`,
  default 0.5) is reserved exclusively for `X-Priority: legitimate` traffic;
  default-tier traffic is capped to the remaining share and cannot use the reserved
  portion even when it's idle.
- **Per-identity concurrency cap** (added 2026-09-11, `PER_IDENTITY_CONCURRENCY_CAP`,
  default 2) — caps how many in-flight requests a single *source IP* may have, full
  stop, regardless of claimed tier. Added after a live test set `LEGITIMATE_SLOT_FRACTION=1.0`
  (simulating an attacker who holds many accounts that all legitimately carry
  `X-Priority: legitimate`) and confirmed the tier check above provides **zero**
  protection in that case — every rejection came from raw concurrency exhaustion,
  not the tier check, because there was no "default" tier left to separate anyone
  from. This check trusts no claimed identity at all, so an attacker now needs many
  distinct *IPs* in addition to many accounts to get the same effect — raising the
  cost of the attack on a second, independent axis.
  **Known limitation, stated explicitly:** source IP is a practical stand-in for
  "identity" since this prototype has no real per-user API key system. Reasonable
  for a single-machine attacker (what this project's load tests actually simulate),
  but does not fully solve a genuinely distributed attacker with many real IPs
  (botnet, rented proxy pool, many cloud VMs) — that needs additional layers
  (per-account keys, an upstream CDN/edge DDoS layer) a single reverse-proxy Shield
  can't provide alone.

Both checks are independent of the token buckets above — they gate *concurrency*,
not *admission rate/cost*. Either one returns `503` when tripped, without touching
either bucket beyond the refund already described.

Deliberately **not implemented**: wait-time aging (a long-waiting default-tier
request gradually earning priority). This is a stated cut per CLAUDE.md's cut list —
priority-inversion/aging for tiered admission is still open, unresolved work even in
mature schedulers (see vLLM's own RFCs #6077 and #16969). A fixed reservation with no
aging is the documented fallback, not an oversight.

**3. (B) Queue-aware load shedding** — checked last now. Polls
`llamacpp:requests_deferred` from llama-server's `/metrics` (cached, not per-request)
and short-circuits with `503` before the real server's queue backs up. Falls back to
the authoritative `/slots?fail_on_no_slot=1` check when the deferred count looks
borderline.

**4. Forward + reconcile** — admitted requests are forwarded, then estimate-vs-actual
is logged (see below).

`⚠️ TOTAL_LLAMA_SLOTS` **must be kept in sync by hand** with whatever `-np` value
`service/start.sh` actually passes to llama-server — the Shield has no way to read
llama-server's real `-np` at runtime. Get it wrong and slot reservation silently
over- or under-reserves; there's no error, it just stops doing what it's for. The
Shield logs a warning at startup if this is left at its default.

## Exit Criterion

- Reverse proxy listens on `http://localhost:9090` (configurable via `SHIELD_PORT`)
- Reads `LLAMA_SERVER_URL` from environment (no hardcoded IPs)
- `SHIELD_ACTIVE=false` flips it to pure pass-through logging (Day-1 behavior)
- Returns `429` (token budget exceeded) or `503` (queue/slots full) when shedding
- One-command launch with test

## One-Command Start

```bash
# Reads LLAMA_SERVER_URL (and optional SHIELD_PORT, SHIELD_ACTIVE) from .env
python shield/main.py
```

Listens on `http://localhost:9090` by default.

**To watch it live in a browser instead of a terminal:**

```bash
python shield/dashboard_server.py
# then open http://localhost:8765 (also reachable from other machines on the
# hotspot at this machine's IP:8765)
```

Runs on a separate port (8765) alongside the Shield's own 9090. Shows live
health/queue-depth, cumulative counts of every defense that's fired since the
Shield started, a colorized log tail, and a Final Report section at the
bottom (success rate with a Wilson 90% CI, defense-firing breakdown, and cost
estimate accuracy if a reconciliation CSV exists) — with a "Snapshot" button
to freeze it at a point in time instead of it continuing to update live.

**For live test sessions, prefer the auto-restarting wrapper instead:**

```bash
./shield/run_resilient.sh
# or, if your default `python` doesn't have shield/requirements.txt installed:
PYTHON_BIN="py -3.11" ./shield/run_resilient.sh
```

Added 2026-09-11 after the Shield crashed mid-session with `OSError: [WinError
64] The specified network name is no longer available` — a Windows-level
socket-accept failure, most likely a momentary phone-hotspot drop (see
CLAUDE.md's "ephemeral connectivity" section), not a code bug. Nobody was
watching the terminal when it happened, so it sat dead for a while before
anyone noticed. The wrapper just restarts `shield/main.py` a couple seconds
after it exits, so a network blip costs seconds of downtime instead of an
unnoticed dead Shield for the rest of a run. It is **not** a fix for a real
crash-causing bug in our own code — if you see the *same* traceback repeating
on every restart, that's a bug, not a network blip; stop and read it.

## Testing the Proxy

```bash
python shield/main.py &

# Small legitimate request — should be admitted
curl -X POST http://localhost:9090/completion \
  -H "Content-Type: application/json" \
  -H "X-Priority: legitimate" \
  -d '{"prompt": "Test", "n_predict": 10}'

# Huge, low-priority request (Profile D shape) — should be rejected on cost (429)
# even though it's a single request, not a flood.
curl -X POST http://localhost:9090/completion \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"$(python -c 'print("word " * 2000)')\", \"n_predict\": 1024}"
```

## Configuration (env vars, see `.env.example`)

| Variable | Default | Meaning |
|---|---|---|
| `LLAMA_SERVER_URL` | *(required)* | Where to forward admitted requests |
| `SHIELD_PORT` | 9090 | Port the Shield listens on |
| `SHIELD_ACTIVE` | true | `false` = pass-through logging only, no blocking |
| `LEGITIMATE_BUCKET_CAPACITY` / `LEGITIMATE_BUCKET_REFILL_RATE` | 2000 / 200 | Cost-unit budget for `X-Priority: legitimate` traffic |
| `DEFAULT_BUCKET_CAPACITY` / `DEFAULT_BUCKET_REFILL_RATE` | 500 / 50 | Cost-unit budget for everything else |
| `DEFERRED_SHED_THRESHOLD_DEFAULT` / `_LEGITIMATE` | 2 / 8 | `llamacpp:requests_deferred` shedding thresholds |
| `TOTAL_LLAMA_SLOTS` | 4 | **Must match** `service/start.sh`'s `-np`/`NUM_PARALLEL`. Not auto-detected. |
| `LEGITIMATE_SLOT_FRACTION` | 0.5 | Fraction of `TOTAL_LLAMA_SLOTS` reserved for legitimate-tier in-flight requests |
| `PER_IDENTITY_CONCURRENCY_CAP` | 2 | Max in-flight requests per source IP, regardless of claimed tier — see known limitation above |
| `SLOT_CHECK_TTL` | 0.5 | Cache TTL (seconds) for the `/slots` availability check — see `docs/MANUAL_CONFIG.md`. Performance fix, **unverified** as of introduction; tune once real rerun data exists. |

Cost units are ~tokens: prompt word-count/0.75 + `n_predict`/`max_tokens` (defaults to
128 if unset). This is a cheap estimate on purpose — the whole point is to reject
expensive requests before paying for real tokenization or a round trip to llama-server.

## Dependencies

```bash
pip install -r shield/requirements.txt
```
