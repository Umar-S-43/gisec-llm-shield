# Shield: Reverse Proxy with Admission Control

FastAPI-based reverse proxy implementing:
- Token-bucket rate limiting / admission control
- Queue-aware load shedding (using `llamacpp:requests_deferred` and `/slots?fail_on_no_slot=1`)
- Priority-tiered fair queuing (legitimate probes vs. attack traffic)

## Exit Criterion

By end of workstream session:
- Reverse proxy listens on `http://localhost:9090`
- Reads `LLAMA_SERVER_URL` from environment (no hardcoded IPs)
- Implements token-bucket admission control with configurable bucket size/refill rate
- Forwards to llama-server; returns `503 Service Unavailable` or `429 Too Many Requests` when overloaded
- Supports priority headers or URL path differentiation for legitimate probes
- One-command launch with test

## One-Command Start

```bash
# Reads LLAMA_SERVER_URL from .env
python shield/main.py
```

Listens on `http://localhost:9090` by default.

## Configuration

Edit `shield/config.py` or pass environment variables:

```python
# Example in code or via env
SHIELD_PORT = 9090
TOKEN_BUCKET_CAPACITY = 10        # Max tokens in bucket
TOKEN_BUCKET_REFILL_RATE = 1.0    # Tokens per second
LLAMA_SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://localhost:8080")
```

## Testing the Proxy

```bash
# From repo root
python shield/main.py &  # Start in background

# Simple request (should succeed if queue is empty)
curl -X POST http://localhost:9090/completion \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Test", "n_predict": 10}'

# With priority header (legitimate probe)
curl -X POST http://localhost:9090/completion \
  -H "Content-Type: application/json" \
  -H "X-Priority: legitimate" \
  -d '{"prompt": "Test", "n_predict": 10}'
```

## Implementation Notes

- **Queue awareness:** Periodically poll `/slots?fail_on_no_slot=1` on llama-server to determine if new requests should be accepted or rejected.
- **Token bucket:** Token refill is continuous (not per-request).
- **Priority tiers:** Distinguish requests via headers (e.g., `X-Priority: legitimate`) to implement fair queuing; prioritize legitimate traffic when shedding is required.
- **No hardcoding:** Read `LLAMA_SERVER_URL` from environment; never hardcode `localhost:8080` or other IPs.

## Load Shedding Strategy

When the token bucket is depleted or llama-server reports no available slots:
1. Check request priority (header/path)
2. If legitimate: attempt to queue; if queue full, return `503`
3. If attack/unknown: return `429` immediately
4. Log rejected requests for analysis

## Dependencies

See `requirements.txt` in this directory; install with:
```bash
pip install -r shield/requirements.txt
```

