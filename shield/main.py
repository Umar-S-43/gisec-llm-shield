"""
Shield: FastAPI reverse proxy with admission control and load shedding.

Reads LLAMA_SERVER_URL from environment (required).
Implements token-bucket rate limiting and queue-aware load shedding.
Listens on http://localhost:9090 by default.
"""

import os
import time
import logging
import httpx
from typing import Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    shield_port: int = 9090
    llama_server_url: str  # Required; must be set via LLAMA_SERVER_URL env var
    token_bucket_capacity: float = 10.0
    token_bucket_refill_rate: float = 1.0  # tokens per second

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()

if not settings.llama_server_url:
    raise ValueError("LLAMA_SERVER_URL environment variable is required")

logger.info(f"Shield proxy configured to forward to: {settings.llama_server_url}")

app = FastAPI(title="Shield Proxy")

class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.tokens = capacity
        self.last_refill = time.time()

    def refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: float = 1.0) -> bool:
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

bucket = TokenBucket(settings.token_bucket_capacity, settings.token_bucket_refill_rate)

async def check_llama_queue() -> bool:
    """Check if llama-server has available slots."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.llama_server_url}/slots?fail_on_no_slot=1",
                timeout=2.0
            )
            # If /slots returns 200, slots are available
            return response.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to check llama slots: {e}")
        # Assume slots available on error (optimistic)
        return True

def is_priority_request(request: Request) -> bool:
    """Check if request should be prioritized (e.g., legitimate probe)."""
    priority_header = request.headers.get("X-Priority", "").lower()
    return priority_header == "legitimate"

async def forward_request(request: Request) -> JSONResponse:
    """Forward request to llama-server; handle errors."""
    try:
        body = await request.body()

        # Check token bucket
        if not bucket.consume(1.0):
            if is_priority_request(request):
                logger.warning("Token bucket depleted; rejecting attack traffic")
            return JSONResponse(
                {"error": "Rate limit exceeded"},
                status_code=429
            )

        # Check llama-server queue
        slots_available = await check_llama_queue()
        if not slots_available:
            logger.warning("No slots available on llama-server; shedding load")
            return JSONResponse(
                {"error": "Service overloaded"},
                status_code=503
            )

        # Forward to llama-server
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.llama_server_url}{request.url.path}",
                content=body,
                headers=dict(request.headers),
                timeout=60.0
            )
            return JSONResponse(
                response.json(),
                status_code=response.status_code
            )

    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return JSONResponse(
            {"error": "Internal proxy error"},
            status_code=500
        )

@app.post("/{path:path}")
async def proxy(request: Request, path: str):
    """Proxy POST requests (completion, chat, etc.) to llama-server."""
    return await forward_request(request)

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}

@app.get("/metrics")
async def metrics():
    """Proxy Prometheus metrics from llama-server."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.llama_server_url}/metrics",
                timeout=5.0
            )
            return response.text
    except Exception as e:
        logger.error(f"Failed to fetch metrics: {e}")
        return {"error": "Metrics unavailable"}

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Shield proxy on port {settings.shield_port}")
    logger.info(f"Forwarding to llama-server at {settings.llama_server_url}")
    uvicorn.run(app, host="0.0.0.0", port=settings.shield_port)
