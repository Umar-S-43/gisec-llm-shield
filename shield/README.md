# Shield: Cost-Aware Reverse Proxy with Admission Control

FastAPI-based reverse proxy implementing four defense checks (see CLAUDE.md), applied
at runtime in this order — each check only runs once the previous one has already
confirmed the request should proceed, so nothing gets charged/reserved for a request
about to be rejected for a different reason:

**1. (B) Queue-aware load shedding** — polls `llamacpp:requests_deferred` from
llama-server's `/metrics` (cached, not per-request) and short-circuits with `503`
before the real server's queue backs up. Falls back to the authoritative
`/slots?fail_on_no_slot=1` check when the deferred count looks borderline.

**2. (C, concurrency layer) Fixed-fraction slot reservation** — caps how many
requests per tier may be **in-flight** (forwarded, awaiting response) at once. A
fraction of `TOTAL_LLAMA_SLOTS` (`LEGITIMATE_SLOT_FRACTION`, default 0.5) is reserved
exclusively for `X-Priority: legitimate` traffic; default-tier traffic is capped to
the remaining share and cannot use the reserved portion even when it's idle. This is
independent of the token buckets below — it gates *concurrency*, not *admission
rate/cost*. Returns `503 {"reason": "..._capacity_..."}` when a tier is full, without
touching either bucket.

Deliberately **not implemented**: wait-time aging (a long-waiting default-tier
request gradually earning priority). This is a stated cut per CLAUDE.md's cut list —
priority-inversion/aging for tiered admission is still open, unresolved work even in
mature schedulers (see vLLM's own RFCs #6077 and #16969). A fixed reservation with no
aging is the documented fallback, not an oversight.

**3. (A) Token-budget admission control**, which also carries **(C, admission
layer)** — rejects requests based on their *estimated cost* (prompt tokens +
requested output tokens), not just request count. This is what catches Profile D
(`/loadgen/profiles/profile-d.js`): few requests/sec, each one huge. Legitimate and
default traffic draw from separate cost budgets (the admission-time half of
priority-tiered fair queuing; slot reservation above is the concurrency-time half).
Only runs once (B) and slot reservation have already confirmed the request should
proceed.

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
| `TOTAL_LLAMA_SLOTS` | 1 | **Must match** `service/start.sh`'s `-np`/`NUM_PARALLEL`. Not auto-detected. |
| `LEGITIMATE_SLOT_FRACTION` | 0.5 | Fraction of `TOTAL_LLAMA_SLOTS` reserved for legitimate-tier in-flight requests |

Cost units are ~tokens: prompt word-count/0.75 + `n_predict`/`max_tokens` (defaults to
128 if unset). This is a cheap estimate on purpose — the whole point is to reject
expensive requests before paying for real tokenization or a round trip to llama-server.

## Dependencies

```bash
pip install -r shield/requirements.txt
```
