"""
Shield: FastAPI reverse proxy implementing cost-aware admission control.

Reads LLAMA_SERVER_URL from environment (required).

Defense mechanisms (see CLAUDE.md), applied at RUNTIME in this order — each check
runs only after the previous one has already confirmed the request should proceed,
so nothing gets charged/reserved for a request that's about to be rejected for a
different reason anyway:

  1. (B) Queue-aware shedding — watches llamacpp:requests_deferred (scraped from
     llama-server's own /metrics) and short-circuits with 503 before the real
     server's queue backs up, using /slots?fail_on_no_slot=1 as the authoritative
     "is there a slot" check.
  2. (C, concurrency layer) Fixed-fraction slot reservation — caps how many
     requests per TIER may be in-flight (forwarded, awaiting response) at once,
     independent of the token buckets below. Reserves a fraction of
     TOTAL_LLAMA_SLOTS exclusively for legitimate-tier traffic so attack traffic
     cannot fill every slot even if it has token budget left to spend.
  3. (A) Token-budget check, which also carries (C, admission layer) — rejects
     requests whose ESTIMATED COST (prompt tokens + requested output tokens) would
     blow the caller's budget. Legitimate and default traffic draw from separate
     token buckets (the admission-time half of priority-tiered fair queuing; the
     slot reservation above is the concurrency-time half). This budget check is
     what catches Profile D (few requests/sec, each one huge) that a plain
     request-counter misses.
  4. Forward to llama-server, then reconcile estimate vs. actual (admitted
     requests only).

Deliberately NOT implemented: wait-time aging for the reserved-slot queue (i.e. a
long-waiting default-tier request gradually earning priority). This is a stated cut
per CLAUDE.md's cut list, not an oversight — priority-inversion/aging for exactly
this kind of tiered admission is still open, unresolved work even in mature
production schedulers (see vLLM's own RFCs #6077 and #16969 wrestling with the same
problem). A fixed reservation with no aging is the documented fallback.

Listens on http://localhost:9090 by default.
"""

import re
import csv
import math
import time
import logging
import httpx
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    # What to charge when n_predict/max_tokens is MISSING or set to llama.cpp's
    # "unbounded" sentinel (-1, or any non-positive value). Charging a cheap flat
    # default here (the old behavior charged 128 unconditionally) would let exactly
    # the "long output / decode pressure" attack the project exists to catch (see
    # CLAUDE.md, research_brief_corrected.md's arXiv:2410.10760 discussion) through
    # the token budget for free — the request can generate until it hits the
    # server's own context limit while being billed as if it asked for 128 tokens.
    # Charge the worst case instead: the per-slot context budget, so an unbounded
    # request is billed as expensively as its actual worst-case cost.
    unbounded_output_cost_estimate: int = 2048

    # Queue-aware shedding thresholds (llamacpp:requests_deferred)
    deferred_shed_threshold_default: int = 2   # shed non-priority traffic first
    deferred_shed_threshold_legitimate: int = 8  # only shed legitimate under severe backlog

    # Fixed-fraction slot reservation (concurrency layer of priority-tiered fair
    # queuing — see module docstring). total_llama_slots MUST equal whatever -np
    # value service/start.sh actually passes to llama-server. The Shield has no
    # way to read llama-server's real -np at runtime (it isn't exposed anywhere),
    # so THIS HAS TO BE KEPT IN SYNC MANUALLY across the two files/processes. Get
    # it wrong and this defense silently either over-reserves (starves legitimate
    # traffic's own headroom) or under-reserves (lets attack traffic fill slots
    # this was supposed to protect) — it will not error, it will just not work.
    total_llama_slots: int = 4  # matches service/start.sh's own NUM_PARALLEL default
    legitimate_slot_fraction: float = 0.5  # fraction of total_llama_slots reserved for legitimate tier

    metrics_poll_timeout: float = 2.0

    # Must be >= the slowest legitimate generation any loadgen profile allows for,
    # or the Shield kills and reports a proxy error on a request that would have
    # succeeded given more time — looks like a Shield bug in results, but is really
    # just a timeout mismatch. profile-d.js's k6 client waits up to 120s; matched
    # here. See docs/MANUAL_CONFIG.md.
    forward_timeout_seconds: float = 120.0

    # extra="ignore": .env is a SHARED file (CLAUDE.md — "every component reads this
    # same variable"), so it legitimately holds vars meant for other components
    # (SHIELD_URL for loadgen, LLAMA_SERVER_HOST/MODEL_PATH/NUM_PARALLEL for
    # service/start.sh, etc.) that aren't Settings fields here. pydantic-settings
    # defaults to rejecting unknown vars, which crashed the Shield at startup on
    # any .env containing them — not a hypothetical, this is the exact shape of
    # .env.example. Modernized from the deprecated class-based Config to
    # model_config while fixing this.
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()

if not settings.llama_server_url:
    raise ValueError("LLAMA_SERVER_URL environment variable is required")

logger.info(f"Shield proxy configured to forward to: {settings.llama_server_url}")
logger.info(f"Shield active (defense-on): {settings.shield_active}")

# Mutable at runtime via POST /admin/shield-active — see that endpoint's docstring
# for why. settings.shield_active above remains the STARTUP default only; this is
# what forward_request() and /health actually consult from here on.
_shield_active = settings.shield_active

if "total_llama_slots" not in settings.model_fields_set:
    # model_fields_set (not os.environ) — pydantic-settings loads TOTAL_LLAMA_SLOTS
    # from .env via its own dotenv parsing, which never touches os.environ, so
    # checking os.environ here used to warn "not set" even when .env correctly set
    # it. model_fields_set reflects every source (.env, real env var, init kwarg).
    logger.warning(
        f"TOTAL_LLAMA_SLOTS not set — using default {settings.total_llama_slots}. "
        f"This MUST match the -np value service/start.sh passes to llama-server, "
        f"and the Shield cannot verify this at runtime. If they drift, slot "
        f"reservation (Defense C, concurrency layer) will silently do the wrong "
        f"thing — either starving legitimate traffic or leaving attack traffic free "
        f"to fill every slot — with no error to indicate it."
    )

# Computed once at startup, not per-request: how many of total_llama_slots are
# reserved exclusively for legitimate-tier in-flight requests.
_reserved_for_legitimate = math.ceil(settings.total_llama_slots * settings.legitimate_slot_fraction)
_default_slot_capacity = settings.total_llama_slots - _reserved_for_legitimate
logger.info(
    f"Slot reservation: total={settings.total_llama_slots}, "
    f"reserved_for_legitimate={_reserved_for_legitimate}, default_capacity={_default_slot_capacity}"
)
if _default_slot_capacity <= 0:
    # Not a misconfiguration by itself (total_llama_slots=1 legitimately has nowhere
    # else to put the reservation), but it silently means EVERY default-tier request
    # gets a 503 at the slot-reservation check before its cost is ever estimated —
    # the token budget below never runs for default traffic. That would make a
    # Profile D run "look like" a token-cost win when it's actually just a blanket
    # block. Loud warning so this doesn't get discovered after a load test.
    logger.warning(
        f"default_slot_capacity={_default_slot_capacity} <= 0: ALL default-tier "
        f"(non-legitimate) requests will be rejected by slot reservation alone, "
        f"before the token budget ever runs. This is expected only if you intend "
        f"to test 'no capacity at all for unprivileged traffic' as its own scenario. "
        f"To let the token-budget defense (A) actually be exercised, raise "
        f"TOTAL_LLAMA_SLOTS or lower LEGITIMATE_SLOT_FRACTION."
    )

# In-flight counters (requests forwarded to llama-server, response not yet returned).
# Plain dict, not a class/lock: asyncio is single-threaded/cooperative and these are
# only ever mutated by non-yielding `+= 1` / `-= 1` statements, so there's no
# interleaving hazard between the increment, the check, and the decrement.
_in_flight = {"legitimate": 0, "default": 0}

app = FastAPI(title="Shield Proxy")


# --- Cost estimation -------------------------------------------------------
# Rough word-based estimator (~0.75 words/token for English). This is intentionally
# cheap to compute — the whole point is to reject expensive requests BEFORE paying
# for real tokenization or forwarding to llama-server.

def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text.split()) / 0.75))


def estimate_request_cost(body: bytes) -> tuple[int, int]:
    """Estimate (prompt_cost, output_cost) from a completion/chat payload, in cost units."""
    import json
    try:
        payload = json.loads(body)
    except Exception:
        return (1, 0)  # unparsable body; charge the minimum rather than failing open expensively

    prompt_text = payload.get("prompt", "")
    if not prompt_text and "messages" in payload:
        prompt_text = " ".join(m.get("content", "") for m in payload.get("messages", []) if isinstance(m, dict))

    prompt_cost = estimate_tokens(prompt_text)

    # n_predict/max_tokens: missing, or <=0, means "unbounded" to llama.cpp (its own
    # -1 default means generate until context/EOS). Bill the worst case rather than
    # a flat guess — see Settings.unbounded_output_cost_estimate for why. NOTE: the
    # old `payload.get("n_predict") or payload.get("max_tokens") or 128` here used
    # to be actively wrong in the dangerous direction: n_predict=-1 is truthy in
    # Python, so it evaluated to -1 and REDUCED total_estimated_cost below the
    # prompt-only cost — an unbounded-output request billed for less than a short
    # one. Explicit None/<=0 checks below fix that.
    requested_output = payload.get("n_predict")
    if requested_output is None:
        requested_output = payload.get("max_tokens")
    try:
        requested_output = int(requested_output) if requested_output is not None else None
    except (TypeError, ValueError):
        requested_output = None
    if requested_output is None or requested_output <= 0:
        output_cost = settings.unbounded_output_cost_estimate
    else:
        output_cost = requested_output

    return (prompt_cost, output_cost)


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


# --- Estimate-vs-actual reconciliation (log-only, no bucket feedback) ------
# One CSV per Shield process start, session-tagged the same way the rest of the
# repo tags run output (results/<thing>_<timestamp>.csv). This is a diagnostic
# log for building an error-distribution report later — it deliberately does NOT
# feed back into the token bucket (no retroactive refund/charge), so it can't
# change admission behavior mid-run and bias a comparison.

_RECONCILIATION_CSV_PATH = Path("results") / f"shield_reconciliation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
_RECONCILIATION_HEADERS = [
    "timestamp", "priority",
    "prompt_tokens_estimated", "output_tokens_estimated", "total_estimated",
    "prompt_tokens_actual", "completion_tokens_actual", "total_actual",
    "signed_error", "relative_error_pct",
]


def _log_reconciliation(priority: bool, prompt_cost: int, output_cost: int, response_json) -> None:
    """
    Compare estimated cost against llama-server's reported token counts for an
    ADMITTED request. Log-only: never adjusts the token bucket.

    llama-server's NATIVE /completion endpoint (what every current loadgen script
    calls) does not return an OpenAI-style `usage` object — confirmed from
    llama.cpp's own /completion example response. It instead returns, at the
    top level: `tokens_evaluated` (prompt tokens actually processed) and
    `tokens_predicted` (output tokens actually generated). Those are what we read
    here. The CSV columns are still named prompt_tokens_actual/
    completion_tokens_actual for consistency with the analysis scripts — that's a
    presentation rename only, not a claim that llama-server calls them that.

    If this code is ever pointed at the OpenAI-compatible endpoints
    (/v1/completions, /v1/chat/completions) instead, it will need a `usage` branch
    added back — those endpoints use the OpenAI shape, not this one.
    """
    if not isinstance(response_json, dict):
        logger.warning("Reconciliation skipped: response body was not JSON (streaming response or non-JSON error body?)")
        return

    if "tokens_evaluated" not in response_json or "tokens_predicted" not in response_json:
        logger.warning(
            "Reconciliation skipped: response JSON had no usable 'tokens_evaluated'/'tokens_predicted'. "
            "See _log_reconciliation docstring — expected on llama-server's native /completion endpoint."
        )
        return

    prompt_actual = response_json["tokens_evaluated"]
    completion_actual = response_json["tokens_predicted"]
    total_estimated = prompt_cost + output_cost
    total_actual = prompt_actual + completion_actual
    signed_error = total_actual - total_estimated
    relative_error_pct = (signed_error / total_estimated * 100) if total_estimated else None

    is_new_file = not _RECONCILIATION_CSV_PATH.exists()
    _RECONCILIATION_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RECONCILIATION_CSV_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new_file:
            writer.writerow(_RECONCILIATION_HEADERS)
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            "legitimate" if priority else "default",
            prompt_cost, output_cost, total_estimated,
            prompt_actual, completion_actual, total_actual,
            signed_error, f"{relative_error_pct:.2f}" if relative_error_pct is not None else "",
        ])


# --- Request pipeline --------------------------------------------------------

async def forward_request(request: Request) -> JSONResponse:
    body = await request.body()
    priority = is_priority_request(request)

    if not _shield_active:
        # Day-1 / defense-off mode, OR toggled off at runtime for the interleaved
        # on/off comparison (see /admin/shield-active): pass everything through,
        # just log. No cost was estimated for this request, so there is nothing to
        # reconcile against.
        logger.info(f"[PASSTHROUGH] {request.method} {request.url.path} priority={priority}")
        return await _do_forward(request, body)

    # (B) Queue-aware shedding runs BEFORE the token budget so a request that gets
    # shed here never touches the bucket — otherwise it's charged for a request
    # that never reaches llama-server, draining the budget faster than it should
    # and skewing probe-cohort survival numbers under sustained load. Check the
    # deferred gauge first (cheap, cached), fall back to the authoritative /slots
    # check only when it looks tight.
    deferred = await get_requests_deferred()
    shed_threshold = (
        settings.deferred_shed_threshold_legitimate if priority
        else settings.deferred_shed_threshold_default
    )
    if deferred >= shed_threshold:
        # Rejected before reaching llama-server — nothing to reconcile, same as above.
        logger.warning(f"Shedding load: requests_deferred={deferred} >= threshold={shed_threshold} priority={priority}")
        return JSONResponse({"error": "Service overloaded", "requests_deferred": deferred}, status_code=503)

    if not await slot_available():
        # Rejected before reaching llama-server — nothing to reconcile, same as above.
        logger.warning(f"No slot available on llama-server (priority={priority}); shedding")
        return JSONResponse({"error": "No slots available"}, status_code=503)

    # (C, concurrency layer) Fixed-fraction slot reservation. Checked before the
    # token budget for the same reason as everything else in this pipeline: don't
    # charge a request that's about to be rejected for a different reason. Neither
    # bucket is touched here — this only reads/writes _in_flight counters.
    #
    # NOTE: no wait-time aging — see module docstring for why that's a deliberate
    # cut, not an oversight.
    if priority:
        # Legitimate traffic may use the full pool, including the share default
        # traffic is capped away from.
        if _in_flight["legitimate"] >= settings.total_llama_slots:
            logger.warning(
                f"Slot reservation: legitimate_in_flight={_in_flight['legitimate']} "
                f">= total_llama_slots={settings.total_llama_slots}; shedding"
            )
            return JSONResponse(
                {"error": "Tier capacity reserved", "reason": "legitimate_in_flight_at_total_capacity"},
                status_code=503,
            )
    else:
        # Default traffic is capped to its non-reserved share and cannot eat into
        # the portion reserved for legitimate traffic, even if that portion is idle.
        if _in_flight["default"] >= _default_slot_capacity:
            logger.warning(
                f"Slot reservation: default_in_flight={_in_flight['default']} "
                f">= default_capacity={_default_slot_capacity} "
                f"(reserved_for_legitimate={_reserved_for_legitimate}); shedding"
            )
            return JSONResponse(
                {"error": "Tier capacity reserved", "reason": "default_tier_capacity_exhausted"},
                status_code=503,
            )

    # (A) Cost-aware token budget — only reached once queue-shedding AND slot
    # reservation have already confirmed this request should proceed, so a shed
    # or capacity-rejected request never touches the bucket.
    prompt_cost, output_cost = estimate_request_cost(body)
    cost = prompt_cost + output_cost
    bucket = legitimate_bucket if priority else default_bucket
    if not bucket.consume(cost):
        # Rejected requests (429/503) never reach llama-server, so there's nothing
        # to reconcile an estimate against — this is intentional, not a gap.
        logger.warning(f"Token budget exceeded (cost={cost}, priority={priority}); rejecting")
        return JSONResponse({"error": "Token budget exceeded", "estimated_cost": cost}, status_code=429)

    # Admitted — forward, tracking in-flight count for the slot-reservation check
    # above. Incremented right before the call, decremented in `finally` so the
    # count can never leak upward whether the forward succeeds, errors internally
    # (caught inside _do_forward), or raises unexpectedly.
    tier_key = "legitimate" if priority else "default"
    _in_flight[tier_key] += 1
    try:
        return await _do_forward(request, body, reconcile=(prompt_cost, output_cost), priority=priority)
    finally:
        _in_flight[tier_key] -= 1


async def _do_forward(
    request: Request,
    body: bytes,
    reconcile: tuple[int, int] | None = None,
    priority: bool = False,
) -> JSONResponse:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.llama_server_url}{request.url.path}",
                content=body,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
                timeout=settings.forward_timeout_seconds,
            )
            try:
                parsed = response.json()
            except Exception:
                # Non-JSON body — e.g. a streaming (SSE) response, if one is ever sent.
                # No loadgen script sends stream:true today, so this path is untested;
                # flagging rather than silently coercing it into something reconcilable.
                if reconcile is not None:
                    _log_reconciliation(priority, reconcile[0], reconcile[1], None)
                return JSONResponse({"raw": response.text}, status_code=response.status_code)

            if reconcile is not None and response.status_code == 200:
                _log_reconciliation(priority, reconcile[0], reconcile[1], parsed)

            return JSONResponse(parsed, status_code=response.status_code)
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return JSONResponse({"error": "Internal proxy error"}, status_code=500)


@app.get("/admin/shield-active")
async def get_shield_active():
    return {"shield_active": _shield_active}


@app.post("/admin/shield-active")
async def set_shield_active(request: Request):
    """
    Runtime toggle for the interleaved defense-off/defense-on comparison
    (loadgen/run_comparison.sh). SHIELD_ACTIVE at startup only sets the initial
    value — this is what actually lets both legs of the comparison hit the SAME
    Shield process (module docstring's stated design), instead of the "off" leg
    bypassing the Shield and hitting llama-server directly, which would confound
    the comparison with an extra network hop / FastAPI overhead that has nothing
    to do with the defense itself.

    NOTE: this endpoint is intentionally unauthenticated, consistent with the rest
    of the Shield (no auth anywhere — see X-Priority spoofability note in
    shield/README.md). Fine for a trusted LAN hackathon session; do not expose this
    port on an untrusted network.

    IMPORTANT: this route must stay registered ABOVE the `@app.post("/{path:path}")`
    catch-all below — Starlette matches routes in registration order, and the
    catch-all would otherwise swallow POST /admin/shield-active and forward it to
    llama-server as if it were a completion request.
    """
    global _shield_active
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "expected JSON body {'active': true|false}"}, status_code=400)

    if "active" not in payload or not isinstance(payload["active"], bool):
        return JSONResponse({"error": "expected JSON body {'active': true|false}"}, status_code=400)

    _shield_active = payload["active"]
    logger.info(f"Shield active flag toggled at runtime: {_shield_active}")
    return {"shield_active": _shield_active}


@app.post("/{path:path}")
async def proxy(request: Request, path: str):
    return await forward_request(request)


@app.get("/health")
async def health():
    return {"status": "ok", "shield_active": _shield_active}


@app.get("/metrics")
async def metrics():
    """Proxy llama-server's Prometheus text metrics unchanged (llamacpp:* only).

    Must return PlainTextResponse, not a bare string — FastAPI JSON-encodes a
    string return value by default, which wraps the Prometheus text in quotes
    and escapes its newlines, making it unparseable by any real scraper.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.llama_server_url}/metrics", timeout=5.0)
            return PlainTextResponse(response.text)
    except Exception as e:
        logger.error(f"Failed to fetch metrics: {e}")
        return {"error": "Metrics unavailable"}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Shield proxy on port {settings.shield_port}")
    logger.info(f"Forwarding to llama-server at {settings.llama_server_url}")
    uvicorn.run(app, host="0.0.0.0", port=settings.shield_port)
