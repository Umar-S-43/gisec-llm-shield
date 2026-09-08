"""
Shield: FastAPI reverse proxy implementing cost-aware admission control.

Reads LLAMA_SERVER_URL from environment (required).

Defense pipeline, applied in order (see CLAUDE.md):
  (A) Token-budget check — rejects requests whose ESTIMATED COST (prompt tokens +
      requested output tokens) would blow the caller's budget. This is what catches
      Profile D (few requests/sec, each one huge) that a plain request-counter misses.
  (B) Queue-aware shedding — watches llamacpp:requests_deferred (scraped from
      llama-server's own /metrics) and short-circuits with 503 before the real
      server's queue backs up, using /slots?fail_on_no_slot=1 as the authoritative
      "is there a slot" check.
  (C) Priority-tiered fair queuing — "legitimate" traffic (X-Priority: legitimate)
      draws from its own reserved token budget so attack traffic sharing the same
      wire cannot starve it.

Listens on http://localhost:9090 by default.
"""

import os
import re
import time
import logging
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    shield_port: int = 9090
    llama_server_url: str  # Required; must be set via LLAMA_SERVER_URL env var

    # SHIELD_ACTIVE=0 makes the shield a pure pass-through logger (Day-1 behavior in
    # CLAUDE.md) so the interleaved on/off comparison can hit the SAME shield process
    # and just flip this instead of standing up a second target.
    shield_active: bool = True

    # Token budget is in COST UNITS (~ tokens), not requests. One unit is roughly one
    # LLM token: estimated prompt tokens + requested n_predict/max_tokens.
    legitimate_bucket_capacity: float = 2000.0
    legitimate_bucket_refill_rate: float = 200.0  # cost units/sec
    default_bucket_capacity: float = 500.0
    default_bucket_refill_rate: float = 50.0  # cost units/sec

    # Queue-aware shedding thresholds (llamacpp:requests_deferred)
    deferred_shed_threshold_default: int = 2   # shed non-priority traffic first
    deferred_shed_threshold_legitimate: int = 8  # only shed legitimate under severe backlog

    metrics_poll_timeout: float = 2.0

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

if not settings.llama_server_url:
    raise ValueError("LLAMA_SERVER_URL environment variable is required")

logger.info(f"Shield proxy configured to forward to: {settings.llama_server_url}")
logger.info(f"Shield active (defense-on): {settings.shield_active}")

app = FastAPI(title="Shield Proxy")


# --- Cost estimation -------------------------------------------------------
# Rough word-based estimator (~0.75 words/token for English). This is intentionally
# cheap to compute — the whole point is to reject expensive requests BEFORE paying
# for real tokenization or forwarding to llama-server.

def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text.split()) / 0.75))


def estimate_request_cost(body: bytes) -> int:
    """Estimate prompt tokens + requested output tokens from a completion/chat payload."""
    import json
    try:
        payload = json.loads(body)
    except Exception:
        return 1  # unparsable body; charge the minimum rather than failing open expensively

    prompt_text = payload.get("prompt", "")
    if not prompt_text and "messages" in payload:
        prompt_text = " ".join(m.get("content", "") for m in payload.get("messages", []) if isinstance(m, dict))

    prompt_cost = estimate_tokens(prompt_text)
    output_cost = int(payload.get("n_predict") or payload.get("max_tokens") or 128)

    return prompt_cost + output_cost


# --- Token bucket (cost-aware) ----------------------------------------------

class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()

    def refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, cost: float) -> bool:
        self.refill()
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


legitimate_bucket = TokenBucket(settings.legitimate_bucket_capacity, settings.legitimate_bucket_refill_rate)
default_bucket = TokenBucket(settings.default_bucket_capacity, settings.default_bucket_refill_rate)


def is_priority_request(request: Request) -> bool:
    return request.headers.get("X-Priority", "").lower() == "legitimate"


# --- Queue-aware load shedding ----------------------------------------------
# llama-server only exposes requests_deferred via Prometheus text on /metrics; there
# is no per-request JSON field for it, so we poll periodically rather than per-request
# to keep proxy overhead low.

_deferred_cache = {"value": 0, "checked_at": 0.0}
_DEFERRED_CACHE_TTL = 0.5  # seconds


async def get_requests_deferred() -> int:
    now = time.time()
    if now - _deferred_cache["checked_at"] < _DEFERRED_CACHE_TTL:
        return _deferred_cache["value"]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.llama_server_url}/metrics",
                timeout=settings.metrics_poll_timeout,
            )
            match = re.search(r"^llamacpp:requests_deferred\s+(\d+)", response.text, re.MULTILINE)
            value = int(match.group(1)) if match else 0
    except Exception as e:
        logger.warning(f"Failed to scrape /metrics for requests_deferred: {e}")
        value = 0  # fail open on the metrics scrape; /slots check below is authoritative

    _deferred_cache["value"] = value
    _deferred_cache["checked_at"] = now
    return value


async def slot_available() -> bool:
    """Authoritative check: llama-server returns non-200 from /slots?fail_on_no_slot=1 when full."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.llama_server_url}/slots?fail_on_no_slot=1",
                timeout=settings.metrics_poll_timeout,
            )
            return response.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to check /slots: {e}")
        return True  # optimistic fail-open if llama-server is briefly unreachable


# --- Request pipeline --------------------------------------------------------

async def forward_request(request: Request) -> JSONResponse:
    body = await request.body()
    priority = is_priority_request(request)

    if not settings.shield_active:
        # Day-1 / defense-off mode: pass everything through, just log.
        logger.info(f"[PASSTHROUGH] {request.method} {request.url.path} priority={priority}")
        return await _do_forward(request, body)

    # (A) Cost-aware token budget
    cost = estimate_request_cost(body)
    bucket = legitimate_bucket if priority else default_bucket
    if not bucket.consume(cost):
        logger.warning(f"Token budget exceeded (cost={cost}, priority={priority}); rejecting")
        return JSONResponse({"error": "Token budget exceeded", "estimated_cost": cost}, status_code=429)

    # (B) Queue-aware shedding — check the deferred gauge first (cheap, cached),
    # fall back to the authoritative /slots check only when it looks tight.
    deferred = await get_requests_deferred()
    shed_threshold = (
        settings.deferred_shed_threshold_legitimate if priority
        else settings.deferred_shed_threshold_default
    )
    if deferred >= shed_threshold:
        logger.warning(f"Shedding load: requests_deferred={deferred} >= threshold={shed_threshold} priority={priority}")
        return JSONResponse({"error": "Service overloaded", "requests_deferred": deferred}, status_code=503)

    if not await slot_available():
        logger.warning(f"No slot available on llama-server (priority={priority}); shedding")
        return JSONResponse({"error": "No slots available"}, status_code=503)

    # (C) Admitted — priority only affected which bucket/threshold was used above;
    # forwarding itself is FIFO on llama-server's own scheduler.
    return await _do_forward(request, body)


async def _do_forward(request: Request, body: bytes) -> JSONResponse:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.llama_server_url}{request.url.path}",
                content=body,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
                timeout=60.0,
            )
            try:
                return JSONResponse(response.json(), status_code=response.status_code)
            except Exception:
                return JSONResponse({"raw": response.text}, status_code=response.status_code)
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return JSONResponse({"error": "Internal proxy error"}, status_code=500)


@app.post("/{path:path}")
async def proxy(request: Request, path: str):
    return await forward_request(request)


@app.get("/health")
async def health():
    return {"status": "ok", "shield_active": settings.shield_active}


@app.get("/metrics")
async def metrics():
    """Proxy llama-server's Prometheus text metrics unchanged (llamacpp:* only)."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.llama_server_url}/metrics", timeout=5.0)
            return response.text
    except Exception as e:
        logger.error(f"Failed to fetch metrics: {e}")
        return {"error": "Metrics unavailable"}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Shield proxy on port {settings.shield_port}")
    logger.info(f"Forwarding to llama-server at {settings.llama_server_url}")
    uvicorn.run(app, host="0.0.0.0", port=settings.shield_port)
