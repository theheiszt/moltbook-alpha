"""
Moltbook Alpha API Server with Hardened Solana / USDC Payment Verification.
Verifies on-chain transactions on Solana mainnet and automatically mints API keys
with ACID transactional SQLite storage, zero backdoors, rate limiting, and fail-closed security.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import re
import secrets
from typing import List, Optional

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Shared singletons, rate limiters, storage, and metered gates from app_state
from app_state import (
    PROJECT_ROOT,
    SERVER_START_TIME,
    _DASHBOARD_METRICS_CACHE,
    _DASHBOARD_METRICS_CACHE_LOCK,
    _DASHBOARD_METRICS_CACHE_TTL_SECONDS,
    IdempotentReplay,
    MeteredCall,
    _payment_required_detail,
    concurrency_limiter,
    data_product_exchange,
    dex_microstructure,
    extract_api_key,
    get_client_ip,
    in_flight_deduplicator,
    intel_engine,
    is_trusted_proxy,
    metered,
    nano_adapter,
    rate_limiter,
    refund_dispatcher,
    storage,
    token_bucket_limiter,
    witness_key_manager,
    witness_manager,
)
from capabilities import get_api_capabilities
from config import (
    BASE_DIR,
    BASE58_PATTERN,
    CANONICAL_USDC_MINT,
    DB_PATH,
    DEFAULT_RATE_LIMIT_BURST_CAPACITY,
    DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
    DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    INDEX_HTML_PATH,
    REPORTS_DIR,
    WEBHOOK_SECRET,
    WITNESS_KEY_PATH,
    get_trusted_proxies,
    is_demo_keys_enabled,
    load_payment_config,
)
from cryptographic_witness import WitnessKeyManager, WitnessManager
from data_products import DataProductExchange
from errors import (
    ApiError,
    DOCS_BASE_URL,
    ERROR_REGISTRY,
    ErrorCode,
    OperationOutcome,
    RecoveryAction,
    format_error_payload,
)
from job_board import create_jobs_router
from metrics import (
    record_payment,
    record_rate_limit,
    record_request,
    record_webhook,
    registry,
    update_active_keys_gauge,
)
from ops.security.confirm_store import confirm_store
from ops.security.safe_mode import (
    disable_safe_mode,
    enable_safe_mode,
    get_safe_mode_status,
    is_mutation_allowed,
)
from ops.trading.dex_microstructure import (
    DEXMicrostructureEngine,
    microstructure_broadcaster,
)
from payment_verifier import (
    NanoInvoicePaymentAdapter,
    RPCError,
    SolanaPaymentVerifier,
    SolanaRefundDispatcher,
    VerificationError,
    VerifyPaymentInput,
)
from rate_limiter import (
    ConcurrencyLimiter,
    InFlightDeduplicator,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)
# Routers
from routes.account import create_account_router
from routes.admin import create_admin_router
from routes.discovery import create_discovery_router
from routes.exchange import create_exchange_router
from routes.intel import create_intel_router
from routes.nfts import create_nfts_router
from routes.pages import create_pages_router
from routes.payments import create_payments_router
from routes.webhooks import create_webhooks_router
from storage import StorageError, StorageManager

__all__ = [
    "app",
    "EDGE_CACHEABLE_PATHS",
    "storage",
    "rate_limiter",
    "token_bucket_limiter",
    "concurrency_limiter",
    "in_flight_deduplicator",
    "witness_key_manager",
    "witness_manager",
    "intel_engine",
    "nano_adapter",
    "refund_dispatcher",
    "dex_microstructure",
    "data_product_exchange",
    "is_trusted_proxy",
    "get_client_ip",
    "_payment_required_detail",
    "extract_api_key",
    "IdempotentReplay",
    "MeteredCall",
    "metered",
    "SERVER_START_TIME",
    "PROJECT_ROOT",
    "_DASHBOARD_METRICS_CACHE",
    "_DASHBOARD_METRICS_CACHE_LOCK",
    "_DASHBOARD_METRICS_CACHE_TTL_SECONDS",
    "get_api_capabilities",
    "BASE_DIR",
    "BASE58_PATTERN",
    "CANONICAL_USDC_MINT",
    "DB_PATH",
    "DEFAULT_RATE_LIMIT_BURST_CAPACITY",
    "DEFAULT_RATE_LIMIT_MAX_CONCURRENT",
    "DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "INDEX_HTML_PATH",
    "REPORTS_DIR",
    "WEBHOOK_SECRET",
    "WITNESS_KEY_PATH",
    "get_trusted_proxies",
    "is_demo_keys_enabled",
    "load_payment_config",
    "WitnessKeyManager",
    "WitnessManager",
    "DataProductExchange",
    "ApiError",
    "DOCS_BASE_URL",
    "ERROR_REGISTRY",
    "ErrorCode",
    "OperationOutcome",
    "RecoveryAction",
    "format_error_payload",
    "create_jobs_router",
    "record_payment",
    "record_rate_limit",
    "record_request",
    "record_webhook",
    "registry",
    "update_active_keys_gauge",
    "confirm_store",
    "disable_safe_mode",
    "enable_safe_mode",
    "get_safe_mode_status",
    "is_mutation_allowed",
    "DEXMicrostructureEngine",
    "microstructure_broadcaster",
    "NanoInvoicePaymentAdapter",
    "RPCError",
    "SolanaPaymentVerifier",
    "SolanaRefundDispatcher",
    "VerificationError",
    "VerifyPaymentInput",
    "ConcurrencyLimiter",
    "InFlightDeduplicator",
    "SlidingWindowRateLimiter",
    "TokenBucketRateLimiter",
    "StorageError",
    "StorageManager",
]

logger = logging.getLogger("moltbook.api")


async def _background_quota_reservation_sweeper():
    """Continuously sweeps expired quota reservations, auto-restoring credits to dropped clients."""
    while True:
        try:
            await asyncio.sleep(30)
            reaped = storage.reap_expired_reservations()
            if reaped > 0:
                logger.info("Auto-reaped %d stale/abandoned quota reservations", reaped)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Error in background quota reservation sweeper: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sweeper_task = asyncio.create_task(_background_quota_reservation_sweeper())
    try:
        yield
    finally:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Moltbook Alpha Intelligence API",
    description="Agentic Market Intelligence & Quant Insights with Solana Verification",
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=86400,
)
app.add_middleware(GZipMiddleware, minimum_size=500)

_assets_dir = PROJECT_ROOT / "assets"
if _assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


EDGE_CACHEABLE_PATHS = [
    "/v1/health",
    "/v1/quickstart",
    "/v1/capabilities",
    "/v1/intel/sample",
    "/v1/intel/observatory/status",
    "/v1/sample",
    "/.well-known/agent-card.json",
    "/v1/payments/config",
    "/v1/errors",
]


@app.middleware("http")
async def request_tracing_middleware(request: Request, call_next):
    req_id = request.headers.get("x-request-id")
    if not req_id or not re.match(r"^[a-zA-Z0-9_\-\.]{8,64}$", req_id):
        req_id = f"req_{secrets.token_hex(8)}"
    request.state.request_id = req_id

    # Keys in URLs leak into access logs, proxies, browser history and Referer headers: reject them outright.
    if "api_key" in request.query_params or "x_api_key" in request.query_params:
        content = format_error_payload(
            code=ErrorCode.VALIDATION_ERROR.value,
            message=(
                "API keys are not accepted in the URL query string. Send the key in the X-API-KEY header "
                "or as Authorization: Bearer molt_... . Rotate the key if this URL may have been logged."
            ),
            request_id=req_id,
            status_code=400,
            retryable=False,
        )
        return JSONResponse(status_code=400, content=content, headers={"X-Request-ID": req_id})

    # Developer Experience (DX): accept API keys via Authorization: Bearer molt_... as well as X-API-KEY
    if not request.headers.get("x-api-key"):
        candidate_key = None
        auth_hdr = request.headers.get("authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            token_val = auth_hdr[7:].strip()
            if token_val and not token_val.startswith("adm_sess_"):
                candidate_key = token_val
        if candidate_key:
            raw_headers = list(request.scope.get("headers", []))
            raw_headers.append((b"x-api-key", candidate_key.encode("utf-8")))
            request.scope["headers"] = raw_headers
            if hasattr(request, "_headers"):
                delattr(request, "_headers")

    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id

    # Edge caching headers for unmetered static/discovery endpoints
    if request.method == "GET" and response.status_code == 200:
        path = request.url.path
        if path in EDGE_CACHEABLE_PATHS or (path.startswith("/v1/tools/") and path.endswith("/parameter-graph")):
            response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
            response.headers["Vary"] = "Accept-Encoding"

    return response


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        norm_endpoint = getattr(route, "path", None) or "unmatched_route"
        record_request(norm_endpoint, request.method, status_code)


@app.middleware("http")
async def timeout_and_rate_limit_middleware(request: Request, call_next):
    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    if not is_mutation_allowed(request.method, request.url.path):
        status_info = get_safe_mode_status()
        reason = status_info.get("reason") or "Administrative maintenance"
        content = format_error_payload(
            code="SERVICE_READ_ONLY_MODE",
            message=f"System is currently running in Read-Only Safe Mode: {reason}",
            request_id=req_id,
            status_code=503,
            retryable=True,
            retry_after=60,
            details=status_info,
        )
        return JSONResponse(status_code=503, content=content, headers={"X-Request-ID": req_id, "Retry-After": "60"})
    try:
        response = await asyncio.wait_for(call_next(request), timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        slot_id = getattr(request.state, "concurrency_slot_id", None)
        rate_key = getattr(request.state, "concurrency_rate_key", None)
        if slot_id and rate_key:
            concurrency_limiter.release(slot_id, rate_key)
            request.state.concurrency_slot_id = None

        res_id = getattr(request.state, "quota_reservation_id", None)
        if res_id:
            storage.release_quota(res_id, reason="request_timeout_504")
            request.state.quota_reservation_id = None

        content = format_error_payload(
            code="REQUEST_TIMEOUT",
            message=f"Request execution timed out after {int(DEFAULT_REQUEST_TIMEOUT_SECONDS)} seconds.",
            request_id=req_id,
            status_code=504,
            retryable=True,
            retry_after=5,
        )
        return JSONResponse(status_code=504, content=content, headers={"X-Request-ID": req_id, "Retry-After": "5"})

    # Attach standard rate limit headers
    rl_limit = getattr(request.state, "rate_limit_limit", DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN)
    rl_remaining = getattr(request.state, "rate_limit_remaining", None)
    rl_reset = getattr(request.state, "rate_limit_reset", 0)

    response.headers["X-RateLimit-Limit"] = str(rl_limit)
    if rl_remaining is not None:
        response.headers["X-RateLimit-Remaining"] = str(max(0, int(rl_remaining)))
    response.headers["X-RateLimit-Reset"] = str(max(0, int(rl_reset)))

    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    headers = dict(exc.headers)
    headers["X-Request-ID"] = req_id
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)

    content = format_error_payload(
        code=exc.code,
        message=exc.message,
        request_id=req_id,
        status_code=exc.status_code,
        details=exc.details,
        retryable=exc.retryable,
        retry_after=exc.retry_after,
        docs_url=exc.docs_url,
        legacy_detail=exc.legacy_detail,
        outcome=exc.outcome,
        state_effect=exc.state_effect,
        recovery_action=exc.recovery_action,
        recovery=exc.recovery,
    )
    return JSONResponse(status_code=exc.status_code, content=content, headers=headers)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    headers = dict(exc.headers or {})
    headers["X-Request-ID"] = req_id

    status_code = exc.status_code
    detail = exc.detail
    path = request.url.path

    retry_after = None
    if "Retry-After" in headers:
        try:
            retry_after = int(headers["Retry-After"])
        except (ValueError, TypeError):
            pass

    details = detail if isinstance(detail, dict) else None
    if isinstance(detail, dict):
        msg = detail.get("message") or detail.get("error") or "An error occurred."
    else:
        msg = str(detail)

    if status_code == 401:
        if path == "/metrics":
            code = ErrorCode.UNAUTHORIZED_METRICS
        elif "webhook" in path:
            code = ErrorCode.UNAUTHORIZED_WEBHOOK
        else:
            code = ErrorCode.AUTHENTICATION_REQUIRED
    elif status_code == 402:
        if isinstance(detail, dict) and "entitlement" in str(detail.get("error", "")).lower():
            code = ErrorCode.ENTITLEMENT_EXPIRED
        elif "exhausted" in str(detail).lower():
            code = ErrorCode.CREDITS_EXHAUSTED
        else:
            code = ErrorCode.PAYMENT_REQUIRED
    elif status_code == 403:
        if "revoked" in str(detail).lower():
            code = ErrorCode.API_KEY_REVOKED
        elif "demo" in str(detail).lower():
            code = ErrorCode.FEATURE_DISABLED
        else:
            code = ErrorCode.INVALID_API_KEY
    elif status_code == 404:
        code = ErrorCode.RESOURCE_NOT_FOUND
    elif status_code == 429:
        code = ErrorCode.RATE_LIMIT_EXCEEDED
    elif status_code == 502:
        code = ErrorCode.RPC_GATEWAY_ERROR
        if retry_after is None:
            retry_after = 5
    elif status_code == 503:
        code = ErrorCode.DATABASE_UNAVAILABLE
        if retry_after is None:
            retry_after = 10
    elif status_code == 400:
        d_lower = str(detail).lower()
        if "unbound" in d_lower or "active invoice" in d_lower:
            code = ErrorCode.UNBOUND_PAYMENT_REJECTED
        elif "expired" in d_lower:
            code = ErrorCode.INVOICE_EXPIRED
        elif "already fulfilled" in d_lower:
            code = ErrorCode.INVOICE_ALREADY_FULFILLED
        elif "claim secret" in d_lower:
            code = ErrorCode.INVALID_CLAIM_SECRET
        else:
            code = ErrorCode.PAYMENT_VERIFICATION_FAILED
    elif status_code == 422:
        code = ErrorCode.VALIDATION_ERROR
    else:
        code = ErrorCode.INTERNAL_SERVER_ERROR

    content = format_error_payload(
        code=code.value,
        message=msg,
        request_id=req_id,
        status_code=status_code,
        details=details,
        retry_after=retry_after,
        legacy_detail=detail,
    )
    return JSONResponse(status_code=status_code, content=content, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    headers = {"X-Request-ID": req_id}
    raw_errors = jsonable_encoder(exc.errors())

    structured_errors = []
    for err in raw_errors:
        loc = err.get("loc", [])
        field = ".".join(str(p) for p in loc if p != "body") or "payload"
        structured_errors.append({
            "field": field,
            "message": err.get("msg", "Validation error"),
            "type": err.get("type", "value_error"),
        })

    content = format_error_payload(
        code=ErrorCode.VALIDATION_ERROR.value,
        message="Request input validation failed. Check parameters and payload schema.",
        request_id=req_id,
        status_code=422,
        details={"errors": structured_errors},
        retryable=False,
        legacy_detail=raw_errors,
    )
    return JSONResponse(status_code=422, content=content, headers=headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    headers = {"X-Request-ID": req_id}

    try:
        storage.log_audit_event(
            "unhandled_server_exception",
            f"Unhandled {type(exc).__name__}: {exc!s} [req_id: {req_id}]",
            ip_address=request.client.host if request.client else "unknown",
        )
    except Exception:
        pass

    content = format_error_payload(
        code=ErrorCode.INTERNAL_SERVER_ERROR.value,
        message="Internal server error. Incident has been recorded with request ID.",
        request_id=req_id,
        status_code=500,
        retryable=False,
        legacy_detail="Internal server error. Incident has been recorded.",
    )
    return JSONResponse(status_code=500, content=content, headers=headers)


@app.exception_handler(IdempotentReplay)
async def idempotent_replay_handler(request: Request, exc: IdempotentReplay):
    return JSONResponse(status_code=200, content=jsonable_encoder(exc.payload), headers={"Idempotent-Replayed": "true"})


# Mount routers
app.include_router(create_pages_router())
app.include_router(create_discovery_router())
app.include_router(create_account_router())
app.include_router(create_webhooks_router())
app.include_router(create_nfts_router())
app.include_router(create_exchange_router())
app.include_router(create_intel_router())
app.include_router(create_admin_router())
app.include_router(create_payments_router())
app.include_router(create_jobs_router(storage_manager=storage))


@app.websocket("/v1/ws/microstructure")
async def websocket_microstructure_stream(
    websocket: WebSocket,
    api_key: Optional[str] = None,
    token: Optional[str] = None,
):
    """
    Ultra-low latency sub-100ms WebSocket stream delivering Concentrated Liquidity (CLMM)
    orderbook tick depth deltas and manipulation alerts across Raydium, Orca, and Meteora.
    Supports real-time pool subscriptions and ping/pong heartbeats.
    """
    await websocket.accept()
    session_id = f"wsm_{secrets.token_hex(8)}"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Register client with broadcaster
    await microstructure_broadcaster.connect(websocket)

    # Initial connection handshake
    await websocket.send_json({
        "type": "connected",
        "session_id": session_id,
        "tracked_pools": dex_microstructure.get_tracked_pools(),
        "timestamp": now_iso,
    })

    try:
        while True:
            msg = await websocket.receive_json()
            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type")
            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "session_id": session_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            elif msg_type == "subscribe":
                pools = msg.get("pools")
                if isinstance(pools, list):
                    pools_list = [str(p) for p in pools]
                    microstructure_broadcaster.set_subscriptions(websocket, pools_list)
                else:
                    microstructure_broadcaster.set_subscriptions(websocket, [])
                await websocket.send_json({
                    "type": "subscribed",
                    "session_id": session_id,
                    "pools": list(microstructure_broadcaster.get_subscriptions(websocket)),
                })
            elif msg_type == "unsubscribe":
                microstructure_broadcaster.set_subscriptions(websocket, [])
                await websocket.send_json({
                    "type": "unsubscribed",
                    "session_id": session_id,
                })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        microstructure_broadcaster.disconnect(websocket)
        storage.log_audit_event("ws_microstructure_disconnected", f"Session {session_id} ended")


@app.websocket("/v1/ws/alpha")
async def websocket_alpha_stream(
    websocket: WebSocket,
    api_key: Optional[str] = None,
    token: Optional[str] = None,
):
    """
    Real-time streaming WebSocket endpoint for continuous intelligence feeds.
    Pushes newly detected market opportunities, cross-exchange arbitrage signals,
    and DEX manipulation telemetry directly to connected algorithmic trading agents.
    Authenticates via query param or initial connection handshake message.
    """
    await websocket.accept()

    # Initial handshake & auth
    raw_key = api_key or token
    if not raw_key:
        try:
            auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
            if isinstance(auth_msg, dict) and auth_msg.get("type") == "auth":
                raw_key = auth_msg.get("api_key") or auth_msg.get("token")
        except Exception:
            pass

    if not raw_key:
        await websocket.send_json({
            "type": "error",
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Provide ?token=... query param or initial auth message within 5s.",
        })
        await websocket.close(code=4408)
        return

    # Authenticate and deduct 1 credit for the live session
    req_id = f"ws_sess_{secrets.token_hex(6)}"
    record, auth_status = storage.authenticate_and_deduct(raw_key, request_id=req_id)
    if auth_status != "ok" or not record:
        if auth_status in ("exhausted", "entitlement_expired"):
            await websocket.send_json({
                "type": "error",
                "code": "PAYMENT_REQUIRED",
                "status": auth_status,
                "message": "Credit quota exhausted or entitlement expired. Top up via /v1/payments/verify-solana.",
            })
            await websocket.close(code=4402)
        else:
            await websocket.send_json({
                "type": "error",
                "code": "FORBIDDEN",
                "status": auth_status,
                "message": "Invalid or revoked API key.",
            })
            await websocket.close(code=4403)
        return

    session_id = f"wss_{secrets.token_hex(8)}"
    now_iso = datetime.now(timezone.utc).isoformat()
    storage.log_audit_event("ws_connected", f"WebSocket session {session_id} authenticated for tier {record['tier']}")

    await websocket.send_json({
        "type": "authenticated",
        "session_id": session_id,
        "tier": record["tier"],
        "remaining_credits": record.get("credits", 0),
        "timestamp": now_iso,
    })

    # Default filters
    sub_categories: Optional[List[str]] = None
    min_confidence = "LOW"
    seen_signal_ids: set[str] = set()

    # Send initial backlog of latest signals
    initial_signals = intel_engine.search_signals(limit=10)
    for sig in reversed(initial_signals):
        seen_signal_ids.add(sig["signal_id"])
        await websocket.send_json({
            "type": "signal",
            "session_id": session_id,
            "signal": sig,
        })

    # Concurrently handle incoming frames (ping, subscribe) and outgoing stream
    async def receiver():
        nonlocal sub_categories, min_confidence
        try:
            while True:
                msg = await websocket.receive_json()
                if not isinstance(msg, dict):
                    continue
                msg_type = msg.get("type")
                if msg_type == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "session_id": session_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                elif msg_type == "subscribe":
                    cats = msg.get("categories")
                    if isinstance(cats, list):
                        sub_categories = [str(c) for c in cats]
                    conf = msg.get("min_confidence")
                    if conf:
                        min_confidence = str(conf).upper()
                    await websocket.send_json({
                        "type": "subscribed",
                        "session_id": session_id,
                        "categories": sub_categories,
                        "min_confidence": min_confidence,
                    })
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    receiver_task = asyncio.create_task(receiver())

    try:
        while not receiver_task.done():
            await asyncio.sleep(2.0)
            current_signals = intel_engine.search_signals(limit=15)
            for s in reversed(current_signals):
                sid = s["signal_id"]
                if sid in seen_signal_ids:
                    continue
                seen_signal_ids.add(sid)

                if sub_categories and s["category"] not in sub_categories:
                    continue

                await websocket.send_json({
                    "type": "signal",
                    "session_id": session_id,
                    "signal": s,
                })
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        receiver_task.cancel()
        storage.log_audit_event("ws_disconnected", f"WebSocket session {session_id} ended")


if __name__ == "__main__":
    uvicorn.run("api_server:app", host="127.0.0.1", port=8080, reload=False)
