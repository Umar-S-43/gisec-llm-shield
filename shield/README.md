# Shield: Cost-Aware Reverse Proxy with Admission Control

FastAPI-based reverse proxy implementing, in order (see CLAUDE.md):

**(A) Token-budget admission control** — rejects requests based on their *estimated
cost* (prompt tokens + requested output tokens), not just request count. This is what
catches Profile D (`/loadgen/profiles/profile-d.js`): few requests/sec, each one huge.
Legitimate and non-priority traffic draw from separate cost budgets so one can't starve
the other.

**(B) Queue-aware load shedding** — polls `llamacpp:requests_deferred` from
llama-server's `/metrics` (cached, not per-request) and short-circuits with `503`
before the real server's queue backs up. Falls back to the authoritative
`/slots?fail_on_no_slot=1` check when the deferred count looks borderline.

**(C) Priority-tiered fair queuing** — `X-Priority: legitimate` traffic gets its own,
larger token budget and a higher shedding threshold, so attack traffic sharing the
wire cannot starve it.

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

Cost units are ~tokens: prompt word-count/0.75 + `n_predict`/`max_tokens` (defaults to
128 if unset). This is a cheap estimate on purpose — the whole point is to reject
expensive requests before paying for real tokenization or a round trip to llama-server.

## Dependencies

```bash
pip install -r shield/requirements.txt
```
