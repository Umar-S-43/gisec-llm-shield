"""
Shield: FastAPI reverse proxy implementing cost-aware admission control.

Reads LLAMA_SERVER_URL from environment (required).

Defense mechanisms (see CLAUDE.md), applied at RUNTIME in this order: A -> C -> B
(changed 2026-09-11; was B -> C -> A):

  1. (A) Token-budget check — checked FIRST now, so every request's cost is judged
     before any capacity/queue concern. Rejects requests whose ESTIMATED COST
     (prompt tokens + requested output tokens) would blow the caller's budget.
     Legitimate and default traffic draw from separate token buckets. This budget
     check is what catches Profile D (few requests/sec, each one huge) that a plain
     request-counter misses.
     TokenBucket.consume() deducts on success immediately, not just checks — needed
     to prevent a time-of-check-to-time-of-use race between concurrent requests.
     bucket.refund(cost) is called at every downstream rejection point in C and B
     below, so budget is only ever actually spent, net, on requests that reach
     llama-server.
  2. (C, concurrency layer) TWO independent fairness checks, both must pass:
     a. Fixed-fraction slot reservation — caps how many requests per TIER may be
        in-flight at once. Reserves a fraction of TOTAL_LLAMA_SLOTS exclusively for
        legitimate-tier traffic so attack traffic cannot fill every slot even if it
        has token budget left to spend.
     b. Per-identity concurrency cap (added 2026-09-11, PER_IDENTITY_CONCURRENCY_CAP,
        default 2) — caps in-flight requests per SOURCE IP, trusting no claimed tier
        at all. Added after a live test (LEGITIMATE_SLOT_FRACTION=1.0, simulating an
        attacker with many accounts that all legitimately claim the legitimate tier)
        showed check (a) provides ZERO protection once every requester shares one
        tier — confirmed live, every rejection in that test was raw concurrency
        exhaustion, not the tier check. KNOWN LIMITATION: source IP is a practical
        identity proxy, not a real per-account key system — reasonable against a
        single-machine attacker, not a fully solved answer to a genuinely
        distributed attacker with many real IPs.
  3. (B) Queue-aware shedding — checked LAST now. Watches llamacpp:requests_deferred
     (scraped from llama-server's own /metrics) and short-circuits with 503 before
     the real server's queue backs up, using /slots?fail_on_no_slot=1 as the
     authoritative "is there a slot" check.
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

import os
import re
import csv
import math
import time
import logging
import httpx
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings

# Log to both the console (as before) and a real file on disk (shield/shield.log,
# gitignored -- runtime state, not a result artifact). The console-only setup
# made "watch the Shield live" mean "read a background task's captured stdout,"
# which only the process that launched it could see. A real file lets anyone
# (a separate terminal, a PowerShell dashboard, another teammate) tail it too.
_LOG_FILE_PATH = Path(__file__).parent / "shield.log"
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_FILE_PATH, encoding="utf-8"),
    ],
)
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

    # Per-identity concurrency cap (added 2026-09-11) — a SEPARATE fairness check
    # from the tier-based slot reservation above. Motivation: the tier check only
    # protects "legitimate" traffic from "default" traffic, and relies entirely on
    # the X-Priority header being honest. If an attacker can obtain many accounts
    # that all legitimately carry X-Priority: legitimate (e.g. LEGITIMATE_SLOT_FRACTION
    # was set to 1.0 to test exactly this), the tier check provides ZERO protection —
    # confirmed live: every rejection in that test came from raw concurrency
    # exhaustion (>=4 in flight), not the tier check, because there was no longer
    # a "default" tier to separate anyone from.
    #
    # This check doesn't trust ANY claimed identity/tier at all. It caps how many
    # concurrent in-flight requests a single SOURCE IP may have, full stop,
    # regardless of what priority header it claims. An attacker with many accounts
    # now needs many DISTINCT IPs too, not just many accounts — raising the cost
    # of the attack on a second, independent axis instead of relying solely on
    # account-level trust.
    #
    # KNOWN LIMITATION, stated explicitly rather than hidden: this uses source IP
    # as a practical stand-in for "identity," since this prototype has no real
    # per-user API key system. That's a reasonable proxy for a single-machine
    # attacker (which is what this project's load tests actually simulate), but
    # it does NOT fully solve a genuinely distributed attacker with many real IPs
    # (botnet, rented proxy pool, many cloud VMs) -- that threat needs additional
    # layers (per-account keys, an upstream CDN/edge DDoS layer) this single
    # reverse-proxy Shield can't provide alone. Documented as an explicit known
    # limitation, not a claimed complete solution.
    per_identity_concurrency_cap: int = 2

    metrics_poll_timeout: float = 2.0

    # Cache TTL for slot_available()'s /slots?fail_on_no_slot=1 result — see
    # docs/MANUAL_CONFIG.md. Mirrors get_requests_deferred()'s existing
    # _DEFERRED_CACHE_TTL pattern. Kept configurable (not a hardcoded constant)
    # because the right value depends on real attack-load measurements we don't
    # have yet as of this commit — see commit message for status.
    slot_check_ttl: float = 0.5

    class Config:
        env_file = ".env"
        case_sensitive = False
        # This repo's .env is shared across Shield, loadgen, and run_comparison.sh
        # (SHIELD_URL, SHIELD_PORT for other tools, etc.) — pydantic-settings
        # defaults to rejecting any .env key it can't map to a declared field,
        # which crashes the Shield on startup for keys that are legitimately
        # meant for other components. Ignore, don't forbid, unknown keys.
        extra = "ignore"


settings = Settings()

if not settings.llama_server_url:
    raise ValueError("LLAMA_SERVER_URL environment variable is required")

logger.info(f"Shield proxy configured to forward to: {settings.llama_server_url}")
logger.info(f"Shield active (defense-on): {settings.shield_active}")

if "total_llama_slots" not in settings.model_fields_set:
    # NOTE: checking os.environ here would be wrong — pydantic-settings loads
    # values from .env directly into the model without ever populating
    # os.environ, so that check would warn even when TOTAL_LLAMA_SLOTS *is*
    # correctly set in .env. model_fields_set reflects the model's actual
    # source-of-truth regardless of whether the value came from .env, a real
    # env var, or neither.
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

# In-flight counters (requests forwarded to llama-server, response not yet returned).
# Plain dict, not a class/lock: asyncio is single-threaded/cooperative and these are
# only ever mutated by non-yielding `+= 1` / `-= 1` statements, so there's no
# interleaving hazard between the increment, the check, and the decrement.
_in_flight = {"legitimate": 0, "default": 0}

# Per-source-IP in-flight counters, for the per-identity concurrency cap (see
# Settings.per_identity_concurrency_cap). Same interleaving-safety reasoning as
# _in_flight above. Keys are deleted once a count returns to 0 (in the decrement
# path below) rather than left at 0 forever, so this doesn't grow unbounded over
# a long session with many distinct clients.
_in_flight_by_identity: dict[str, int] = {}

app = FastAPI(title="Shield Proxy")

# Shared, connection-pooled clients for slot_available() and get_requests_deferred().
# PR #3 originally pooled slot_available() only and deliberately left
# get_requests_deferred() on a fresh-client-per-call pattern ("not a general
# refactor"). Live testing on 2026-09-10 showed that was a mistake: under a real
# flood, many requests can miss get_requests_deferred()'s 0.5s cache in the same
# instant (before any of them writes back) and each fires its own unpooled
# connection to llama-server's /metrics — observed as 2,000+ simultaneous
# connections from the Shield's own host against a 4-slot server, burying it
# hard enough that even /health stopped responding. Pooling this one too doesn't
# eliminate the cache-miss race (still possible under extreme concurrency), but
# it removes the fresh-TCP-handshake-per-miss cost that was turning a brief race
# into a sustained pile-up. _do_forward() and the /metrics proxy still open a
# fresh client per call — not implicated in this incident (most requests were
# shed by slot reservation before ever reaching _do_forward) and left alone.
_slot_check_client = httpx.AsyncClient()
_deferred_check_client = httpx.AsyncClient()


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
    output_cost = int(payload.get("n_predict") or payload.get("max_tokens") or 128)

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

    def refund(self, cost: float):
        """Give back a cost previously consume()'d, for a request that later
        turned out not to be forwarded after all (rejected by a downstream
        check). Capped at capacity, same as a normal refill, so a refund can
        never push the bucket above its max. Cheap and instant -- no await,
        no I/O, just arithmetic on an in-memory number -- so calling this in
        every downstream rejection branch costs nothing measurable."""
        self.tokens = min(self.capacity, self.tokens + cost)


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
        response = await _deferred_check_client.get(
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


_slot_cache = {"value": True, "checked_at": 0.0}


async def slot_available() -> bool:
    """
    Authoritative check: llama-server returns non-200 from /slots?fail_on_no_slot=1
    when full.

    PERFORMANCE FIX (unverified as of this commit — see commit message): previously
    this created a brand-new httpx.AsyncClient() and made a fresh network round trip
    on EVERY incoming request, with no cache. Under the Phase 3 sustained-flood test
    (50 req/s straight at the Shield), with llama-server itself already saturated by
    ~4,950 attack requests, this was theorized to queue up on the Shield's single
    asyncio event loop (no worker pool — see shield/main.py's uvicorn.run() call) and
    contribute to both observed failure modes: client-side timeouts and TCP-level
    connection failures. This is a plausible, code-reading-based theory, NOT confirmed
    by a rerun yet.

    Two changes, mirroring get_requests_deferred()'s existing _DEFERRED_CACHE_TTL
    pattern: (1) cache the result for settings.slot_check_ttl seconds so concurrent
    requests within that window reuse one answer instead of each firing a fresh
    /slots call; (2) use the shared, connection-pooled _slot_check_client instead of
    opening a new client (and paying a fresh TCP/connection-pool setup cost) per call.

    Does NOT change what counts as "admit" vs "shed" — same 200-means-available
    logic, same fail-open-on-error behavior as before.
    """
    now = time.time()
    if now - _slot_cache["checked_at"] < settings.slot_check_ttl:
        return _slot_cache["value"]

    try:
        response = await _slot_check_client.get(
            f"{settings.llama_server_url}/slots?fail_on_no_slot=1",
            timeout=settings.metrics_poll_timeout,
        )
        value = response.status_code == 200
    except Exception as e:
        logger.warning(f"Failed to check /slots: {e}")
        value = True  # optimistic fail-open if llama-server is briefly unreachable

    _slot_cache["value"] = value
    _slot_cache["checked_at"] = now
    return value


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
    # Source IP, used only by the per-identity concurrency cap below (Defense C,
    # identity-fairness sub-check) — see Settings.per_identity_concurrency_cap for
    # why this exists and its known IP-as-identity-proxy limitation.
    client_id = request.client.host if request.client else "unknown"

    if not settings.shield_active:
        # Day-1 / defense-off mode: pass everything through, just log. No cost was
        # estimated for this request, so there is nothing to reconcile against.
        logger.info(f"[PASSTHROUGH] {request.method} {request.url.path} priority={priority}")
        return await _do_forward(request, body)

    # Pipeline order: A -> C -> B (changed 2026-09-11; was B -> C -> A).
    #
    # A's bucket.consume() below deducts immediately, not just checks -- that's
    # deliberate, not an oversight: an async event loop can have many requests
    # "in the middle of" this function at once, and if A only peeked at the
    # balance without reserving it, two concurrent requests could each see
    # enough budget for themselves while jointly overspending it (a classic
    # time-of-check-to-time-of-use race) -- immediate deduction is what
    # prevents that.
    #
    # But that alone would mean a request that passes A and is THEN shed by C
    # or B has paid for nothing it got to use. Fixed with bucket.refund(cost)
    # at every downstream rejection point below -- the bucket is only ever
    # actually spent, net, on requests that make it all the way to
    # llama-server. refund() has no await/I/O in it (see its docstring), so
    # this costs nothing measurable.

    # (A) Cost-aware token budget -- checked first now, so every request's cost
    # is judged before any capacity/queue concern, matching the project's core
    # thesis (price the request, not just the slot) as directly as possible.
    prompt_cost, output_cost = estimate_request_cost(body)
    cost = prompt_cost + output_cost
    bucket = legitimate_bucket if priority else default_bucket
    if not bucket.consume(cost):
        # Rejected requests (429/503) never reach llama-server, so there's nothing
        # to reconcile an estimate against — this is intentional, not a gap.
        logger.warning(f"Token budget exceeded (cost={cost}, priority={priority}); rejecting")
        return JSONResponse({"error": "Token budget exceeded", "estimated_cost": cost}, status_code=429)

    # (C, concurrency layer) Fixed-fraction slot reservation. Reads/writes only
    # the _in_flight counters -- no bucket interaction here.
    #
    # NOTE: no wait-time aging — see module docstring for why that's a deliberate
    # cut, not an oversight.
    if priority:
        # Legitimate traffic may use the full pool, including the share default
        # traffic is capped away from.
        if _in_flight["legitimate"] >= settings.total_llama_slots:
            bucket.refund(cost)
            logger.warning(
                f"Slot reservation: legitimate_in_flight={_in_flight['legitimate']} "
                f">= total_llama_slots={settings.total_llama_slots}; shedding (refunded cost={cost})"
            )
            return JSONResponse(
                {"error": "Tier capacity reserved", "reason": "legitimate_in_flight_at_total_capacity"},
                status_code=503,
            )
    else:
        # Default traffic is capped to its non-reserved share and cannot eat into
        # the portion reserved for legitimate traffic, even if that portion is idle.
        if _in_flight["default"] >= _default_slot_capacity:
            bucket.refund(cost)
            logger.warning(
                f"Slot reservation: default_in_flight={_in_flight['default']} "
                f">= default_capacity={_default_slot_capacity} "
                f"(reserved_for_legitimate={_reserved_for_legitimate}); shedding (refunded cost={cost})"
            )
            return JSONResponse(
                {"error": "Tier capacity reserved", "reason": "default_tier_capacity_exhausted"},
                status_code=503,
            )

    # (C, identity-fairness sub-check) Per-source-IP concurrency cap. Trusts NO
    # claimed tier/identity at all -- this is what still protects real users when
    # an attacker holds many accounts that all legitimately carry X-Priority:
    # legitimate (confirmed live: with LEGITIMATE_SLOT_FRACTION=1.0, the tier
    # check above provides zero protection, since there's no "default" tier left
    # to separate anyone from). See Settings.per_identity_concurrency_cap for the
    # known source-IP-as-identity-proxy limitation.
    if _in_flight_by_identity.get(client_id, 0) >= settings.per_identity_concurrency_cap:
        bucket.refund(cost)
        logger.warning(
            f"Per-identity concurrency cap: client={client_id} in_flight={_in_flight_by_identity.get(client_id, 0)} "
            f">= cap={settings.per_identity_concurrency_cap}; shedding (refunded cost={cost})"
        )
        return JSONResponse(
            {"error": "Per-identity concurrency cap exceeded", "reason": "per_identity_in_flight_at_cap"},
            status_code=503,
        )

    # (B) Queue-aware shedding -- checked last now. Check the deferred gauge
    # first (cheap, cached), fall back to the authoritative /slots check only
    # when it looks tight.
    deferred = await get_requests_deferred()
    shed_threshold = (
        settings.deferred_shed_threshold_legitimate if priority
        else settings.deferred_shed_threshold_default
    )
    if deferred >= shed_threshold:
        bucket.refund(cost)
        logger.warning(f"Shedding load: requests_deferred={deferred} >= threshold={shed_threshold} priority={priority} (refunded cost={cost})")
        return JSONResponse({"error": "Service overloaded", "requests_deferred": deferred}, status_code=503)

    if not await slot_available():
        bucket.refund(cost)
        logger.warning(f"No slot available on llama-server (priority={priority}); shedding (refunded cost={cost})")
        return JSONResponse({"error": "No slots available"}, status_code=503)

    # Admitted — forward, tracking in-flight counts for both the tier-based and
    # per-identity concurrency checks above. Incremented right before the call,
    # decremented in `finally` so the counts can never leak upward whether the
    # forward succeeds, errors internally (caught inside _do_forward), or raises
    # unexpectedly.
    tier_key = "legitimate" if priority else "default"
    _in_flight[tier_key] += 1
    _in_flight_by_identity[client_id] = _in_flight_by_identity.get(client_id, 0) + 1
    try:
        return await _do_forward(request, body, reconcile=(prompt_cost, output_cost), priority=priority)
    finally:
        _in_flight[tier_key] -= 1
        _in_flight_by_identity[client_id] -= 1
        if _in_flight_by_identity[client_id] <= 0:
            # Delete rather than leave at 0 -- keeps the dict bounded to
            # currently-active identities instead of growing forever across a
            # long session with many distinct clients.
            del _in_flight_by_identity[client_id]


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
                # Must stay comfortably ABOVE the longest client-side timeout any loadgen
                # script sets (profile-d.js: 120s), not equal to it — otherwise the Shield
                # can kill a request the client was still willing to wait for, which shows
                # up in results as "the Shield is broken" rather than what it actually is.
                # See docs/MANUAL_CONFIG.md.
                timeout=130.0,
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


@app.post("/{path:path}")
async def proxy(request: Request, path: str):
    return await forward_request(request)


@app.on_event("shutdown")
async def _close_pooled_clients():
    await _slot_check_client.aclose()
    await _deferred_check_client.aclose()


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
    # log_config=None: without this, uvicorn.run() applies its own internal
    # dictConfig and installs handlers directly on the "uvicorn"/"uvicorn.access"
    # loggers, which silently bypasses the basicConfig handlers set up above --
    # verified empirically (access lines with response codes were missing from
    # shield.log until this was added). With log_config=None, uvicorn's loggers
    # fall back to Python's default propagate=True and inherit our two handlers
    # (console + file) instead.
    uvicorn.run(app, host="0.0.0.0", port=settings.shield_port, log_config=None)
