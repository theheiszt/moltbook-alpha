"""
Moltbook Alpha API Server with Hardened Solana / USDC Payment Verification.
Verifies on-chain transactions on Solana mainnet and automatically mints API keys
with ACID transactional SQLite storage, zero backdoors, rate limiting, and fail-closed security.
"""

import os
import json
import ipaddress
import secrets
import re
import asyncio
import logging
from contextlib import asynccontextmanager
import threading
import time
import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, field_validator, model_validator
import uvicorn

from ops.security.confirm_store import confirm_store
from ops.security.safe_mode import (
    is_mutation_allowed,
    enable_safe_mode,
    disable_safe_mode,
    get_safe_mode_status,
)
from errors import (
    DOCS_BASE_URL,
    ErrorCode,
    ERROR_REGISTRY,
    ApiError,
    format_error_payload,
    OperationOutcome,
    RecoveryAction,
)
from dag_tool_parameters import TOOL_DAG_REGISTRY

from config import (
    DB_PATH,
    REPORTS_DIR,
    INDEX_HTML_PATH,
    BASE_DIR,
    BASE58_PATTERN,
    CANONICAL_USDC_MINT,
    WEBHOOK_SECRET,
    WITNESS_KEY_PATH,
    load_payment_config,
    is_demo_keys_enabled,
    get_trusted_proxies,
    DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    DEFAULT_RATE_LIMIT_BURST_CAPACITY,
    DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
)
from cryptographic_witness import WitnessManager, WitnessKeyManager
from intel_engine import IntelEngine
from capabilities import get_api_capabilities
from data_products import DataProductExchange
from ops.trading.dex_microstructure import (
    DEXMicrostructureEngine,
    microstructure_broadcaster,
)
from storage import StorageManager, StorageError
from payment_verifier import (
    SolanaPaymentVerifier,
    VerifyPaymentInput,
    VerificationError,
    RPCError,
    NanoInvoicePaymentAdapter,
    SolanaRefundDispatcher,
)
from rate_limiter import (
    SlidingWindowRateLimiter,
    InFlightDeduplicator,
    TokenBucketRateLimiter,
    ConcurrencyLimiter,
)
from metrics import (
    registry,
    record_payment,
    record_webhook,
    record_rate_limit,
    record_request,
    update_active_keys_gauge,
)

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

# In-memory TTL cache for dashboard metrics (prevents SQLite lock contention from concurrent/rapid UI polling)
_DASHBOARD_METRICS_CACHE_LOCK = threading.Lock()
_DASHBOARD_METRICS_CACHE = {"timestamp": 0.0, "payload": None}
_DASHBOARD_METRICS_CACHE_TTL_SECONDS = 10.0

SERVER_START_TIME = time.time()
PROJECT_ROOT = Path(__file__).resolve().parent


@app.middleware("http")
async def request_tracing_middleware(request: Request, call_next):
    req_id = request.headers.get("x-request-id")
    if not req_id or not re.match(r"^[a-zA-Z0-9_\-\.]{8,64}$", req_id):
        req_id = f"req_{secrets.token_hex(8)}"
    request.state.request_id = req_id

    # Developer Experience (DX): seamlessly accept API keys via Authorization: Bearer molt_... or ?api_key=molt_...
    if not request.headers.get("x-api-key"):
        candidate_key = None
        auth_hdr = request.headers.get("authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            token_val = auth_hdr[7:].strip()
            if token_val and not token_val.startswith("adm_sess_"):
                candidate_key = token_val
        if not candidate_key:
            q_key = request.query_params.get("api_key") or request.query_params.get("x_api_key")
            if q_key and q_key.strip():
                candidate_key = q_key.strip()
        if candidate_key:
            raw_headers = list(request.scope.get("headers", []))
            raw_headers.append((b"x-api-key", candidate_key.encode("utf-8")))
            request.scope["headers"] = raw_headers
            if hasattr(request, "_headers"):
                delattr(request, "_headers")

    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        endpoint = request.url.path
        if endpoint.startswith("/v1/payments/status/"):
            norm_endpoint = "/v1/payments/status/:signature"
        elif endpoint.startswith("/v1/payments/invoice/") and endpoint.endswith("/claim"):
            norm_endpoint = "/v1/payments/invoice/:id/claim"
        elif endpoint.startswith("/v1/payments/invoice/"):
            norm_endpoint = "/v1/payments/invoice/:id"
        elif endpoint.startswith("/v1/payments/refund/"):
            norm_endpoint = "/v1/payments/refund/:unmatched_id"
        elif endpoint.startswith("/v1/errors/"):
            norm_endpoint = "/v1/errors/:code"
        elif endpoint.startswith("/v1/tools/") and endpoint.endswith("/parameter-graph"):
            norm_endpoint = "/v1/tools/:tool/parameter-graph"
        elif endpoint.startswith("/v1/challenges/") and endpoint != "/v1/challenges/verify":
            norm_endpoint = "/v1/challenges/:id"
        elif endpoint.startswith("/v1/witnesses/") and endpoint not in {"/v1/witnesses/public-keys", "/v1/witnesses/verify"}:
            norm_endpoint = "/v1/witnesses/:id"
        elif endpoint.startswith("/v1/data-products/") and endpoint.endswith("/latest"):
            norm_endpoint = "/v1/data-products/:product_id/latest"
        elif endpoint.startswith("/v1/data-products/") and endpoint.endswith("/sample"):
            norm_endpoint = "/v1/data-products/:product_id/sample"
        elif endpoint.startswith("/v1/data-products/") and endpoint != "/v1/data-products":
            norm_endpoint = "/v1/data-products/:product_id"
        elif endpoint.startswith("/v1/intel/microstructure/") and endpoint != "/v1/intel/microstructure":
            norm_endpoint = "/v1/intel/microstructure/:pool_id"
        elif endpoint.startswith("/v1/webhooks/test/"):
            norm_endpoint = "/v1/webhooks/test/:subscription_id"
        elif endpoint.startswith("/v1/webhooks/") and endpoint != "/v1/webhooks":
            norm_endpoint = "/v1/webhooks/:subscription_id"
        elif endpoint.startswith("/v1/nfts/assets/"):
            norm_endpoint = "/v1/nfts/assets/:filename"
        elif endpoint.startswith("/v1/nfts/metadata/"):
            norm_endpoint = "/v1/nfts/metadata/:nft_id"
        elif endpoint.startswith("/v1/jobs/") and endpoint.endswith("/submit"):
            norm_endpoint = "/v1/jobs/:job_id/submit"
        elif endpoint.startswith("/v1/jobs/") and endpoint not in {"/v1/jobs/board", "/v1/jobs/post"}:
            norm_endpoint = "/v1/jobs/:job_id"
        elif endpoint in {
            "/dashboard",
            "/v1/metrics/dashboard",
            "/v1/newsletter/latest",
            "/v1/quickstart",
            "/v1/admin/briefing/refresh",
            "/v1/admin/briefing/ingest-post",
            "/v1/jobs/verify-witness",
            "/v1/intel/demand",
            "/v1/quant/first-passage",
            "/v1/quant/trade-viability",
            "/v1/nfts/catalog",
            "/v1/nfts/order",
            "/v1/nfts/claim",
            "/v1/jobs/board",
            "/v1/jobs/post",
            "/",
            "/metrics",
            "/gateway.json",
            "/v1/gateway/discovery",
            "/.well-known/agent-card.json",
            "/v1/health",
            "/v1/errors",
            "/v1/challenges",
            "/v1/challenges/verify",
            "/v1/tools",
            "/v1/witnesses/public-keys",
            "/v1/witnesses/verify",
            "/v1/intel/sample",
            "/v1/intel/latest",
            "/v1/intel/signals",
            "/v1/intel/signals/trading",
            "/v1/intel/opportunities",
            "/v1/intel/refresh",
            "/v1/intel/microstructure",
            "/v1/metrics/funnel",
            "/v1/admin/login",
            "/v1/admin/change-password",
            "/v1/admin/logout",
            "/v1/admin/session",
            "/v1/admin/safemode",
            "/v1/webhooks",
            "/v1/webhooks/subscribe",
            "/v1/payments/config",
            "/v1/payments/invoice",
            "/v1/payments/verify-solana",
            "/v1/payments/verify-nano",
            "/v1/payments/reconcile",
            "/v1/payments/unmatched",
            "/v1/payments/webhook",
            "/v1/keys/generate-demo",
            "/v1/briefing/latest",
            "/v1/account/quota",
            "/v1/account/usage",
            "/v1/capabilities",
            "/v1/data-products",
        }:
            norm_endpoint = endpoint
        else:
            norm_endpoint = "unmatched_route"
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


# Initialize storage, rate limiters, deduplicator, cryptographic state witness manager, and intel engine
storage = StorageManager(DB_PATH)
rate_limiter = SlidingWindowRateLimiter()
token_bucket_limiter = TokenBucketRateLimiter(
    default_capacity=DEFAULT_RATE_LIMIT_BURST_CAPACITY,
    default_refill_per_min=DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    storage=storage,
)
concurrency_limiter = ConcurrencyLimiter(
    default_max_concurrent=DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
    storage=storage,
)
in_flight_deduplicator = InFlightDeduplicator()
witness_key_manager = WitnessKeyManager(WITNESS_KEY_PATH)
witness_manager = WitnessManager(storage, witness_key_manager)
intel_engine = IntelEngine(storage)
payment_cfg = load_payment_config()
nano_adapter = NanoInvoicePaymentAdapter(
    merchant_address=payment_cfg.get("nano_treasury_address", "nano_3t1sxtuxyjgdabj6miwn6st58p8x553i8ybkikoc9ozn7mra7kk71iysfyn1")
)
refund_dispatcher = SolanaRefundDispatcher(
    treasury_wallet=payment_cfg["solana_treasury_wallet"]
)

dex_microstructure = DEXMicrostructureEngine(broadcaster=microstructure_broadcaster)
data_product_exchange = DataProductExchange()

# Seed default baseline pools with realistic institutional prices ($182 SOL)
dex_microstructure.parse_raydium_clmm_pool(
    pool_id="Raydium_SOL_USDC",
    pair="SOL/USDC",
    pool_state={
        "current_tick": -15620,
        "current_price": 182.15,
        "ticks": [
            {"tick": -15630, "price": 182.05, "liquidity_usd": 125000.0},
            {"tick": -15625, "price": 182.10, "liquidity_usd": 185000.0},
            {"tick": -15620, "price": 182.15, "liquidity_usd": 220000.0},
            {"tick": -15615, "price": 182.20, "liquidity_usd": 195000.0},
            {"tick": -15610, "price": 182.25, "liquidity_usd": 140000.0},
        ],
    },
)

dex_microstructure.parse_orca_whirlpool(
    pool_id="Orca_SOL_USDC",
    pair="SOL/USDC",
    pool_state={
        "tick_current_index": -15620,
        "price": 182.38,
        "ticks": [
            {"index": -15630, "price": 182.28, "liquidity_net": 1200.0},
            {"index": -15625, "price": 182.33, "liquidity_net": 1800.0},
            {"index": -15620, "price": 182.38, "liquidity_net": 2100.0},
            {"index": -15615, "price": 182.43, "liquidity_net": -1700.0},
            {"index": -15610, "price": 182.48, "liquidity_net": -1300.0},
        ],
    },
)

dex_microstructure.parse_meteora_dlmm(
    pool_id="Meteora_SOL_USDC",
    pair="SOL/USDC",
    pool_state={
        "active_id": -15620,
        "current_price": 182.25,
        "bins": [
            {"bin_id": -15630, "price": 182.15, "amount_x_usd": 60000.0, "amount_y_usd": 65000.0},
            {"bin_id": -15625, "price": 182.20, "amount_x_usd": 90000.0, "amount_y_usd": 95000.0},
            {"bin_id": -15620, "price": 182.25, "amount_x_usd": 110000.0, "amount_y_usd": 105000.0},
            {"bin_id": -15615, "price": 182.30, "amount_x_usd": 95000.0, "amount_y_usd": 90000.0},
            {"bin_id": -15610, "price": 182.35, "amount_x_usd": 70000.0, "amount_y_usd": 65000.0},
        ],
    },
)

# Seed standard production liquidity depths for Solana CLMM arbitrage
dex_microstructure.seed_default_pools(base_sol_price=182.50)


# Run one-time legacy migration from api_keys.json if present (skipping any admin backdoors)
legacy_keys_file = BASE_DIR / "api_keys.json"
if legacy_keys_file.exists():
    storage.migrate_from_json(legacy_keys_file)


def is_trusted_proxy(ip_str: str, trusted_proxies: list[str]) -> bool:
    """Verifies whether an IP address matches an explicitly trusted proxy or network."""
    if not trusted_proxies or not ip_str:
        return False
    if ip_str in trusted_proxies:
        return True
    try:
        addr = ipaddress.ip_address(ip_str)
        for net_str in trusted_proxies:
            try:
                net = ipaddress.ip_network(net_str, strict=False)
                if addr in net:
                    return True
            except ValueError:
                continue
    except ValueError:
        return False
    return False


def get_client_ip(request: Request) -> str:
    """
    Extracts authentic client IP address safely according to trusted-hop topology.
    Only respects X-Forwarded-For if the immediate peer (request.client.host)
    is an explicitly trusted proxy configured in TRUSTED_PROXIES.

    When traversing multi-hop chains, parses from right-to-left (nearest hop to farthest):
    skips hops that belong to TRUSTED_PROXIES, and selects the first non-trusted IP.
    This prevents untrusted clients from injecting spoofed IPs into the leftmost position.
    """
    peer_ip = request.client.host if request.client else "127.0.0.1"
    trusted_proxies = get_trusted_proxies()

    if not is_trusted_proxy(peer_ip, trusted_proxies):
        return peer_ip

    # If behind a trusted proxy and CF-Connecting-IP is provided, prioritize authentic edge IP
    cf_connecting = request.headers.get("cf-connecting-ip")
    if cf_connecting:
        try:
            ipaddress.ip_address(cf_connecting.strip())
            return cf_connecting.strip()
        except ValueError:
            pass

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer_ip

    # Split and clean all hops in the chain
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if not hops:
        return peer_ip

    # Traverse from rightmost (nearest upstream proxy) to leftmost (farthest origin)
    for hop in reversed(hops):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            # Malformed IP in chain - fail closed to peer_ip
            return peer_ip

        if not is_trusted_proxy(hop, trusted_proxies):
            # This is the first untrusted entity in the proxy chain -> authentic client
            return hop

    # If every hop in the chain is in TRUSTED_PROXIES, return the leftmost trusted hop
    return hops[0]



def authenticate_and_deduct(api_key: Optional[str], request_id: Optional[str] = None) -> Dict[str, Any]:
    cfg = load_payment_config()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Payment Required",
                "message": "Access requires an active API key or payment.",
                "price": "Starter: $1 (50 queries), Pro: $5 (300 queries), Premium: $20 (10,000 queries / 30 days).",
                "purchase_instructions": {
                    "treasury_wallet": cfg["solana_treasury_wallet"],
                    "rates": cfg["rates"],
                    "topup_packages": cfg.get("topup_packages", {}),
                    "verify_endpoint": "POST /v1/payments/verify-solana",
                },
            },
        )

    user_info, state = storage.authenticate_and_deduct(api_key, request_id=request_id)
    if state == "invalid":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key. Submit payment to /v1/payments/verify-solana or contact administrator.",
        )
    if state == "revoked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has been revoked.",
        )
    if state == "entitlement_expired":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Entitlement Expired",
                "message": "Premium entitlement has expired. Renew your Premium subscription to continue spending credits.",
                "purchase_instructions": {
                    "treasury_wallet": cfg["solana_treasury_wallet"],
                    "rates": cfg["rates"],
                    "topup_packages": cfg.get("topup_packages", {}),
                    "verify_endpoint": "POST /v1/payments/verify-solana",
                },
            },
        )
    if state == "exhausted":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Key credits exhausted. Top up your balance via Solana USDC.",
        )

    return user_info or {}


@app.get("/", response_class=HTMLResponse)
def index():
    if INDEX_HTML_PATH.exists():
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Moltbook Alpha API</h1>"


@app.get("/v1/health")
def health_check():
    cfg = load_payment_config()
    try:
        db_healthy = storage.check_health()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database health check failed: {e!s}",
        ) from e

    rpc_pool = cfg.get("rpc_endpoints", [cfg.get("rpc_url")])
    return {
        "status": "ok",
        "service": "moltbook-alpha-api",
        "version": "1.2.0",
        "database": "healthy" if db_healthy else "degraded",
        "subsystems": {
            "database": {
                "status": "ok" if db_healthy else "degraded",
                "journal_mode": "WAL",
            },
            "payments": {
                "status": "ok",
                "treasury_wallet": cfg["solana_treasury_wallet"],
                "accepted_assets": ["SOL", "USDC (Solana SPL)"],
            },
            "rpc_pool": {
                "status": "ok",
                "cluster": cfg.get("cluster", "mainnet-beta"),
                "endpoints_configured": len(rpc_pool),
            },
        },
    }


@app.get("/metrics")
def get_prometheus_metrics(request: Request):
    """
    Prometheus and OpenTelemetry-compatible metrics exposition endpoint.
    Returns plain text in standard Prometheus 0.0.4 exposition format.
    Supports optional METRICS_BEARER_TOKEN authorization header if configured in production.
    """
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token:
        auth_header = request.headers.get("authorization", "")
        expected = f"Bearer {metrics_token}"
        if not secrets.compare_digest(auth_header, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized access to metrics exposition endpoint.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    try:
        update_active_keys_gauge(storage.get_active_keys_count())
    except Exception:
        pass
    text_data = registry.export_prometheus_text()
    return Response(
        content=text_data,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/v1/metrics/funnel")
def get_funnel_metrics_endpoint(request: Request, since: Optional[str] = None):
    """
    Returns aggregated conversion funnel metrics and recent privacy-sanitized events.
    """
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token:
        auth_header = request.headers.get("authorization", "")
        expected = f"Bearer {metrics_token}"
        if not hmac.compare_digest(auth_header, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized access to metrics exposition.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return {
        "success": True,
        "funnel_metrics": storage.get_funnel_metrics(since_utc=since),
        "recent_events": storage.get_funnel_events(limit=25),
    }


class AdminLoginInput(BaseModel):
    username: str
    password: str


class AdminChangePasswordInput(BaseModel):
    current_password: str
    new_password: str


@app.post("/v1/admin/login")
def admin_login_endpoint(payload: AdminLoginInput, request: Request):
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"admin_login:{client_ip}", limit=10, window_seconds=300)
    if not allowed:
        record_rate_limit("/v1/admin/login")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    clean_user = (payload.username or "").strip().upper()
    if not storage.verify_admin_credentials(clean_user, payload.password):
        storage.log_audit_event("admin_login_failed", f"Failed admin login attempt for '{clean_user}'", ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session_token = storage.create_admin_session(clean_user, duration_hours=24)
    storage.log_audit_event("admin_login_success", f"Admin user '{clean_user}' successfully authenticated", ip_address=client_ip)
    return {
        "success": True,
        "token": session_token,
        "username": clean_user,
        "expires_in_hours": 24,
    }


@app.post("/v1/admin/change-password")
def admin_change_password_endpoint(payload: AdminChangePasswordInput, request: Request):
    client_ip = get_client_ip(request)
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()

    admin_user = storage.validate_admin_session(token)
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid administrator session required to change password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    ok, message = storage.change_admin_password(admin_user, payload.current_password, payload.new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    # Issue fresh session token since old sessions were revoked
    storage.log_audit_event(
        "admin_password_changed",
        f"Admin password changed for user '{admin_user}'",
        ip_address=client_ip,
    )
    new_token = storage.create_admin_session(admin_user, duration_hours=24)
    return {
        "success": True,
        "message": message,
        "new_token": new_token,
        "username": admin_user,
    }


@app.post("/v1/admin/logout")
def admin_logout_endpoint(request: Request):
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    storage.revoke_admin_session(token)
    return {"success": True, "message": "Admin session revoked."}


@app.get("/v1/admin/session")
def admin_session_endpoint(request: Request):
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    admin_user = storage.validate_admin_session(token)
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin session.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"authenticated": True, "username": admin_user}


class AdminSafeModeInput(BaseModel):
    active: bool
    reason: Optional[str] = "Administrative maintenance"


@app.get("/v1/admin/safemode")
def admin_get_safemode_endpoint(request: Request):
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    admin_user = storage.validate_admin_session(token)
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid administrator session required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"success": True, "safe_mode": get_safe_mode_status()}


@app.post("/v1/admin/safemode")
def admin_toggle_safemode_endpoint(payload: AdminSafeModeInput, request: Request):
    client_ip = get_client_ip(request)
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    admin_user = storage.validate_admin_session(token)
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid administrator session required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.active:
        status_dict = enable_safe_mode(reason=payload.reason or "Administrative maintenance", operator=admin_user)
        storage.log_audit_event(
            "safe_mode_enabled",
            f"Safe mode enabled by '{admin_user}': {payload.reason}",
            ip_address=client_ip,
        )
    else:
        status_dict = disable_safe_mode(operator=admin_user)
        storage.log_audit_event(
            "safe_mode_disabled",
            f"Safe mode disabled by '{admin_user}'",
            ip_address=client_ip,
        )
    return {"success": True, "safe_mode": status_dict}


@app.get("/v1/metrics/dashboard")
def get_dashboard_metrics_endpoint(request: Request):
    """
    Returns unified operational dashboard metrics for real-time monitoring.
    Requires administrator session token or METRICS_BEARER_TOKEN.
    """
    auth_header = request.headers.get("authorization", "")
    bearer_token = ""
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()

    is_authenticated = False
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token and bearer_token and hmac.compare_digest(bearer_token, metrics_token):
        is_authenticated = True
    elif bearer_token:
        admin_user = storage.validate_admin_session(bearer_token)
        if admin_user:
            is_authenticated = True

    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required. Please sign in with ADMIN credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Rate limiting: max 30 requests per minute per IP to prevent runaway polling loops
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"dashboard_metrics:{client_ip}", limit=30, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/metrics/dashboard")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Dashboard rate limit exceeded. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    # In-memory TTL cache check: return cached payload if fresh within TTL window
    now_ts = time.time()
    with _DASHBOARD_METRICS_CACHE_LOCK:
        if (
            _DASHBOARD_METRICS_CACHE["payload"] is not None
            and (now_ts - _DASHBOARD_METRICS_CACHE["timestamp"]) < _DASHBOARD_METRICS_CACHE_TTL_SECONDS
        ):
            return _DASHBOARD_METRICS_CACHE["payload"]

    db_metrics = storage.get_dashboard_metrics()

    # Enrich with real-time in-memory telemetry
    active_ws = 0
    if hasattr(microstructure_broadcaster, "active_connections_count"):
        try:
            active_ws = microstructure_broadcaster.active_connections_count
            if callable(active_ws):
                active_ws = active_ws()
        except Exception:
            active_ws = 0

    # In-flight concurrency slots
    in_flight = 0
    if hasattr(concurrency_limiter, "_in_flight"):
        try:
            with getattr(concurrency_limiter, "_lock", threading.Lock()):
                in_flight = sum(len(slots) for slots in concurrency_limiter._in_flight.values())
        except Exception:
            in_flight = 0

    # Request distribution from Prometheus registry
    requests_total = 0
    status_codes = {"2xx": 0, "4xx": 0, "5xx": 0}
    top_endpoints: Dict[str, int] = {}

    try:
        with registry._lock:
            for (m_name, labels_tuple), val in registry._counters.items():
                if m_name == "moltbook_api_requests_total":
                    requests_total += int(val)
                    labels_dict = dict(labels_tuple)
                    ep = labels_dict.get("endpoint", "other")
                    code_str = labels_dict.get("status_code", "200")
                    top_endpoints[ep] = top_endpoints.get(ep, 0) + int(val)
                    if code_str.startswith("2"):
                        status_codes["2xx"] += int(val)
                    elif code_str.startswith("4"):
                        status_codes["4xx"] += int(val)
                    elif code_str.startswith("5"):
                        status_codes["5xx"] += int(val)
    except Exception:
        pass

    uptime_sec = round(time.time() - SERVER_START_TIME, 1)

    # Load latest intelligence briefing & daily newsletter for the Operator Console
    latest_briefing_info: Dict[str, Any] = {
        "briefing_id": "N/A",
        "state_witness_id": "Verified",
        "items_analyzed": 0,
        "signals_extracted": 0,
        "created_at": None,
        "briefing_markdown": "",
        "newsletter_markdown": "",
    }
    try:
        with storage.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT briefing_id, items_analyzed, signals_extracted, report_markdown, state_witness_id, created_at
                FROM intel_briefings
                ORDER BY created_at DESC LIMIT 1
                """
            )
            b_row = cur.fetchone()
            if b_row:
                latest_briefing_info["briefing_id"] = b_row["briefing_id"]
                latest_briefing_info["items_analyzed"] = b_row["items_analyzed"]
                latest_briefing_info["signals_extracted"] = b_row["signals_extracted"]
                latest_briefing_info["briefing_markdown"] = b_row["report_markdown"] or ""
                latest_briefing_info["state_witness_id"] = b_row["state_witness_id"] or "Verified"
                latest_briefing_info["created_at"] = b_row["created_at"]
    except Exception:
        pass

    try:
        from config import REPORTS_DIR
        lb_file = Path(REPORTS_DIR) / "latest_briefing.md"
        if lb_file.is_file():
            latest_briefing_info["briefing_markdown"] = lb_file.read_text(encoding="utf-8")
        ln_file = Path(REPORTS_DIR) / "latest_newsletter.md"
        if ln_file.is_file():
            latest_briefing_info["newsletter_markdown"] = ln_file.read_text(encoding="utf-8")
    except Exception:
        pass

    payload = {
        "success": True,
        "server": {
            "status": "healthy",
            "version": "1.2.0",
            "uptime_seconds": uptime_sec,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "connected": {
            "active_websockets": active_ws,
            "in_flight_requests": in_flight,
            "events_last_5m": db_metrics["activity"]["events_last_5m"],
            "events_last_1h": db_metrics["activity"]["events_last_1h"],
            "events_last_24h": db_metrics["activity"]["events_last_24h"],
        },
        "users": db_metrics["users"],
        "sales": db_metrics["sales"],
        "traffic": {
            "total_requests": requests_total,
            "status_codes": status_codes,
            "top_endpoints": (
                sorted(
                    [(k, v) for k, v in top_endpoints.items() if k not in {"/v1/metrics/dashboard", "/dashboard", "unmatched_route"}],
                    key=lambda x: x[1],
                    reverse=True,
                )[:8]
                or sorted(top_endpoints.items(), key=lambda x: x[1], reverse=True)[:8]
            ),
        },
        "funnel": db_metrics["funnel"],
        "recent_activity": db_metrics["recent_activity"],
        "latest_briefing": latest_briefing_info,
        "ecosystem": _get_dashboard_ecosystem_summary(),
    }

    with _DASHBOARD_METRICS_CACHE_LOCK:
        _DASHBOARD_METRICS_CACHE["timestamp"] = now_ts
        _DASHBOARD_METRICS_CACHE["payload"] = payload

    return payload



def _get_dashboard_ecosystem_summary() -> Dict[str, Any]:
    """Aggregates live Agent Job Board (25 reward cap) and Molt Alpha DEMS NFT inventory for the Operator Console."""
    jb_summary: Dict[str, Any] = {
        "open_jobs": 0,
        "rewards_claimed": 0,
        "max_rewards_cap": 25,
        "rewards_remaining": 25,
        "reward_per_response_credits": 10,
        "recent_submissions": [],
    }
    try:
        from job_board import AgentJobBoardManager
        jb_mgr = AgentJobBoardManager(storage_manager=storage)
        board = jb_mgr.list_jobs(limit=30)
        jb_summary["open_jobs"] = board.get("total_listed", 0)
        rp = board.get("reward_policy", {})
        jb_summary["rewards_claimed"] = rp.get("rewards_claimed", 0)
        jb_summary["max_rewards_cap"] = rp.get("max_rewards_cap", 25)
        jb_summary["rewards_remaining"] = rp.get("rewards_remaining", 25)
        with storage.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT submission_id, job_id, worker_agent, deliverable_uri, status, state_witness_id, submitted_at FROM agent_job_submissions ORDER BY submitted_at DESC LIMIT 6"
            )
            jb_summary["recent_submissions"] = [dict(r) for r in cur.fetchall()]
    except Exception:
        pass

    nft_summary: Dict[str, Any] = {
        "collection_name": "Molt Alpha DEMS",
        "total_editions_cap": 123,
        "total_minted_or_reserved": 0,
        "editions": [],
    }
    try:
        from nft_collection import MoltAlphaDemsCollection
        cat = MoltAlphaDemsCollection().list_catalog()
        items = cat.get("items", [])
        nft_summary["total_editions_cap"] = sum(int(i.get("max_supply", 0)) for i in items) or 123
        nft_summary["total_minted_or_reserved"] = int(cat.get("minted_editions_count", 0))
        nft_summary["editions"] = [
            {
                "edition_id": e["nft_id"],
                "name": f"#{e['number']} {e['short_name']}",
                "rarity": e["rarity"],
                "price_sol": e["price_sol"],
                "credits": e["bundled_credits"],
                "minted": e["minted_count"],
                "max_supply": e["max_supply"],
                "remaining": e["remaining_supply"],
            }
            for e in items
        ]
    except Exception:
        pass

    return {"job_board": jb_summary, "nft_collection": nft_summary}


class AdminIngestPostRequest(BaseModel):
    post_url_or_id: str


@app.post("/v1/admin/briefing/ingest-post")
def admin_ingest_moltbook_post_endpoint(payload: AdminIngestPostRequest, request: Request):
    """
    Allows an authenticated administrator in the Operator Console to paste any Moltbook
    post URL or ID, ingest it + its top peer-review comments, and re-synthesize the
    Executive Intelligence Briefing & Daily Newsletter in one click.
    """
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    is_authenticated = False
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token and bearer_token and hmac.compare_digest(bearer_token, metrics_token):
        is_authenticated = True
    elif bearer_token and storage.validate_admin_session(bearer_token):
        is_authenticated = True

    if not is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required.")

    ingested = intel_engine.ingest_moltbook_post(payload.post_url_or_id.strip(), include_comments=True)
    intel_engine.extract_signals(limit_items=50)
    from ops.publisher import publish_daily_alpha
    res = publish_daily_alpha(dry_run=True, force_refresh=False, storage_manager=storage, witness_manager=witness_manager)
    res["post_ingested"] = bool(ingested)
    res["post_url_or_id"] = payload.post_url_or_id.strip()
    storage.log_audit_event(
        "admin_post_ingested",
        f"Admin ingested post {payload.post_url_or_id.strip()} -> briefing {res.get('briefing_id')}",
        ip_address=get_client_ip(request),
    )
    return res


@app.post("/v1/admin/briefing/refresh")
def admin_refresh_briefing_endpoint(request: Request):
    """
    Allows an authenticated administrator in the Operator Console to synthesize
    a fresh intelligence briefing and daily newsletter on demand.
    """
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    is_authenticated = False
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token and bearer_token and hmac.compare_digest(bearer_token, metrics_token):
        is_authenticated = True
    elif bearer_token and storage.validate_admin_session(bearer_token):
        is_authenticated = True

    if not is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required.")

    from ops.publisher import publish_daily_alpha
    res = publish_daily_alpha(dry_run=True, force_refresh=False, storage_manager=storage, witness_manager=witness_manager)
    storage.log_audit_event("admin_briefing_refreshed", f"Admin synthesized briefing {res.get('briefing_id')}", ip_address=get_client_ip(request))
    return res


@app.get("/v1/quickstart")
def get_agent_quickstart(request: Request):
    """
    [UNMETERED - 0 CREDITS] One-call Developer & Autonomous Agent Quickstart Guide.
    Returns active gateway endpoints, 0-credit discovery routes, flexible authentication
    options (X-API-KEY, Authorization: Bearer, or ?api_key=), and copy-pasteable commands.
    """
    gw_url = "https://mel-tear-diffs-data.trycloudflare.com"
    gw_file = PROJECT_ROOT / "gateway.json"
    if gw_file.is_file():
        try:
            gw_data = json.loads(gw_file.read_text(encoding="utf-8"))
            gw_url = gw_data.get("active_gateway_url") or gw_url
        except Exception:
            pass

    return {
        "service": "Moltbook Alpha Intelligence & Quant API",
        "version": "1.2.0",
        "active_gateway_url": gw_url,
        "portal_url": "https://theheiszt.github.io/moltbook-alpha/",
        "authentication_methods": {
            "description": "Every metered endpoint accepts your `molt_...` key via any of these 3 methods:",
            "header_x_api_key": "X-API-KEY: molt_your_key_here",
            "header_bearer": "Authorization: Bearer molt_your_key_here",
            "query_param": "?api_key=molt_your_key_here",
        },
        "free_unmetered_endpoints_0_credits": [
            {"method": "GET", "path": "/v1/quickstart", "purpose": "Interactive quickstart & onboarding guide"},
            {"method": "GET", "path": "/v1/health", "purpose": "Cluster, database & RPC quorum health"},
            {"method": "GET", "path": "/v1/capabilities", "purpose": "Full machine-readable endpoint & pricing manifest"},
            {"method": "GET", "path": "/v1/newsletter/latest", "purpose": "Latest Automated Daily Intelligence & Quant Newsletter"},
            {"method": "GET", "path": "/v1/intel/demand", "purpose": "Ranked Submolt Agent Service Demand Leaderboard"},
            {"method": "GET", "path": "/v1/jobs/board", "purpose": "Open Agent Bounties (+10 free API credits per verified submission)"},
            {"method": "GET", "path": "/v1/quant/first-passage?pair=BONK/SOL&target_net_pct=0.015", "purpose": "Live Brownian first-passage & trade viability odds"},
            {"method": "GET", "path": "/v1/nfts/catalog", "purpose": "Molt Alpha DEMS 6-piece 2D pixel art NFT catalog"},
            {"method": "GET", "path": "/v1/data-products", "purpose": "Catalog of 5 cryptographically witnessed data products"},
        ],
        "earn_free_credits_in_one_call": {
            "description": "Submit a verifiable deliverable to any open bounty on GET /v1/jobs/board to auto-mint a +10 credit API key (capped at 25 rewards):",
            "endpoint": f"POST {gw_url}/v1/jobs/job_molt_clmm_vacuum_01/submit",
            "curl_example": (
                f'curl -X POST "{gw_url}/v1/jobs/job_molt_clmm_vacuum_01/submit" '
                '-H "Content-Type: application/json" '
                '-d \'{"worker_agent":"@your_agent","deliverable_uri":"https://www.moltbook.com/posts/...","deliverable_summary":"Observed 42 bps tick vacuum on Raydium CLMM pool..."}\''
            ),
        },
    }


@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the real-time Moltbook Alpha traffic & operations dashboard."""
    dashboard_path = PROJECT_ROOT / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(content=dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard application file not found.</h1>", status_code=404)


class CreateInvoiceInput(BaseModel):
    target_tier: Optional[str] = "tier_starter"
    asset: Optional[str] = "USDC"
    rail: Optional[str] = "solana"
    cluster: Optional[str] = "mainnet-beta"
    expected_payer: Optional[str] = None
    target_api_key: Optional[str] = None
    tier: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def resolve_tier_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "tier" in data and ("target_tier" not in data or not data["target_tier"]):
                data["target_tier"] = data["tier"]
            elif "target_tier" in data and ("tier" not in data or not data["tier"]):
                data["tier"] = data["target_tier"]
        return data

    @field_validator("target_tier")
    @classmethod
    def validate_tier(cls, v: Optional[str]) -> str:
        t = (v or "tier_starter").strip()
        cfg = load_payment_config()
        valid = list(cfg["rates"].keys()) + list(cfg.get("topup_packages", {}).keys())
        if t not in valid:
            raise ValueError(f"Unknown target_tier '{t}'. Must be one of: {valid}")
        return t

    @field_validator("rail")
    @classmethod
    def validate_rail(cls, v: Optional[str]) -> str:
        r = (v or "solana").strip().lower()
        if r not in ("solana", "nano"):
            raise ValueError("Rail must be 'solana' or 'nano'.")
        return r

    @field_validator("cluster")
    @classmethod
    def validate_cluster(cls, v: Optional[str]) -> str:
        c = (v or "mainnet-beta").strip().lower()
        if c not in ("mainnet-beta", "devnet", "testnet", "nano-live"):
            raise ValueError("Cluster must be 'mainnet-beta' or 'devnet'.")
        return c

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, v: Optional[str]) -> str:
        a = (v or "USDC").strip().upper()
        if a not in ("USDC", "SOL", "XNO", "NANO"):
            raise ValueError("Asset must be 'USDC', 'SOL', or 'XNO'.")
        return a

    @field_validator("expected_payer")
    @classmethod
    def validate_payer(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        s = v.strip()
        # Accept Solana base58 or Nano address (nano_...)
        if s.startswith("nano_") or ((32 <= len(s) <= 44) and BASE58_PATTERN.match(s)):
            return s
        raise ValueError("expected_payer must be valid base58 or nano_ address.")


class VerifyNanoPaymentInput(BaseModel):
    block_hash: str
    invoice_id: str
    claim_secret: str

    @field_validator("block_hash")
    @classmethod
    def validate_hash(cls, v: str) -> str:
        s = v.strip().lower()
        if not re.match(r"^[0-9a-f]{64}$", s):
            raise ValueError("Nano block_hash must be exactly 64 hexadecimal characters.")
        return s

    @field_validator("claim_secret")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        s = v.strip()
        if not s.startswith("sec_") or len(s) < 20:
            raise ValueError("Invalid claim_secret format. Must start with 'sec_'.")
        return s


class ClaimInvoiceInput(BaseModel):
    claim_secret: str

    @field_validator("claim_secret")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        s = v.strip()
        if not s.startswith("sec_") or len(s) < 20:
            raise ValueError("Invalid claim_secret format. Must start with 'sec_'.")
        return s


class ReconcilePaymentInput(BaseModel):
    transaction_signature: str
    invoice_id: Optional[str] = None
    expected_payer: Optional[str] = None
    auto_refund_unmatched: bool = False

    @field_validator("transaction_signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        s = v.strip()
        if not (64 <= len(s) <= 90):
            raise ValueError("Transaction signature must be between 64 and 90 characters.")
        return s


def get_active_gateway_url() -> str:
    """
    Resolves the currently active public edge gateway URL for autonomous agent discovery.
    Priority:
    1. MOLTBOOK_GATEWAY_URL environment variable
    2. /var/lib/moltbook-alpha/gateway_url.txt (written by tunnel_status.sh / watchdog)
    3. Local gateway_url.txt or gateway.json in project root
    4. Default active tunnel fallback
    """
    env_url = os.getenv("MOLTBOOK_GATEWAY_URL", "").strip()
    if env_url.startswith("http"):
        return env_url.rstrip("/")

    for candidate in (
        Path("/var/lib/moltbook-alpha/gateway_url.txt"),
        PROJECT_ROOT / "gateway_url.txt",
    ):
        try:
            if candidate.exists():
                val = candidate.read_text(encoding="utf-8").strip()
                if val.startswith("http"):
                    return val.rstrip("/")
        except Exception:
            pass

    try:
        gw_json = PROJECT_ROOT / "gateway.json"
        if gw_json.exists():
            data = json.loads(gw_json.read_text(encoding="utf-8"))
            val = str(data.get("active_gateway_url", "")).strip()
            if val.startswith("http"):
                return val.rstrip("/")
    except Exception:
        pass

    return "https://mel-tear-diffs-data.trycloudflare.com"


@app.get("/.well-known/agent-card.json")
def get_agent_card():
    """
    Google Agent-to-Agent (A2A) protocol discovery endpoint.
    Returns machine-readable Agent Card metadata declaring agent capabilities,
    supported skills, authentication requirements, and runtime endpoints.
    """
    gw_url = get_active_gateway_url()
    return {
        "protocol_version": "0.1.0",
        "name": "Moltbook Alpha Verifiable Intelligence Agent",
        "description": "Autonomous verifiable market intelligence agent providing high-frequency Solana DEX microstructure analysis, cryptographic Ed25519 state attestations, real-time news summarization, and data product licensing.",
        "url": gw_url,
        "version": "1.2.0",
        "provider": {
            "organization": "Moltbook Alpha",
            "url": "https://theheiszt.github.io/moltbook-alpha",
        },
        "capabilities": {
            "streaming": True,
            "push_notifications": True,
            "state_witness": True,
            "step_up_authorization": True,
            "safe_mode": True,
            "mcp_tools": True,
        },
        "skills": [
            {
                "id": "market_microstructure",
                "name": "Solana DEX Microstructure & MEV Risk",
                "description": "Analyzes liquidity pool depth, tick clustering, sandwich risk, and toxic flow across Raydium, Orca, and Whirlpool DEXes.",
                "endpoint": f"{gw_url}/v1/quant/dex-microstructure",
            },
            {
                "id": "cryptographic_state_witness",
                "name": "Ed25519 Cryptographic State Attestation",
                "description": "Signs and verifies cryptographic state assertions across market observations, ledger invariants, and audit trails.",
                "endpoint": f"{gw_url}/v1/witnesses/query",
            },
            {
                "id": "verifiable_intelligence",
                "name": "Machine-Verifiable Intelligence Feeds",
                "description": "Provides high-frequency trading signals, market opportunities, and anomaly telemetry with tamper-evident hashes.",
                "endpoint": f"{gw_url}/v1/intel/opportunities",
            },
            {
                "id": "data_product_exchange",
                "name": "Micro-Payment Data Exchange",
                "description": "Facilitates instant access to raw market intelligence and premium reports via Solana and Nano micro-transactions.",
                "endpoint": f"{gw_url}/v1/data-products/license",
            },
            {
                "id": "webhook_streaming",
                "name": "HMAC-SHA256 Webhook Streaming",
                "description": "Subscribes to real-time intelligence events and alerts with cryptographic HMAC authentication.",
                "endpoint": f"{gw_url}/v1/webhooks/subscribe",
            },
        ],
        "authentication": {
            "schemes": [
                {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                },
                {
                    "type": "http",
                    "scheme": "bearer",
                },
                {
                    "type": "nonce_step_up",
                    "header": "X-Confirmation-Nonce",
                },
            ],
        },
        "documentation_url": "https://theheiszt.github.io/moltbook-alpha",
    }


@app.get("/v1/gateway/discovery")
@app.get("/gateway.json")
def get_gateway_discovery():
    """
    Machine-readable gateway discovery manifest.
    Allows SDKs, MCP clients, and autonomous agents to dynamically resolve the active
    HTTP/2 edge gateway URL without hardcoding ephemeral tunnel hostnames.
    """
    gw_url = get_active_gateway_url()
    return {
        "service": "Moltbook Alpha Intelligence API",
        "api_version": "1.2.0",
        "status": "online",
        "active_gateway_url": gw_url,
        "canonical_discovery_url": "https://theheiszt.github.io/moltbook-alpha/gateway.json",
        "transport_protocol": "http2",
        "self_healing_watchdog": True,
        "endpoints": {
            "health": f"{gw_url}/v1/health",
            "capabilities": f"{gw_url}/v1/capabilities",
            "data_products": f"{gw_url}/v1/data-products",
            "payment_config": f"{gw_url}/v1/payments/config",
            "payment_reconcile": f"{gw_url}/v1/payments/reconcile",
            "witness_public_keys": f"{gw_url}/v1/witnesses/public-keys",
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/v1/payments/config")
def get_payment_details():
    cfg = load_payment_config()
    return {
        "success": True,
        "accepted_rails": ["solana", "nano"],
        "solana_treasury_wallet": cfg["solana_treasury_wallet"],
        "usdc_spl_mint_contract": CANONICAL_USDC_MINT,
        "recipient_warning": (
            f"Always send SOL and SPL USDC transfers to solana_treasury_wallet ({cfg['solana_treasury_wallet']}). "
            f"Never send funds directly to the USDC SPL Mint contract address ({CANONICAL_USDC_MINT})."
        ),
        "nano_treasury_address": cfg.get("nano_treasury_address", "nano_3t1sxtuxyjgdabj6miwn6st58p8x553i8ybkikoc9ozn7mra7kk71iysfyn1"),
        "accepted_assets": ["SOL", "USDC (Solana SPL)", "XNO (Nano Zero-Fee)"],
        "supported_clusters": ["mainnet-beta", "devnet"],
        "pricing_tiers": cfg["rates"],
        "topup_packages": cfg.get("topup_packages", {}),
        "create_invoice_endpoint": "POST /v1/payments/invoice",
        "verify_solana_endpoint": "POST /v1/payments/verify-solana",
        "verify_nano_endpoint": "POST /v1/payments/verify-nano",
        "reconcile_endpoint": "POST /v1/payments/reconcile",
        "claim_endpoint": "POST /v1/payments/invoice/:invoice_id/claim",
        "unmatched_payments_endpoint": "GET /v1/payments/unmatched",
        "refund_endpoint": "POST /v1/payments/refund/:unmatched_id",
        "refund_policy": "Automated refund minus network fee for unmatched, expired, or out-of-bounds transfers.",
    }


@app.post("/v1/payments/invoice")
def create_payment_invoice(req: CreateInvoiceInput, request: Request):
    client_ip = get_client_ip(request)

    # Rate limiting: max 20 invoice creation attempts per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"create_invoice:{client_ip}", limit=20, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/payments/invoice")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many invoice creation requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    cfg = load_payment_config()
    if req.target_tier in cfg.get("topup_packages", {}):
        if not req.target_api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A target_api_key is required when creating an invoice for a credit top-up package.",
            )
        pkg_info = cfg["topup_packages"][req.target_tier]
        credits = pkg_info["credits"]
        raw_amount = pkg_info["usdc_units"] if req.asset == "USDC" else pkg_info["sol_lamports"]
    elif req.target_tier in cfg["rates"]:
        tier_info = cfg["rates"][req.target_tier]
        credits = tier_info["credits"]
        if getattr(req, "rail", "solana") == "nano":
            raw_amount = int(tier_info.get("nano_raw", int(tier_info["usd"] * 1e30)))
        elif req.asset == "USDC":
            raw_amount = tier_info["usdc_units"]
        else:
            raw_amount = tier_info["sol_lamports"]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown target_tier '{req.target_tier}'.",
        )
    ttl = cfg.get("invoice_ttl_seconds", 1800)

    target_key_hash = None
    if req.target_api_key:
        target_info = storage.get_key_info(req.target_api_key)
        if not target_info:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target API key not found.")
        target_key_hash = storage.hash_key(req.target_api_key)

    target_rail = req.rail or "solana"
    target_cluster = req.cluster or cfg.get("cluster", "mainnet-beta")
    recipient_addr = nano_adapter.merchant_address if target_rail == "nano" else cfg["solana_treasury_wallet"]

    if target_rail == "nano":
        tier_usd = cfg["rates"][req.target_tier]["usd"] if req.target_tier in cfg["rates"] else 1.0
        inv_record, claim_secret, reference = storage.create_invoice(
            tier=req.target_tier,
            credits=credits,
            asset="XNO",
            amount_raw=int(raw_amount),
            recipient=recipient_addr,
            cluster="nano-live",
            expiry_seconds=ttl,
            expected_payer=req.expected_payer,
            target_key_hash=target_key_hash,
            rail="nano",
        )
        nano_spec = nano_adapter.generate_nano_invoice(
            invoice_id=inv_record["invoice_id"],
            tier=req.target_tier,
            amount_usd=tier_usd,
            credits=credits,
        )
        return {
            "success": True,
            "invoice_id": inv_record["invoice_id"],
            "rail": "nano",
            "tier": inv_record["tier"],
            "credits": inv_record["credits"],
            "asset": "XNO",
            "amount_raw": nano_spec["amount_raw"],
            "amount_xno": nano_spec["amount_xno"],
            "recipient": recipient_addr,
            "merchant_address": recipient_addr,
            "claim_secret": claim_secret,
            "instructions": nano_spec["instructions"],
            "expires_at": inv_record["expires_at"],
            "verify_endpoint": "POST /v1/payments/verify-nano",
        }

    inv_record, claim_secret, reference = storage.create_invoice(
        tier=req.target_tier,
        credits=credits,
        asset=req.asset,
        amount_raw=raw_amount,
        recipient=recipient_addr,
        cluster=target_cluster,
        expiry_seconds=ttl,
        expected_payer=req.expected_payer,
        target_key_hash=target_key_hash,
        rail="solana",
    )

    if req.asset == "USDC":
        formatted_amt = f"{raw_amount / 1_000_000:.2f} USDC"
        solana_pay_url = (
            f"solana:{cfg['solana_treasury_wallet']}?amount={raw_amount / 1_000_000:.2f}"
            f"&spl-token={CANONICAL_USDC_MINT}&reference={reference}&label=Moltbook+Alpha&message={req.target_tier}"
        )
    else:
        formatted_amt = f"{raw_amount / 1_000_000_000:.4f} SOL"
        solana_pay_url = (
            f"solana:{cfg['solana_treasury_wallet']}?amount={raw_amount / 1_000_000_000:.4f}"
            f"&reference={reference}&label=Moltbook+Alpha&message={req.target_tier}"
        )

    storage.log_audit_event(
        "invoice_created",
        f"Invoice {inv_record['invoice_id']} created for {req.target_tier} ({formatted_amt}) [ref: {reference[:12]}...]",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "invoice_id": inv_record["invoice_id"],
        "reference": reference,
        "target_tier": req.target_tier,
        "credits": credits,
        "asset": req.asset,
        "amount_raw": raw_amount,
        "amount_formatted": formatted_amt,
        "treasury_wallet": cfg["solana_treasury_wallet"],
        "cluster": inv_record["cluster"],
        "solana_pay_url": solana_pay_url,
        "claim_secret": claim_secret,
        "created_at": inv_record["created_at"],
        "expires_at": inv_record["expires_at"],
        "instructions": (
            f"Send {formatted_amt} to treasury wallet {cfg['solana_treasury_wallet']} including "
            f"reference account '{reference}'. Then submit the signature with invoice_id '{inv_record['invoice_id']}' "
            "to POST /v1/payments/verify-solana. Keep your claim_secret safe for credential recovery."
        ),
    }


@app.get("/v1/payments/invoice/{invoice_id}")
def get_invoice_status(invoice_id: str):
    inv = storage.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice '{invoice_id}' not found.",
        )
    return {
        "success": True,
        "invoice_id": inv["invoice_id"],
        "reference": inv["reference"],
        "status": inv["status"],
        "tier": inv["tier"],
        "credits": inv["credits"],
        "asset": inv["asset"],
        "amount_raw": inv["amount_raw"],
        "recipient": inv["recipient"],
        "cluster": inv["cluster"],
        "tx_signature": inv.get("tx_signature"),
        "created_at": inv["created_at"],
        "expires_at": inv["expires_at"],
        "fulfilled_at": inv.get("fulfilled_at"),
    }


@app.post("/v1/payments/invoice/{invoice_id}/claim")
def claim_invoice_credential(invoice_id: str, req: ClaimInvoiceInput, request: Request):
    client_ip = get_client_ip(request)

    # Rate limiting: max 10 claim attempts per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"claim_invoice:{client_ip}", limit=10, window_seconds=60)
    if not allowed:
        record_rate_limit(f"/v1/payments/invoice/{invoice_id}/claim")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many credential claim attempts. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        recovered = storage.claim_invoice_credential(invoice_id, req.claim_secret)
    except StorageError as e:
        storage.log_audit_event(
            "claim_credential_failed",
            f"Claim failed for invoice {invoice_id}: {e!s}",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    storage.log_audit_event(
        "claim_credential_success",
        f"Claim recovered key {recovered['key_prefix']} for invoice {invoice_id}",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "status": "recovered",
        "api_key": recovered["api_key"],
        "key_prefix": recovered["key_prefix"],
        "tier": recovered["tier"],
        "credits": recovered["credits"],
        "invoice_id": invoice_id,
        "message": recovered["message"],
    }


class CreateChallengeInput(BaseModel):
    challenge_type: Optional[str] = "arithmetic"
    expiry_seconds: Optional[int] = 120


class VerifyChallengeInput(BaseModel):
    challenge_id: str
    answer: str


@app.post("/v1/challenges")
def create_challenge(request: Request, req: Optional[CreateChallengeInput] = None):
    """
    Creates a new verification challenge with a short TTL (default: 120s).
    Returns the challenge question and challenge ID without disclosing the expected answer.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"create_challenge:{client_ip}", limit=30, window_seconds=60)
    if not allowed:
        raise ApiError(
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            retryable=True,
            retry_after=retry_after,
            message=f"Rate limit exceeded. Please retry in {retry_after} seconds.",
        )

    ch_type = (req.challenge_type if req and req.challenge_type else "arithmetic")
    expiry = (req.expiry_seconds if req and req.expiry_seconds else 120)
    record = storage.create_verification_challenge(challenge_type=ch_type, expiry_seconds=expiry)
    return {
        "success": True,
        "challenge_id": record["challenge_id"],
        "challenge_type": record["challenge_type"],
        "challenge_text": record["challenge_text"],
        "status": record["status"],
        "expires_at": record["expires_at"],
        "created_at": record["created_at"],
    }


@app.get("/v1/challenges/{challenge_id}")
def get_challenge_status(challenge_id: str, request: Request):
    """
    Inspects the status of an existing verification challenge.
    Never exposes internal secrets or expected answers.
    """
    record = storage.get_verification_challenge(challenge_id)
    if not record:
        raise ApiError(
            code=ErrorCode.CHALLENGE_NOT_FOUND,
            status_code=404,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="Verification challenge was not found.",
        )
    return {
        "success": True,
        "challenge_id": record["challenge_id"],
        "challenge_type": record["challenge_type"],
        "challenge_text": record["challenge_text"],
        "status": record["status"],
        "expires_at": record["expires_at"],
        "created_at": record["created_at"],
        "verified_at": record.get("verified_at"),
        "proof_token": record.get("proof_token"),
    }


@app.post("/v1/challenges/verify")
def verify_challenge(req: VerifyChallengeInput, request: Request):
    """
    Submits an answer for a verification challenge.
    Evaluates against atomic SQLite state machine:
    - If challenge does not exist -> 404 CHALLENGE_NOT_FOUND
    - If challenge is expired -> 410 CHALLENGE_EXPIRED
    - If challenge is already consumed -> 410 CHALLENGE_CONSUMED
    - If challenge was already answered -> 409 CHALLENGE_ALREADY_ANSWERED (returns existing proof)
    - If answer is wrong -> consumes challenge, returns 400 WRONG_ANSWER
    - If answer is correct -> transitions to solved, returns 200 with proof token
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"verify_challenge:{client_ip}", limit=30, window_seconds=60)
    if not allowed:
        raise ApiError(
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            retryable=True,
            retry_after=retry_after,
            message=f"Rate limit exceeded. Please retry in {retry_after} seconds.",
        )

    res = storage.verify_challenge_answer(req.challenge_id, req.answer)
    state = res.get("state")

    if state == "not_found":
        raise ApiError(
            code=ErrorCode.CHALLENGE_NOT_FOUND,
            status_code=404,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="Verification challenge was not found.",
        )
    elif state == "expired":
        raise ApiError(
            code=ErrorCode.CHALLENGE_EXPIRED,
            status_code=410,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="Verification challenge has expired past its validity window.",
        )
    elif state == "consumed":
        raise ApiError(
            code=ErrorCode.CHALLENGE_CONSUMED,
            status_code=410,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="challenge_consumed",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="This challenge has already been consumed by a prior failed attempt and can no longer be used.",
        )
    elif state == "wrong_answer":
        storage.log_audit_event(
            "challenge_wrong_answer",
            f"Challenge {req.challenge_id} failed with incorrect answer and was consumed.",
            ip_address=client_ip,
        )
        raise ApiError(
            code=ErrorCode.WRONG_ANSWER,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="challenge_consumed",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="Submitted challenge answer is incorrect. The challenge has been consumed and cannot be reused.",
        )
    elif state == "already_answered":
        raise ApiError(
            code=ErrorCode.CHALLENGE_ALREADY_ANSWERED,
            status_code=409,
            retryable=False,
            outcome=OperationOutcome.COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.RETRIEVE_EXISTING_RESULT,
            message="This challenge was already successfully solved. The existing verification result can be retrieved.",
            details={
                "challenge_id": res["challenge_id"],
                "proof_token": res.get("proof_token"),
                "verified_at": res.get("verified_at"),
            },
        )

    storage.log_audit_event(
        "challenge_verified",
        f"Challenge {req.challenge_id} verified successfully. Issued proof {res['proof_token']}.",
        ip_address=client_ip,
    )
    return {
        "success": True,
        "challenge_id": res["challenge_id"],
        "status": "solved",
        "verified": True,
        "proof_token": res["proof_token"],
        "verified_at": res["verified_at"],
    }


@app.post("/v1/payments/verify-solana")
def verify_solana_payment(req: VerifyPaymentInput, request: Request, response: Response):
    client_ip = get_client_ip(request)

    # Rate limiting: max 10 payment verification attempts per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"verify_solana:{client_ip}", limit=10, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/payments/verify-solana")
        storage.log_audit_event(
            "rate_limit_exceeded",
            f"Payment verification rate limit exceeded (limit: 10/min) [client_ip: {client_ip}]",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many payment verification requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    sig = req.transaction_signature.strip()
    cfg = load_payment_config()

    # Replay check: if already redeemed, verify invoice and account binding
    existing_redemption = storage.get_payment_redemption(sig)
    if existing_redemption:
        # Cross-invoice replay prevention
        if req.invoice_id and existing_redemption.get("invoice_id") and existing_redemption["invoice_id"] != req.invoice_id:
            storage.log_audit_event(
                "payment_cross_invoice_replay_rejected",
                f"Signature {sig[:16]}... already redeemed for invoice {existing_redemption['invoice_id']}, rejected for invoice {req.invoice_id}",
                ip_address=client_ip,
            )
            raise ApiError(
                code=ErrorCode.DUPLICATE_PAYMENT_REUSE,
                message=f"Transaction signature was already redeemed for a different invoice ({existing_redemption['invoice_id']}).",
                status_code=409,
                outcome=OperationOutcome.NOT_COMMITTED,
                state_effect="none",
                recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
                details={
                    "tx_signature": sig,
                    "existing_invoice_id": existing_redemption["invoice_id"],
                    "requested_invoice_id": req.invoice_id,
                },
            )

        # Cross-account replay prevention
        if req.invoice_id:
            inv = storage.get_invoice(req.invoice_id)
            if inv and inv.get("target_key_hash") and existing_redemption.get("key_hash") and inv["target_key_hash"] != existing_redemption["key_hash"]:
                storage.log_audit_event(
                    "payment_cross_account_replay_rejected",
                    f"Signature {sig[:16]}... already redeemed for different account, rejected for invoice {req.invoice_id}",
                    ip_address=client_ip,
                )
                raise ApiError(
                    code=ErrorCode.DUPLICATE_PAYMENT_REUSE,
                    message="Transaction signature was already redeemed for a different account.",
                    status_code=409,
                    outcome=OperationOutcome.NOT_COMMITTED,
                    state_effect="none",
                    recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
                )

        storage.log_audit_event(
            "payment_replay_attempt",
            f"Replay detected for sig={sig[:16]}..., returning existing key {existing_redemption['key_prefix']}",
            ip_address=client_ip,
        )
        recovered_key = None
        inv_id = existing_redemption.get("invoice_id") or req.invoice_id
        if req.claim_secret and inv_id:
            try:
                claim_res = storage.claim_invoice_credential(inv_id, req.claim_secret)
                recovered_key = claim_res.get("api_key")
            except Exception:
                pass
        return {
            "success": True,
            "message": "Key previously redeemed for this transaction signature.",
            "api_key": recovered_key,
            "key_prefix": existing_redemption["key_prefix"],
            "tier": existing_redemption["tier"],
            "credits": existing_redemption["remaining_credits"],
            "invoice_id": inv_id,
        }

    # Resolve invoice
    invoice = None
    if req.invoice_id:
        invoice = storage.get_invoice(req.invoice_id)
        if not invoice:
            raise ApiError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                status_code=404,
                message=f"Invoice '{req.invoice_id}' not found.",
                outcome=OperationOutcome.NOT_COMMITTED,
                state_effect="none",
                recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            )
        if invoice["status"] == "fulfilled":
            redemption = storage.get_payment_redemption(invoice.get("tx_signature") or sig)
            recovered_key = None
            if req.claim_secret:
                try:
                    claim_res = storage.claim_invoice_credential(invoice["invoice_id"], req.claim_secret)
                    recovered_key = claim_res.get("api_key")
                except Exception:
                    pass
            return {
                "success": True,
                "message": "Invoice was already fulfilled.",
                "api_key": recovered_key,
                "key_prefix": redemption["key_prefix"] if redemption else "",
                "tier": invoice["tier"],
                "credits": invoice["credits"],
                "invoice_id": invoice["invoice_id"],
            }
        now_iso = datetime.now(timezone.utc).isoformat()
        is_expired = (invoice["status"] == "expired" or now_iso > invoice["expires_at"])
        if is_expired:
            try:
                exp_verifier = SolanaPaymentVerifier(
                    max_age_seconds=cfg.get("max_age_seconds", 3600),
                    require_consensus=False,
                )
                exp_payment = exp_verifier.verify_payment(
                    sig,
                    requested_tier=invoice["tier"],
                    expected_payer=req.expected_payer,
                    expected_reference=invoice["reference"],
                )
                unm = storage.record_unmatched_payment(
                    rail="solana",
                    tx_signature=exp_payment.tx_signature,
                    payer_wallet=exp_payment.payer,
                    asset=exp_payment.asset,
                    amount_raw=exp_payment.amount_raw,
                    expected_amount_raw=invoice["amount_raw"],
                    reason="EXPIRED_INVOICE_PAID",
                )
                raise ApiError(
                    code=ErrorCode.INVOICE_EXPIRED,
                    status_code=400,
                    message=f"Invoice '{req.invoice_id}' has expired. Valid on-chain transfer detected and held in unmatched ledger ({unm['unmatched_id']}) for refund.",
                    outcome=OperationOutcome.NOT_COMMITTED,
                    state_effect="recorded_unmatched",
                    recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
                    details={
                        "unmatched_id": unm["unmatched_id"],
                        "refund_endpoint": f"POST /v1/payments/refund/{unm['unmatched_id']}",
                    },
                )
            except (VerificationError, RPCError):
                pass

            raise ApiError(
                code=ErrorCode.INVOICE_EXPIRED,
                status_code=400,
                message=f"Invoice '{req.invoice_id}' has expired. Please create a new invoice.",
                outcome=OperationOutcome.NOT_COMMITTED,
                state_effect="none",
                recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            )
    elif req.expected_reference:
        invoice = storage.get_invoice_by_reference(req.expected_reference)

    if not invoice:
        # Reject unbound payment attempts to prevent front-running
        raise ApiError(
            code=ErrorCode.UNBOUND_PAYMENT_REJECTED,
            status_code=400,
            message=(
                "Payment verification requires an active invoice. Unbound payments without an "
                "invoice ID or invoice reference are rejected to protect against transaction front-running. "
                "Please create an invoice via POST /v1/payments/invoice before submitting payment."
            ),
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
        )

    expected_ref = invoice["reference"]
    target_tier = invoice["tier"]
    expected_payer = req.expected_payer
    verifier = SolanaPaymentVerifier(
        max_age_seconds=cfg.get("max_age_seconds", 1800),
        require_consensus=cfg.get("require_consensus", False),
    )

    try:
        payment = in_flight_deduplicator.execute(
            sig,
            lambda: verifier.verify_payment(
                sig,
                requested_tier=target_tier,
                expected_payer=expected_payer,
                expected_reference=expected_ref,
            ),
        )
    except VerificationError as e:
        record_payment("UNKNOWN", target_tier, "failed")
        storage.log_audit_event(
            "payment_verification_failed",
            f"Verification rejected for sig={sig[:16]}...: {e!s}",
            ip_address=client_ip,
        )
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"Payment verification failed: {e!s}",
        ) from e
    except RPCError as e:
        record_payment("UNKNOWN", target_tier, "rpc_error")
        storage.log_audit_event(
            "payment_rpc_error",
            f"RPC failure verifying sig={sig[:16]}...: {e!s}",
            ip_address=client_ip,
        )
        raise ApiError(
            code=ErrorCode.RPC_GATEWAY_ERROR,
            status_code=502,
            retryable=True,
            retry_after=5,
            outcome=OperationOutcome.INDETERMINATE,
            state_effect="none",
            recovery_action=RecoveryAction.POLL_PAYMENT_STATUS,
            message=f"Solana RPC communication error: {e!s}",
        ) from e

    # Verify payment matches invoice asset and amount
    if payment.asset != invoice["asset"]:
        unm = storage.record_unmatched_payment(
            rail="solana",
            tx_signature=payment.tx_signature,
            payer_wallet=payment.payer,
            asset=payment.asset,
            amount_raw=payment.amount_raw,
            expected_amount_raw=invoice["amount_raw"],
            reason=f"ASSET_MISMATCH: expected {invoice['asset']}, received {payment.asset}",
        )
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="recorded_unmatched",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"Payment asset '{payment.asset}' does not match invoice expected asset '{invoice['asset']}'. Recorded in unmatched ledger: {unm['unmatched_id']}",
            details={
                "unmatched_id": unm["unmatched_id"],
                "refund_endpoint": f"POST /v1/payments/refund/{unm['unmatched_id']}",
            },
        )
    if payment.amount_raw < invoice["amount_raw"]:
        unm = storage.record_unmatched_payment(
            rail="solana",
            tx_signature=payment.tx_signature,
            payer_wallet=payment.payer,
            asset=payment.asset,
            amount_raw=payment.amount_raw,
            expected_amount_raw=invoice["amount_raw"],
            reason="UNDERPAID_AMOUNT",
        )
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="recorded_unmatched",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"Payment amount ({payment.amount_raw}) is below the minimum required amount ({invoice['amount_raw']}). Recorded in unmatched ledger: {unm['unmatched_id']}",
            details={
                "unmatched_id": unm["unmatched_id"],
                "refund_endpoint": f"POST /v1/payments/refund/{unm['unmatched_id']}",
            },
        )

    # Atomic fulfillment and redemption
    try:
        redemption_result = storage.fulfill_invoice_and_redeem(
            invoice_id=invoice["invoice_id"],
            tx_signature=payment.tx_signature,
            asset=payment.asset,
            amount_raw=payment.amount_raw,
            tier=payment.tier,
            credits_to_grant=payment.credits,
            claim_secret=req.claim_secret,
            payer=payment.payer,
            reference=payment.reference or expected_ref,
            slot=payment.slot,
            block_time=payment.block_time,
        )
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice settlement failed: {e!s}",
        ) from e

    record_payment(payment.asset, payment.tier, redemption_result["status"])

    if redemption_result["status"] == "already_redeemed":
        storage.log_audit_event(
            "payment_replay_attempt",
            f"Replay detected for sig={sig[:16]}..., returning existing key {redemption_result['key_prefix']}",
            ip_address=client_ip,
        )
        return {
            "success": True,
            "message": "Key previously redeemed for this transaction signature.",
            "key_prefix": redemption_result["key_prefix"],
            "tier": redemption_result["tier"],
            "credits": redemption_result["credits"],
        }

    storage.log_audit_event(
        "payment_redeemed_success",
        f"Redeemed {payment.asset} (raw: {payment.amount_raw}) for invoice {invoice['invoice_id']} tier {payment.tier} ({payment.credits} credits). Key: {redemption_result['key_prefix']} [rpc: {payment.rpc_endpoint_used}]",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "status": redemption_result["status"],
        "message": redemption_result["message"],
        "api_key": redemption_result.get("api_key"),
        "key_prefix": redemption_result["key_prefix"],
        "credits": redemption_result["credits"],
        "tier": redemption_result["tier"],
        "invoice_id": invoice["invoice_id"],
    }


class WebhookPayload(BaseModel):
    transaction_signature: str
    target_tier: Optional[str] = "tier_starter"

    @field_validator("transaction_signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        s = v.strip()
        if not (80 <= len(s) <= 90):
            raise ValueError("Solana transaction signature must be between 80 and 90 characters.")
        if not BASE58_PATTERN.match(s):
            raise ValueError("Solana transaction signature must be valid base58.")
        return s


@app.post("/v1/payments/verify-nano")
def verify_nano_payment(req: VerifyNanoPaymentInput, request: Request):
    """
    Verifies zero-fee settlement on the Nano network.
    Fulfills the invoice, credits the user account, and returns an Ed25519 witness receipt.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"verify_nano:{client_ip}", limit=30, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/payments/verify-nano")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many verification requests. Retry in {retry_after} seconds.",
        )

    invoice = storage.get_invoice(req.invoice_id)
    if not invoice:
        unm = storage.record_unmatched_payment(
            rail="nano",
            tx_signature=req.block_hash,
            payer_wallet="unknown_nano_payer",
            asset="XNO",
            amount_raw=0,
            expected_amount_raw=None,
            reason="UNMATCHED_ORDER",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice '{req.invoice_id}' not found. Recorded unmatched holding: {unm['unmatched_id']}",
        )

    if invoice["status"] == "fulfilled":
        try:
            recovered = storage.claim_invoice_credential(req.invoice_id, req.claim_secret)
            return {
                "success": True,
                "api_key": recovered["api_key"],
                "credits": recovered["credits"],
                "tier": recovered["tier"],
                "message": "Payment already verified. Retrieved existing API key.",
            }
        except Exception:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invoice already fulfilled.")

    if invoice.get("rail") != "nano":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice '{req.invoice_id}' is on rail '{invoice.get('rail')}', not 'nano'.",
        )

    try:
        settlement = nano_adapter.verify_settlement(
            block_hash=req.block_hash,
            expected_raw=int(invoice["amount_raw"]),
        )
    except Exception as e:
        storage.record_unmatched_payment(
            rail="nano",
            tx_signature=req.block_hash,
            payer_wallet="unknown_nano_payer",
            asset="XNO",
            amount_raw=int(invoice["amount_raw"]),
            expected_amount_raw=int(invoice["amount_raw"]),
            reason="SETTLEMENT_VERIFICATION_FAILED",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    res = storage.fulfill_invoice_and_redeem(
        invoice_id=req.invoice_id,
        tx_signature=req.block_hash,
        asset=invoice["asset"],
        amount_raw=int(invoice["amount_raw"]),
        tier=invoice["tier"],
        credits_to_grant=invoice["credits"],
        claim_secret=req.claim_secret,
        payer=settlement.get("recipient", nano_adapter.merchant_address),
    )

    witness_id = None
    if witness_manager:
        try:
            w = witness_manager.create_witness(
                action="NANO_PAYMENT_VERIFIED",
                actor="payment_system",
                key_hash=storage.hash_key(res["api_key"]) if res.get("api_key") else None,
                credit_delta=invoice["credits"],
                post_balance=res.get("credits", invoice["credits"]),
                request_id=getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}",
                environmental_anchor={
                    "rail": "nano",
                    "block_hash": req.block_hash,
                    "invoice_id": req.invoice_id,
                },
            )
            witness_id = w.get("witness_id")
        except Exception:
            pass

    return {
        "success": True,
        "api_key": res.get("api_key"),
        "credits": res.get("credits", invoice["credits"]),
        "tier": invoice["tier"],
        "rail": "nano",
        "block_hash": req.block_hash,
        "state_witness_id": witness_id,
    }


@app.get("/v1/payments/unmatched")
def get_unmatched_payments(
    status_filter: Optional[str] = "HELD",
    payer_wallet: Optional[str] = None,
    limit: int = 50,
):
    """
    Returns list of unmatched, underpaid, or expired payments currently held
    awaiting automated or manual refund dispatch.
    """
    records = storage.list_unmatched_payments(
        status=status_filter,
        payer_wallet=payer_wallet,
        limit=min(limit, 100),
    )
    return {
        "count": len(records),
        "status_filter": status_filter,
        "unmatched_payments": records,
    }


@app.post("/v1/payments/refund/{unmatched_id}/challenge")
def request_refund_challenge(unmatched_id: str, request: Request):
    """
    Issues a machine-readable step-up confirmation challenge for an unmatched refund.
    """
    record = storage.get_unmatched_payment(unmatched_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unmatched payment record '{unmatched_id}' not found.",
        )
    if record["status"] != "HELD":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment '{unmatched_id}' has already been processed with status '{record['status']}'.",
        )

    principal_id = getattr(request.state, "key_hash", None) or (request.client.host if request.client else "unknown")
    params = {
        "unmatched_id": unmatched_id,
        "amount_raw": record.get("amount_raw"),
        "asset": record.get("asset"),
        "payer_wallet": record.get("payer_wallet"),
    }
    challenge = confirm_store.issue(
        action="REFUND_PAYMENT",
        principal_id=principal_id,
        params=params,
        consequence_summary={
            "warning": "Executing this operation will permanently dispatch an on-chain refund from the treasury wallet.",
            "unmatched_id": unmatched_id,
            "payer_wallet": record.get("payer_wallet"),
            "asset": record.get("asset"),
            "amount_raw": record.get("amount_raw"),
        },
    )
    return {
        "challenge_nonce": challenge.nonce,
        "action": challenge.action,
        "expires_at": challenge.expires_at,
        "ttl_seconds": confirm_store.default_ttl_seconds,
        "confirm_header": "X-Confirmation-Nonce",
        "consequence_summary": challenge.consequence_summary,
    }


@app.post("/v1/payments/refund/{unmatched_id}")
def process_unmatched_refund(unmatched_id: str, request: Request):
    """
    Dispatches automated refund for an unmatched payment back to payer_wallet
    minus the minimal network transaction fee. Supports machine-readable step-up
    confirmation nonces via ConfirmStore.
    """
    record = storage.get_unmatched_payment(unmatched_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unmatched payment record '{unmatched_id}' not found.",
        )
    if record["status"] != "HELD":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment '{unmatched_id}' has already been processed with status '{record['status']}'.",
        )

    # Step-Up Confirmation Verification
    nonce = request.headers.get("X-Confirmation-Nonce") or request.query_params.get("confirmation_nonce")
    require_confirmation = (
        request.headers.get("X-Require-Confirmation") == "true"
        or request.query_params.get("require_confirmation") == "true"
        or getattr(confirm_store, "strict_mode", False)
    )
    principal_id = getattr(request.state, "key_hash", None) or (request.client.host if request.client else "unknown")
    params = {
        "unmatched_id": unmatched_id,
        "amount_raw": record.get("amount_raw"),
        "asset": record.get("asset"),
        "payer_wallet": record.get("payer_wallet"),
    }

    if require_confirmation and not nonce:
        challenge = confirm_store.issue(
            action="REFUND_PAYMENT",
            principal_id=principal_id,
            params=params,
            consequence_summary={
                "warning": "Executing this operation will permanently dispatch an on-chain refund from the treasury wallet.",
                "unmatched_id": unmatched_id,
                "payer_wallet": record.get("payer_wallet"),
                "asset": record.get("asset"),
                "amount_raw": record.get("amount_raw"),
            },
        )
        req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
        payload = format_error_payload(
            code=ErrorCode.POLICY_CONFIRMATION_REQUIRED.value,
            message="Step-up confirmation required: This action will permanently dispatch an on-chain refund transaction from the treasury.",
            request_id=req_id,
            status_code=428,
            details={
                "challenge_nonce": challenge.nonce,
                "expires_at": challenge.expires_at,
                "consequence_summary": challenge.consequence_summary,
            },
            recovery={
                "action": RecoveryAction.CONFIRM_OPERATION.value,
                "challenge_nonce": challenge.nonce,
                "expires_at": challenge.expires_at,
                "confirm_header": "X-Confirmation-Nonce",
            },
        )
        return JSONResponse(status_code=428, content=payload)

    if nonce:
        ok, reason = confirm_store.verify_and_consume(
            nonce=nonce,
            action="REFUND_PAYMENT",
            principal_id=principal_id,
            params=params,
        )
        if not ok:
            req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
            payload = format_error_payload(
                code=ErrorCode.CONFIRMATION_NONCE_INVALID.value,
                message=f"Confirmation challenge validation failed: {reason}",
                request_id=req_id,
                status_code=410,
                details={"reason": reason, "nonce": nonce},
                recovery_action=RecoveryAction.INSPECT_PARAMETERS,
            )
            return JSONResponse(status_code=410, content=payload)

    try:
        dispatch_result = refund_dispatcher.dispatch_refund(record)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Refund dispatch failed: {e!s}",
        )

    storage.mark_unmatched_refunded(
        unmatched_id=unmatched_id,
        refund_tx_sig=dispatch_result["refund_tx_sig"],
        refunded_amount_raw=dispatch_result["refund_amount_raw"],
    )
    storage.log_audit_event(
        "payment_refund_dispatched",
        f"Refund {dispatch_result['refund_amount_raw']} {record['asset']} dispatched for {unmatched_id} to {record['payer_wallet']}",
    )

    witness_id = None
    witness_sig = None
    if witness_manager:
        try:
            w = witness_manager.create_witness(
                action="UNMATCHED_PAYMENT_REFUNDED",
                actor="refund_dispatcher",
                key_hash=None,
                credit_delta=0,
                post_balance=0,
                request_id=getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}",
                environmental_anchor={
                    "unmatched_id": unmatched_id,
                    "original_tx_signature": record["tx_signature"],
                    "refund_tx_sig": dispatch_result["refund_tx_sig"],
                    "payer_wallet": record["payer_wallet"],
                    "asset": record["asset"],
                    "refund_amount_raw": dispatch_result["refund_amount_raw"],
                },
            )
            witness_id = w.get("witness_id")
            witness_sig = w.get("signature")
        except Exception:
            pass

    return {
        "success": True,
        "unmatched_id": unmatched_id,
        "status": "REFUNDED",
        "payer_wallet": record["payer_wallet"],
        "asset": record["asset"],
        "refund_amount_raw": dispatch_result["refund_amount_raw"],
        "fee_deducted_raw": dispatch_result["fee_deducted_raw"],
        "refund_tx_sig": dispatch_result["refund_tx_sig"],
        "dispatched_at": dispatch_result["dispatched_at"],
        "state_witness_id": witness_id,
        "witness_signature": witness_sig,
    }


@app.post("/v1/payments/reconcile")
def reconcile_payment_endpoint(req: ReconcilePaymentInput, request: Request):
    """
    Reconciles an on-chain transaction signature against open invoices, redeemed ledgers,
    and unmatched payment quarantines.
    - If already redeemed, returns REDEEMED status and existing key prefix.
    - If matches an open invoice and satisfies asset/amount requirements, fulfills the invoice.
    - If sent without an invoice/reference (orphan deposit) or to an expired/mismatched invoice,
      quarantines the transfer into unmatched_payments and optionally triggers an automated refund
      signed by an Ed25519 state witness receipt.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"reconcile_pay:{client_ip}", limit=20, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/payments/reconcile")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many reconciliation requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    sig = req.transaction_signature.strip()
    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"

    # 1. Check if already redeemed
    redemption = storage.get_payment_redemption(sig)
    if redemption:
        w = witness_manager.create_witness(
            action="PAYMENT_RECONCILE_VERIFIED_REDEEMED",
            actor="reconciliation_engine",
            key_hash=redemption.get("key_hash"),
            credit_delta=0,
            post_balance=redemption.get("remaining_credits", 0),
            request_id=req_id,
            environmental_anchor={
                "tx_signature": sig,
                "reconciliation_status": "REDEEMED",
                "invoice_id": redemption.get("invoice_id"),
            },
        )
        return {
            "success": True,
            "reconciliation_status": "REDEEMED",
            "tx_signature": sig,
            "invoice_id": redemption.get("invoice_id"),
            "key_prefix": redemption.get("key_prefix"),
            "tier": redemption.get("tier"),
            "credits_granted": redemption.get("credits_granted"),
            "remaining_credits": redemption.get("remaining_credits"),
            "state_witness_id": w.get("witness_id"),
            "witness_signature": w.get("signature"),
        }

    # 2. Check if already quarantined in unmatched_payments
    existing_unmatched = None
    for item in storage.list_unmatched_payments(status=None, limit=200):
        if item.get("tx_signature") == sig:
            existing_unmatched = item
            break

    if existing_unmatched:
        if req.auto_refund_unmatched and existing_unmatched["status"] == "HELD":
            dispatch_result = refund_dispatcher.dispatch_refund(existing_unmatched)
            storage.mark_unmatched_refunded(
                unmatched_id=existing_unmatched["unmatched_id"],
                refund_tx_sig=dispatch_result["refund_tx_sig"],
                refunded_amount_raw=dispatch_result["refund_amount_raw"],
            )
            w = witness_manager.create_witness(
                action="UNMATCHED_PAYMENT_REFUNDED",
                actor="reconciliation_engine",
                key_hash=None,
                credit_delta=0,
                post_balance=0,
                request_id=req_id,
                environmental_anchor={
                    "unmatched_id": existing_unmatched["unmatched_id"],
                    "tx_signature": sig,
                    "refund_tx_sig": dispatch_result["refund_tx_sig"],
                    "refund_amount_raw": dispatch_result["refund_amount_raw"],
                },
            )
            return {
                "success": True,
                "reconciliation_status": "QUARANTINED_AND_REFUNDED",
                "tx_signature": sig,
                "unmatched_id": existing_unmatched["unmatched_id"],
                "reason": existing_unmatched["reason"],
                "payer_wallet": existing_unmatched["payer_wallet"],
                "asset": existing_unmatched["asset"],
                "refund_amount_raw": dispatch_result["refund_amount_raw"],
                "fee_deducted_raw": dispatch_result["fee_deducted_raw"],
                "refund_tx_sig": dispatch_result["refund_tx_sig"],
                "state_witness_id": w.get("witness_id"),
                "witness_signature": w.get("signature"),
            }

        w = witness_manager.create_witness(
            action="PAYMENT_RECONCILE_QUARANTINED",
            actor="reconciliation_engine",
            key_hash=None,
            credit_delta=0,
            post_balance=0,
            request_id=req_id,
            environmental_anchor={
                "unmatched_id": existing_unmatched["unmatched_id"],
                "tx_signature": sig,
                "status": existing_unmatched["status"],
                "reason": existing_unmatched["reason"],
            },
        )
        return {
            "success": True,
            "reconciliation_status": "QUARANTINED_UNMATCHED",
            "tx_signature": sig,
            "unmatched_id": existing_unmatched["unmatched_id"],
            "status": existing_unmatched["status"],
            "reason": existing_unmatched["reason"],
            "payer_wallet": existing_unmatched["payer_wallet"],
            "asset": existing_unmatched["asset"],
            "amount_raw": existing_unmatched["amount_raw"],
            "refund_endpoint": f"POST /v1/payments/refund/{existing_unmatched['unmatched_id']}",
            "state_witness_id": w.get("witness_id"),
            "witness_signature": w.get("signature"),
        }

    # 3. Inspect on-chain transaction via SolanaPaymentVerifier
    cfg = load_payment_config()
    invoice = storage.get_invoice(req.invoice_id) if req.invoice_id else None
    target_tier = invoice["tier"] if invoice else "tier_starter"
    expected_ref = invoice["reference"] if invoice else None

    verifier = SolanaPaymentVerifier(
        max_age_seconds=cfg.get("max_age_seconds", 86400),
        require_consensus=False,
    )
    try:
        payment = verifier.verify_payment(
            sig,
            requested_tier=target_tier,
            expected_payer=req.expected_payer,
            expected_reference=expected_ref,
        )
    except VerificationError as e:
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"On-chain reconciliation failed: {e!s}",
        ) from e
    except RPCError as e:
        raise ApiError(
            code=ErrorCode.RPC_GATEWAY_ERROR,
            status_code=502,
            retryable=True,
            retry_after=5,
            outcome=OperationOutcome.INDETERMINATE,
            state_effect="none",
            recovery_action=RecoveryAction.POLL_PAYMENT_STATUS,
            message=f"Solana RPC communication error during reconciliation: {e!s}",
        ) from e

    # Try resolving invoice by on-chain reference if invoice_id was not explicitly passed
    if not invoice and getattr(payment, "reference", None):
        invoice = storage.get_invoice_by_reference(payment.reference)

    # 4. Determine if orphan deposit or mismatched/expired invoice
    quarantine_reason = None
    expected_amt = None
    if not invoice:
        quarantine_reason = "UNLINKED_ORPHAN_DEPOSIT"
    else:
        expected_amt = invoice["amount_raw"]
        now_iso = datetime.now(timezone.utc).isoformat()
        is_expired = (invoice["status"] == "expired" or now_iso > invoice["expires_at"])
        if is_expired:
            quarantine_reason = "EXPIRED_INVOICE_PAID"
        elif payment.asset != invoice["asset"]:
            quarantine_reason = f"ASSET_MISMATCH: expected {invoice['asset']}, received {payment.asset}"
        elif payment.amount_raw < invoice["amount_raw"]:
            quarantine_reason = "UNDERPAID_AMOUNT"

    if quarantine_reason:
        unm = storage.record_unmatched_payment(
            rail="solana",
            tx_signature=payment.tx_signature,
            payer_wallet=payment.payer,
            asset=payment.asset,
            amount_raw=payment.amount_raw,
            expected_amount_raw=expected_amt,
            reason=quarantine_reason,
        )
        if req.auto_refund_unmatched:
            dispatch_result = refund_dispatcher.dispatch_refund(unm)
            storage.mark_unmatched_refunded(
                unmatched_id=unm["unmatched_id"],
                refund_tx_sig=dispatch_result["refund_tx_sig"],
                refunded_amount_raw=dispatch_result["refund_amount_raw"],
            )
            w = witness_manager.create_witness(
                action="UNMATCHED_PAYMENT_REFUNDED",
                actor="reconciliation_engine",
                key_hash=None,
                credit_delta=0,
                post_balance=0,
                request_id=req_id,
                environmental_anchor={
                    "unmatched_id": unm["unmatched_id"],
                    "tx_signature": payment.tx_signature,
                    "reason": quarantine_reason,
                    "refund_tx_sig": dispatch_result["refund_tx_sig"],
                    "refund_amount_raw": dispatch_result["refund_amount_raw"],
                },
            )
            return {
                "success": True,
                "reconciliation_status": "QUARANTINED_AND_REFUNDED",
                "tx_signature": payment.tx_signature,
                "unmatched_id": unm["unmatched_id"],
                "reason": quarantine_reason,
                "payer_wallet": payment.payer,
                "asset": payment.asset,
                "amount_raw": payment.amount_raw,
                "refund_amount_raw": dispatch_result["refund_amount_raw"],
                "fee_deducted_raw": dispatch_result["fee_deducted_raw"],
                "refund_tx_sig": dispatch_result["refund_tx_sig"],
                "state_witness_id": w.get("witness_id"),
                "witness_signature": w.get("signature"),
            }

        w = witness_manager.create_witness(
            action="PAYMENT_RECONCILE_QUARANTINED",
            actor="reconciliation_engine",
            key_hash=None,
            credit_delta=0,
            post_balance=0,
            request_id=req_id,
            environmental_anchor={
                "unmatched_id": unm["unmatched_id"],
                "tx_signature": payment.tx_signature,
                "reason": quarantine_reason,
                "payer_wallet": payment.payer,
                "amount_raw": payment.amount_raw,
            },
        )
        return {
            "success": True,
            "reconciliation_status": "QUARANTINED_UNMATCHED",
            "tx_signature": payment.tx_signature,
            "unmatched_id": unm["unmatched_id"],
            "status": "HELD",
            "reason": quarantine_reason,
            "payer_wallet": payment.payer,
            "asset": payment.asset,
            "amount_raw": payment.amount_raw,
            "refund_endpoint": f"POST /v1/payments/refund/{unm['unmatched_id']}",
            "state_witness_id": w.get("witness_id"),
            "witness_signature": w.get("signature"),
        }

    # 5. Valid open invoice match -> fulfill atomically
    redemption_result = storage.fulfill_invoice_and_redeem(
        invoice_id=invoice["invoice_id"],
        tx_signature=payment.tx_signature,
        asset=payment.asset,
        amount_raw=payment.amount_raw,
        tier=invoice["tier"],
        credits_to_grant=invoice["credits"],
        payer=payment.payer,
        reference=payment.reference or invoice["reference"],
        slot=payment.slot,
        block_time=payment.block_time,
    )
    w = witness_manager.create_witness(
        action="PAYMENT_RECONCILED_AND_REDEEMED",
        actor="reconciliation_engine",
        key_hash=storage.hash_key(redemption_result["api_key"]) if redemption_result.get("api_key") else None,
        credit_delta=invoice["credits"],
        post_balance=redemption_result.get("credits", invoice["credits"]),
        request_id=req_id,
        environmental_anchor={
            "invoice_id": invoice["invoice_id"],
            "tx_signature": payment.tx_signature,
            "tier": invoice["tier"],
            "credits": invoice["credits"],
        },
    )
    return {
        "success": True,
        "reconciliation_status": "RECONCILED_AND_FULFILLED",
        "tx_signature": payment.tx_signature,
        "invoice_id": invoice["invoice_id"],
        "api_key": redemption_result.get("api_key"),
        "key_prefix": redemption_result.get("key_prefix"),
        "tier": redemption_result.get("tier"),
        "credits": redemption_result.get("credits"),
        "state_witness_id": w.get("witness_id"),
        "witness_signature": w.get("signature"),
    }


@app.post("/v1/payments/webhook")
def handle_payment_webhook(
    req: WebhookPayload,
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    client_ip = get_client_ip(request)
    if not x_webhook_secret or x_webhook_secret != WEBHOOK_SECRET:
        record_webhook("auth_failed")
        storage.log_audit_event(
            "webhook_auth_failed",
            f"Unauthorized webhook attempt with secret prefix={str(x_webhook_secret)[:4]}... [client_ip: {client_ip}]",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Webhook-Secret header.",
        )

    sig = req.transaction_signature.strip()
    cfg = load_payment_config()
    verifier = SolanaPaymentVerifier(
        max_age_seconds=cfg.get("max_age_seconds", 1800),
        require_consensus=cfg.get("require_consensus", False),
    )

    try:
        payment = in_flight_deduplicator.execute(
            sig,
            lambda: verifier.verify_payment(sig, req.target_tier),
        )
    except VerificationError as e:
        record_webhook("verification_failed")
        record_payment("UNKNOWN", req.target_tier or "tier_starter", "failed")
        storage.log_audit_event(
            "webhook_verification_failed",
            f"Webhook payment rejected for sig={sig[:16]}...: {e!s}",
            ip_address="webhook",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook payment verification failed: {e!s}",
        ) from e
    except RPCError as e:
        record_webhook("rpc_error")
        record_payment("UNKNOWN", req.target_tier or "tier_starter", "rpc_error")
        storage.log_audit_event(
            "webhook_rpc_error",
            f"RPC failure in webhook for sig={sig[:16]}...: {e!s}",
            ip_address="webhook",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Solana RPC communication error: {e!s}",
        ) from e

    redemption_result = storage.redeem_payment(
        tx_signature=payment.tx_signature,
        asset=payment.asset,
        amount_raw=payment.amount_raw,
        tier=payment.tier,
        credits_to_grant=payment.credits,
    )

    record_webhook(redemption_result["status"])
    record_payment(payment.asset, payment.tier, redemption_result["status"])

    event_type = "webhook_payment_redeemed" if redemption_result["status"] == "newly_minted" else "webhook_replay_detected"
    storage.log_audit_event(
        event_type,
        f"Webhook redemption {redemption_result['status']} for sig={sig[:16]}... [tier: {payment.tier}, credits: {payment.credits}]",
        ip_address="webhook",
    )

    return {
        "success": True,
        "status": redemption_result["status"],
        "tier": redemption_result["tier"],
        "credits": redemption_result["credits"],
        "key_prefix": redemption_result["key_prefix"],
        "api_key": redemption_result.get("api_key"),
        "message": redemption_result["message"],
    }


@app.get("/v1/payments/status/{signature}")
def get_payment_status(signature: str):
    sig = signature.strip()
    if not (80 <= len(sig) <= 90) or not BASE58_PATTERN.match(sig):
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Solana transaction signature must be valid Base58 between 80 and 90 characters.",
        )

    redemption = storage.get_payment_redemption(sig)
    if not redemption:
        return {
            "success": True,
            "status": "pending_or_unredeemed",
            "tx_signature": sig,
            "message": "Transaction has not been redeemed yet.",
        }

    return {
        "success": True,
        "status": "redeemed",
        "tx_signature": redemption["tx_signature"],
        "asset": redemption["asset"],
        "tier": redemption["tier"],
        "credits_granted": redemption["credits_granted"],
        "remaining_credits": redemption["remaining_credits"],
        "key_prefix": redemption["key_prefix"],
        "is_active": redemption["is_active"],
        "redeemed_at": redemption["redeemed_at"],
    }


@app.post("/v1/keys/generate-demo")
def generate_demo_key(request: Request):
    client_ip = get_client_ip(request)

    if not is_demo_keys_enabled():
        storage.log_audit_event(
            "demo_key_denied",
            "Attempted demo key generation while feature is disabled in production",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo key issuance is disabled. Provide payment or contact administrator.",
        )

    allowed, retry_after = rate_limiter.is_allowed(f"demo_key:{client_ip}", limit=5, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/keys/generate-demo")
        storage.log_audit_event(
            "rate_limit_exceeded",
            f"Demo key generation rate limit exceeded for IP: {client_ip}",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many demo key requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    raw_token, record = storage.create_api_key(tier="trial", credits=5, prefix_tag="molt_demo")
    storage.log_audit_event(
        "demo_key_issued",
        f"Issued demo key {record['key_prefix']} with 5 trial credits",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "api_key": raw_token,
        "key_prefix": record["key_prefix"],
        "credits": 5,
        "message": "Demo token created with 5 free credits.",
    }


@app.get("/v1/account/quota")
def get_account_quota(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
):
    """
    Non-deducting account quota and key status inspection endpoint.
    Allows autonomous agents and developers to monitor credit balance,
    tier, active status, and top-up instructions without consuming a paid query.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"quota:{client_ip}", limit=60, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/account/quota")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many quota inspection requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    raw_key = x_api_key
    if not raw_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_key = auth_header[7:].strip()

    if not raw_key:
        cfg = load_payment_config()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "Authentication Required",
                "message": "Missing API key. Provide via X-API-KEY or Authorization: Bearer header.",
                "remedy": {
                    "action": "obtain_key",
                    "purchase_endpoint": "POST /v1/payments/verify-solana",
                    "treasury_wallet": cfg["solana_treasury_wallet"],
                },
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_info = storage.get_key_info(raw_key)
    if not key_info:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Invalid API Key",
                "message": "API key was not found or is invalid.",
                "remedy": {
                    "action": "obtain_key",
                    "endpoint": "POST /v1/payments/verify-solana",
                },
            },
        )

    if not key_info.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "API Key Revoked",
                "message": "API key has been deactivated by administrator.",
                "key_prefix": key_info.get("key_prefix"),
            },
        )

    cfg = load_payment_config()
    quota_details = storage.get_key_quota_details(raw_key) or {}
    credits_remaining = quota_details.get("credits_remaining", key_info.get("credits", 0))
    tier = quota_details.get("tier", key_info.get("tier", "unknown"))
    entitlement = quota_details.get("entitlement", {
        "tier": tier,
        "status": "active",
        "expires_at": key_info.get("entitlement_expires_at"),
        "days_remaining": None,
    })
    credit_lots = quota_details.get("credit_lots", [])
    low_credits = credits_remaining < 5 and tier not in ("unlimited", "admin")
    is_expired = entitlement.get("status") == "expired"

    k_hash = key_info["key_hash"]
    rate_limit_key = f"key:{k_hash}"
    remaining_tokens = token_bucket_limiter.get_remaining(rate_limit_key)
    in_flight_count = concurrency_limiter.get_in_flight(rate_limit_key)

    res = {
        "success": True,
        "key_prefix": key_info.get("key_prefix"),
        "tier": tier,
        "credits_remaining": credits_remaining,
        "is_active": bool(key_info.get("is_active")),
        "created_at": key_info.get("created_at"),
        "low_credit_warning": low_credits,
        "entitlement": entitlement,
        "credit_lots": credit_lots,
        "usage": quota_details.get("usage", {}),
        "rate_limit_state": {
            "sustained_limit_per_min": DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
            "burst_capacity": DEFAULT_RATE_LIMIT_BURST_CAPACITY,
            "max_concurrent": DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
            "remaining_tokens": round(remaining_tokens, 2),
            "in_flight_requests": in_flight_count,
            "retry_after_seconds": 0,
        },
    }

    if low_credits or credits_remaining == 0 or is_expired:
        res["remedy"] = {
            "action": "renew_premium" if is_expired else "top_up",
            "endpoint": "POST /v1/payments/verify-solana",
            "treasury_wallet": cfg["solana_treasury_wallet"],
            "accepted_assets": ["SOL", "USDC (Solana SPL)"],
            "pricing_tiers": cfg["rates"],
            "topup_packages": cfg.get("topup_packages", {}),
        }

    return res


@app.get("/v1/account/usage")
def get_account_usage(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
):
    """
    Comprehensive account usage, consumption metrics, active credit lots,
    and remaining entitlement report for autonomous agents.
    Reuses the robust quota accounting engine while conforming to the Agent Data Exchange specification.
    """
    return get_account_quota(request, x_api_key=x_api_key)


@app.get("/v1/capabilities")
def get_capabilities_manifest():
    """
    Returns the comprehensive machine-readable capability manifest for Moltbook Alpha API.
    Allows autonomous orchestrators and agents to discover endpoints, schemas, costs,
    and input requirements without manual human documentation.
    """
    return get_api_capabilities()


@app.get("/v1/data-products")
def list_data_products():
    """
    Agent Data Exchange: Lists all available data products, update frequencies,
    freshness guarantees, schemas, and credit pricing terms.
    """
    products = data_product_exchange.list_products()
    return {
        "count": len(products),
        "products": products,
        "data_products": products,
    }


@app.get("/v1/data-products/{product_id}")
def get_data_product_contract(product_id: str):
    """
    Agent Data Exchange: Returns the complete contract and machine-readable JSON schemas
    for a specific data product.
    """
    prod = data_product_exchange.get_product(product_id)
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data product '{product_id}' not found in exchange catalog. Available: {[p['product_id'] for p in data_product_exchange.list_products()]}",
        )
    return prod.to_contract_dict()


@app.get("/v1/data-products/{product_id}/sample")
def get_data_product_sample(product_id: str, request: Request):
    """
    Agent Data Exchange: Returns a free (0-credit), deterministic, schema-valid sample
    snapshot for pre-purchase agent evaluation, complete with provenance metadata,
    evidence grading, retrieval outcome semantics, and an Ed25519 witness signature.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"data_product_sample:{client_ip}", limit=60, window_seconds=60)
    if not allowed:
        record_rate_limit(f"/v1/data-products/{product_id}/sample")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many sample preview requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        sample = data_product_exchange.generate_sample_snapshot(
            product_id=product_id,
            witness_manager=witness_manager,
        )
    except KeyError:
        sample = None
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data product '{product_id}' not found in exchange catalog. Available: {[p['product_id'] for p in data_product_exchange.list_products()]}",
        )
    return sample


@app.get("/v1/data-products/{product_id}/latest")
def get_data_product_latest(
    product_id: str,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
    min_profit_pct: Optional[float] = None,
    pair: Optional[str] = None,
    asset: Optional[str] = None,
    min_confidence: Optional[float] = None,
    evidence_level: Optional[str] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
):
    """
    Agent Data Exchange: Retrieves the latest structured snapshot for a data product.
    Authenticates the caller and atomically reserves/deducts 1 credit against active credit lots.
    Idempotent: Identical requests with an idempotency-key replay without duplicate credit charges.
    Zero-charge on failure: Errors release the credit reservation safely.
    """
    contract = data_product_exchange.get_product(product_id)
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data product '{product_id}' not found in exchange catalog.",
        )

    client_ip = get_client_ip(request)

    # General rate limit: 60 requests per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"data_product:{client_ip}", limit=60, window_seconds=60)
    if not allowed:
        record_rate_limit(f"/v1/data-products/{product_id}/latest")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    raw_key = x_api_key
    if not raw_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_key = auth_header[7:].strip()

    if not raw_key:
        cfg = load_payment_config()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Payment Required",
                "message": f"Accessing data product '{product_id}' requires an active API key or payment.",
                "price": f"{contract.cost_credits} credit per successful snapshot retrieval.",
                "purchase_instructions": {
                    "treasury_wallet": cfg["solana_treasury_wallet"],
                    "rates": cfg["rates"],
                    "verify_endpoint": "POST /v1/payments/verify-solana",
                },
            },
        )

    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    k_hash = storage.hash_key(raw_key)
    rate_key = f"key:{k_hash}"

    # Token bucket rate limiting (Burst 5, Sustained 60/min)
    tb_allowed, tb_retry_after, tb_remaining = token_bucket_limiter.is_allowed(
        rate_key,
        capacity=DEFAULT_RATE_LIMIT_BURST_CAPACITY,
        refill_per_min=DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    )
    request.state.rate_limit_limit = DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN
    request.state.rate_limit_remaining = tb_remaining
    request.state.rate_limit_reset = tb_retry_after

    if not tb_allowed:
        record_rate_limit(f"/v1/data-products/{product_id}/latest")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Request rate exceeded. Please retry in {tb_retry_after} seconds.",
            headers={
                "Retry-After": str(tb_retry_after),
                "X-RateLimit-Limit": str(DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(tb_retry_after),
            },
        )

    # Concurrency Limiter (Max 5 concurrent requests)
    slot_acquired, slot_id, _ = concurrency_limiter.acquire(
        rate_key,
        max_concurrent=DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
    )
    if not slot_acquired:
        record_rate_limit(f"/v1/data-products/{product_id}/latest")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maximum concurrent requests reached (5). Please back off and retry.",
            headers={"Retry-After": "1"},
        )
    request.state.concurrency_slot_id = slot_id
    request.state.concurrency_rate_key = rate_key

    # Two-Phase Quota Reservation with Idempotency Key
    idempotency_key = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
    res_info, state = storage.reserve_quota(raw_key, idempotency_key=idempotency_key, request_id=req_id)
    if res_info and res_info.get("reservation_id") and state == "ok":
        request.state.quota_reservation_id = res_info["reservation_id"]

    if state == "idempotent_replay":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        if res_info.get("cached_response"):
            return res_info["cached_response"]
        return {
            "status": "settled",
            "reservation_id": res_info.get("reservation_id"),
            "idempotency_key": res_info.get("idempotency_key"),
            "message": "Request previously settled under this idempotency key. Cached payload not retained.",
        }

    if state == "in_flight":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A request with this idempotency key is currently in flight. Please retry shortly.",
            headers={"Retry-After": "1"},
        )

    if state == "invalid":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key. Submit payment to /v1/payments/verify-solana or contact administrator.",
        )
    if state == "revoked":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has been revoked.",
        )
    if state == "entitlement_expired":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        cfg = load_payment_config()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Entitlement Expired",
                "message": "Premium entitlement has expired. Renew your Premium subscription to continue spending credits.",
                "purchase_instructions": {
                    "treasury_wallet": cfg["solana_treasury_wallet"],
                    "rates": cfg["rates"],
                    "verify_endpoint": "POST /v1/payments/verify-solana",
                },
            },
        )
    if state == "exhausted":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Key credits exhausted. Top up your balance via Solana USDC.",
        )

    try:
        receipt = {
            "request_id": req_id,
            "product_id": product_id,
            "credits_deducted": contract.cost_credits,
            "entitlement_tier": res_info.get("tier"),
            "lot_id": res_info.get("lot_id"),
            "credits_remaining": res_info.get("credits"),
            "key_hash": res_info.get("key_hash"),
            "key_prefix": res_info.get("key_prefix"),
        }

        params = {}
        if min_profit_pct is not None:
            params["min_profit_pct"] = min_profit_pct
        if pair is not None:
            params["pair"] = pair
        if asset is not None:
            params["asset"] = asset
        if min_confidence is not None:
            params["min_confidence"] = min_confidence
        if evidence_level is not None:
            params["evidence_level"] = evidence_level
        if category is not None:
            params["category"] = category
        if limit is not None:
            params["limit"] = limit

        snapshot = data_product_exchange.generate_snapshot(
            product_id=product_id,
            intel_engine=intel_engine,
            dex_microstructure=dex_microstructure,
            witness_manager=witness_manager,
            params=params,
            receipt=receipt,
        )

        # Settle quota upon successful response construction
        if res_info and res_info.get("reservation_id") and state == "ok":
            storage.settle_quota(res_info["reservation_id"], response_payload=snapshot)
            request.state.quota_reservation_id = None

        return snapshot

    except HTTPException:
        if res_info and res_info.get("reservation_id") and state == "ok":
            storage.release_quota(res_info["reservation_id"], reason="http_exception")
            request.state.quota_reservation_id = None
        raise
    except Exception as e:
        if res_info and res_info.get("reservation_id") and state == "ok":
            storage.release_quota(res_info["reservation_id"], reason=f"snapshot_error: {e}")
            request.state.quota_reservation_id = None
        raise HTTPException(status_code=500, detail=f"Internal server error generating snapshot for '{product_id}': {e}") from e
    finally:
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None


@app.get("/v1/briefing/latest")
def get_latest_briefing(request: Request, x_api_key: Optional[str] = Header(None)):
    client_ip = get_client_ip(request)

    # General rate limit: 60 requests per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"briefing:{client_ip}", limit=60, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/briefing/latest")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    raw_key = x_api_key
    if not raw_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_key = auth_header[7:].strip()

    if not raw_key:
        cfg = load_payment_config()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Payment Required",
                "message": "Access requires an active API key or payment.",
                "price": "Starter: $1 (50 queries), Pro: $5 (300 queries), Premium: $20 (10,000 queries / 30 days).",
                "purchase_instructions": {
                    "treasury_wallet": cfg["solana_treasury_wallet"],
                    "rates": cfg["rates"],
                    "topup_packages": cfg.get("topup_packages", {}),
                    "verify_endpoint": "POST /v1/payments/verify-solana",
                },
            },
        )

    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    k_hash = storage.hash_key(raw_key)
    rate_key = f"key:{k_hash}"

    # Token Bucket Rate Limiting (Burst 5, Sustained 60/min)
    tb_allowed, tb_retry_after, tb_remaining = token_bucket_limiter.is_allowed(
        rate_key,
        capacity=DEFAULT_RATE_LIMIT_BURST_CAPACITY,
        refill_per_min=DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    )
    request.state.rate_limit_limit = DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN
    request.state.rate_limit_remaining = tb_remaining
    request.state.rate_limit_reset = tb_retry_after

    if not tb_allowed:
        record_rate_limit("/v1/briefing/latest")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Request rate exceeded. Please retry in {tb_retry_after} seconds.",
            headers={
                "Retry-After": str(tb_retry_after),
                "X-RateLimit-Limit": str(DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(tb_retry_after),
            },
        )

    # Concurrency Limiter (Max 5 concurrent requests)
    slot_acquired, slot_id, _ = concurrency_limiter.acquire(
        rate_key,
        max_concurrent=DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
    )
    if not slot_acquired:
        record_rate_limit("/v1/briefing/latest")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maximum concurrent requests reached (5). Please back off and retry.",
            headers={"Retry-After": "1"},
        )
    request.state.concurrency_slot_id = slot_id
    request.state.concurrency_rate_key = rate_key

    # Two-Phase Quota Reservation with Idempotency Key
    idempotency_key = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
    res_info, state = storage.reserve_quota(raw_key, idempotency_key=idempotency_key, request_id=req_id)
    if res_info and res_info.get("reservation_id") and state == "ok":
        request.state.quota_reservation_id = res_info["reservation_id"]

    if state == "idempotent_replay":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        if res_info.get("cached_response"):
            return res_info["cached_response"]
        return {
            "status": "settled",
            "reservation_id": res_info.get("reservation_id"),
            "idempotency_key": res_info.get("idempotency_key"),
            "message": "Request previously settled under this idempotency key. Cached payload not retained.",
        }

    if state == "in_flight":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A request with this idempotency key is currently in flight. Please retry shortly.",
            headers={"Retry-After": "1"},
        )

    if state == "invalid":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key. Submit payment to /v1/payments/verify-solana or contact administrator.",
        )
    if state == "revoked":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has been revoked.",
        )
    if state == "entitlement_expired":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        cfg = load_payment_config()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Entitlement Expired",
                "message": "Premium entitlement has expired. Renew your Premium subscription to continue spending credits.",
                "purchase_instructions": {
                    "treasury_wallet": cfg["solana_treasury_wallet"],
                    "rates": cfg["rates"],
                    "topup_packages": cfg.get("topup_packages", {}),
                    "verify_endpoint": "POST /v1/payments/verify-solana",
                },
            },
        )
    if state == "exhausted":
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Key credits exhausted. Top up your balance via Solana USDC.",
        )

    latest_path = REPORTS_DIR / "latest_briefing.md"

    try:
        if not latest_path.exists():
            raise HTTPException(status_code=404, detail="No briefing generated yet.")

        with open(latest_path, "r", encoding="utf-8") as f:
            content = f.read()

        witness_id = None
        if res_info and res_info.get("key_hash"):
            try:
                w = witness_manager.create_witness(
                    action="QUERY_DEDUCTED",
                    actor=res_info.get("key_prefix", "unknown"),
                    key_hash=res_info.get("key_hash"),
                    lot_id=res_info.get("lot_id"),
                    pre_balance=(res_info.get("credits") or 0) + 1,
                    credit_delta=-1,
                    post_balance=res_info.get("credits"),
                    request_id=req_id,
                )
                witness_id = w["witness_id"]
            except Exception:
                pass

        # Synthesize real-time quantitative trading signals & cross-DEX arbitrage
        trading_signals = intel_engine.generate_trading_signals(
            limit=5,
            dex_microstructure=dex_microstructure,
            witness_manager=witness_manager,
        )
        live_opportunities = intel_engine.get_live_opportunities(
            dex_microstructure=dex_microstructure,
            min_profit_pct=0.05,
            limit=5,
            witness_manager=witness_manager,
        )

        res = {
            "success": True,
            "user_tier": res_info.get("tier"),
            "credits_remaining": res_info.get("credits"),
            "briefing_markdown": content,
            "trading_signals": trading_signals,
            "opportunities": live_opportunities,
        }
        if witness_id:
            res["state_witness_id"] = witness_id

        # Settle quota upon successful response construction
        if res_info and res_info.get("reservation_id") and state == "ok":
            storage.settle_quota(res_info["reservation_id"], response_payload=res)
            request.state.quota_reservation_id = None

        return res
    except HTTPException:
        if res_info and res_info.get("reservation_id") and state == "ok":
            storage.release_quota(res_info["reservation_id"], reason="http_exception")
            request.state.quota_reservation_id = None
        raise
    except Exception as e:
        if res_info and res_info.get("reservation_id") and state == "ok":
            storage.release_quota(res_info["reservation_id"], reason=f"briefing_error: {e}")
            request.state.quota_reservation_id = None
        raise HTTPException(status_code=500, detail="Internal server error reading briefing.") from e
    finally:
        concurrency_limiter.release(slot_id, rate_key)
        request.state.concurrency_slot_id = None


@app.get("/v1/errors")
def get_error_registry():
    """
    Returns the complete machine-readable error code registry,
    including HTTP status mappings, retryability semantics, operation outcomes,
    state effects, recovery actions, and documentation URLs.
    """
    return {
        "version": "1.0.0",
        "docs_base_url": DOCS_BASE_URL,
        "errors": {
            k: {
                "code": v.code.value,
                "status_code": v.status_code,
                "retryable": v.retryable,
                "outcome": v.outcome.value if isinstance(v.outcome, OperationOutcome) else str(v.outcome),
                "state_effect": v.state_effect,
                "recovery_action": v.recovery_action.value if isinstance(v.recovery_action, RecoveryAction) else str(v.recovery_action),
                "default_retry_after": v.default_retry_after,
                "default_message": v.default_message,
                "description": v.description,
                "docs_url": v.docs_url,
            }
            for k, v in ERROR_REGISTRY.items()
        },
    }


@app.get("/v1/errors/{code}")
def get_error_definition(code: str):
    """
    Returns the specification and retry semantics for a specific error code.
    """
    norm_code = code.strip().upper()
    defn = ERROR_REGISTRY.get(norm_code)
    if not defn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error code '{code}' not recognized in error taxonomy registry.",
        )
    return {
        "code": defn.code.value,
        "status_code": defn.status_code,
        "retryable": defn.retryable,
        "outcome": defn.outcome.value if isinstance(defn.outcome, OperationOutcome) else str(defn.outcome),
        "state_effect": defn.state_effect,
        "recovery_action": defn.recovery_action.value if isinstance(defn.recovery_action, RecoveryAction) else str(defn.recovery_action),
        "default_retry_after": defn.default_retry_after,
        "default_message": defn.default_message,
        "description": defn.description,
        "docs_url": defn.docs_url,
    }


@app.get("/v1/tools")
def list_available_tools():
    """
    Returns registered agent tools with links to their parameter DAGs.
    """
    return {
        "version": "1.0.0",
        "tools": [
            {
                "tool_name": name,
                "version": dag.version,
                "description": dag.description,
                "parameter_count": len(dag.parameters),
                "parameter_graph_endpoint": f"/v1/tools/{name}/parameter-graph",
            }
            for name, dag in TOOL_DAG_REGISTRY.items()
        ],
    }


@app.get("/v1/tools/{tool_name}/parameter-graph")
def get_tool_parameter_graph(tool_name: str):
    """
    Returns the compiled Directed Acyclic Graph (DAG) for a tool,
    including prerequisite dependencies, topological execution stages, and resolvers.
    """
    dag = TOOL_DAG_REGISTRY.get(tool_name)
    if not dag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{tool_name}' not found in registered tool catalog.",
        )
    return dag.to_dict()


class VerifyWitnessInput(BaseModel):
    witness: Dict[str, Any]
    public_key_base58: Optional[str] = None


@app.get("/v1/witnesses/public-keys")
def get_witness_public_keys():
    """
    Returns active Ed25519 public keys used for signing cryptographic state witnesses.
    Allows autonomous agents to verify non-repudiation and RFC 8785 canonical hash integrity.
    """
    return witness_manager.get_public_keys_metadata()


@app.get("/v1/witnesses/{witness_id}")
def get_state_witness(witness_id: str):
    """
    Fetches an immutable cryptographic state witness record by ID.
    """
    record = witness_manager.get_witness(witness_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"State witness '{witness_id}' not found.",
        )
    return record


@app.post("/v1/witnesses/verify")
def verify_state_witness(input_data: VerifyWitnessInput):
    """
    Verifies an Ed25519 cryptographic state witness payload against RFC 8785 canonicalization
    and the server's public key (or an optionally supplied public key).
    """
    return witness_manager.verify_witness_payload(
        input_data.witness,
        public_key_b58=input_data.public_key_base58,
    )


def get_sample_briefing_payload() -> Dict[str, Any]:
    """
    Returns a realistic, schema-valid synthetic briefing for unmetered evaluation.
    """
    sample_content = (
        "# Moltbook Alpha Intelligence Briefing [SAMPLE EVALUATION]\n\n"
        "## Executive Summary\n"
        "Synthesized market telemetry across Solana concentrated liquidity pools, "
        "Moltbook autonomous agent discussions, and protocol security advisories.\n\n"
        "## Critical Signals\n"
        "- **Orca Whirlpool SOL-USDC**: Tick vacuum detected at -25 bps tick boundary; skew indicates institutional bid support.\n"
        "- **Agent Ecosystem**: Autonomous agent challenge verification throughput up 42% over last 6 hours.\n\n"
        "## Provenance Witness\n"
        "State witness ID: `wit_sample_e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`\n"
        "Signature verified against Atlas Provenance Guard.\n"
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "success": True,
        "sample": True,
        "mode": "evaluation_unmetered",
        "generated_at": now_iso,
        "credits_remaining": "unmetered",
        "briefing_markdown": sample_content,
        "signals": [
            {
                "signal_id": "sig_sample_001",
                "category": "dex_microstructure",
                "confidence": "HIGH",
                "title": "Orca Whirlpool SOL-USDC Tick Vacuum Detected",
                "summary": "Sub-tick volume divergence identified at lower tick boundary indicating upward volatility squeeze.",
                "sources": [
                    {
                        "source_name": "Orca Whirlpool",
                        "source_type": "dex_clmm",
                        "pool_id": "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm",
                        "verified": True,
                    }
                ],
                "observed_at": now_iso,
            },
            {
                "signal_id": "sig_sample_002",
                "category": "security_advisory",
                "confidence": "HIGH",
                "title": "Moltbook Protocol Agent Identity Verification Standard",
                "summary": "Cryptographic Ed25519 witness state validation mandated for autonomous trading bot telemetry pipelines.",
                "sources": [
                    {
                        "source_name": "Moltbook Protocol",
                        "source_type": "social_graph",
                        "post_id": "e2ae1289-a20b-4bd4-ba46-1af0fd1fc6cc",
                        "verified": True,
                    }
                ],
                "observed_at": now_iso,
            },
        ],
        "trading_signals": [
            {
                "signal_id": "sig_sample_sol_001",
                "asset": "SOL",
                "pair": "SOL/USDC",
                "action": "BUY_ACCUMULATE",
                "confidence_score": 0.88,
                "confidence_tier": "HIGH",
                "risk_rating": "LOW",
                "entry_price": 182.15,
                "price_targets": [186.70, 193.99],
                "stop_loss": 178.87,
                "risk_reward_ratio": 2.36,
                "timeframe": "1h",
                "catalyst_type": "orderflow_imbalance",
                "headline": "Institutional Bid Skew & Orderbook Imbalance on SOL-USDC",
                "rationale": "Concentrated liquidity orderbooks show heavy bid imbalance (+10.6%) with over $2.4M bid depth inside the 50 bps band.",
                "execution_params": {
                    "recommended_venue": "Raydium CLMM",
                    "route_type": "CLMM_DIRECT",
                    "max_slippage_bps": 25,
                    "min_liquidity_depth_usd": 100000.0,
                },
                "created_at": now_iso,
            }
        ],
        "opportunities": [
            {
                "opportunity_id": "opp_sample_arb_sol_usdc",
                "opportunity_type": "cross_dex_arbitrage",
                "pair": "SOL/USDC",
                "buy_venue": "Raydium CLMM",
                "buy_pool_id": "2QdhepnKRTLjjSqPL1PtKNwqrUkoLee5Gqs8bvZhRdMv",
                "buy_price": 182.15,
                "sell_venue": "Orca Whirlpool",
                "sell_pool_id": "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm",
                "sell_price": 182.80,
                "gross_spread_bps": 35.68,
                "net_profit_pct": 0.28,
                "estimated_capacity_usd": 75000.0,
                "urgency": "HIGH",
                "estimated_decay_seconds": 15,
                "detected_at": time.time(),
            }
        ],
        "microstructure_summary": {
            "tracked_pools": 5,
            "anomalies_detected": 1,
            "aggregate_depth_usd_50bps": 14250000.0,
        },
        "state_witness": {
            "action": "SAMPLE_EVALUATION",
            "witness_id": "wit_sample_e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "canonical_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "verified": True,
        },
        "documentation_url": "https://theheiszt.github.io/moltbook-alpha",
        "api_status_url": "/v1/health",
        "pricing_url": "/v1/payments/config",
    }


@app.get("/v1/intel/sample")
def get_intel_sample(request: Request):
    """
    Returns an unmetered, realistic sample briefing payload for evaluation and schema validation.
    No API key or payment required.
    Emits a privacy-preserving 'sample_viewed' conversion funnel event.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"sample:{client_ip}", limit=60, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/intel/sample")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    storage.record_funnel_event(
        "sample_viewed",
        {"endpoint": "/v1/intel/sample", "user_agent": (request.headers.get("user-agent") or "unknown")[:64]}
    )

    return get_sample_briefing_payload()


@app.get("/v1/intel/latest")
def get_intel_latest(request: Request, x_api_key: Optional[str] = Header(None)):
    """
    Returns the latest synthesized market intelligence briefing,
    including actionable signals, verified sources, and cryptographic state witness ID.
    Enforces atomic credit deduction via API key or Bearer token.
    """
    return get_latest_briefing(request, x_api_key=x_api_key)


@app.get("/v1/intel/signals")
def get_intel_signals(
    category: Optional[str] = None,
    confidence: Optional[str] = None,
    limit: int = 25,
):
    """
    Queries indexed intelligence signals across security advisories, API changes,
    operational failures, architecture patterns, and market alpha.
    """
    signals = intel_engine.search_signals(
        category=category,
        confidence=confidence,
        limit=min(limit, 100),
    )
    return {
        "count": len(signals),
        "signals": signals,
    }


@app.get("/v1/intel/opportunities")
def get_intel_opportunities(
    request: Request,
    min_profit_pct: float = 0.05,
    pair: Optional[str] = None,
    opp_type: Optional[str] = None,
    limit: int = 25,
):
    """
    Scans real-time cross-DEX arbitrage opportunities, liquidity gaps,
    and tick vacuum squeeze alerts across tracked Solana liquidity pools (Orca, Raydium, Meteora).
    Calculates net profitability after pool fee tiers and execution gas costs.
    """
    opps = intel_engine.get_live_opportunities(
        dex_microstructure=dex_microstructure,
        min_profit_pct=min_profit_pct,
        pair=pair,
        opp_type=opp_type,
        limit=min(limit, 100),
        witness_manager=witness_manager,
    )
    return {
        "count": len(opps),
        "min_profit_pct": min_profit_pct,
        "opportunities": opps,
        "timestamp_utc": time.time(),
    }


@app.get("/v1/intel/signals/trading")
def get_intel_trading_signals(
    request: Request,
    asset: Optional[str] = None,
    action: Optional[str] = None,
    min_confidence: float = 0.5,
    limit: int = 25,
):
    """
    Returns synthesized machine-readable trading directives with entry price,
    targets, stop loss, risk rating, execution venue, and Ed25519 cryptographic witness.
    """
    signals = intel_engine.generate_trading_signals(
        limit=min(limit, 100),
        asset=asset,
        action=action,
        min_confidence=min_confidence,
        dex_microstructure=dex_microstructure,
        witness_manager=witness_manager,
    )
    return {
        "count": len(signals),
        "min_confidence": min_confidence,
        "trading_signals": signals,
        "timestamp_utc": time.time(),
    }


@app.get("/v1/intel/demand")
def get_intel_service_demand_leaderboard(
    request: Request,
    limit: int = 20,
):
    """
    [UNMETERED - 0 CREDITS] Synthesizes community posts across Moltbook submolts
    into a ranked Agent Service Demand Leaderboard, mapping top agent pain points
    and RFPs directly to Moltbook Alpha API endpoints and open bounties.
    """
    return intel_engine.get_service_demand_leaderboard(limit=min(limit, 50))


from job_board import create_jobs_router  # noqa: E402

app.include_router(create_jobs_router(storage_manager=storage))


class QuantTradeViabilityInput(BaseModel):
    pair: str = "BONK/SOL"
    target_net_pct: float = 0.015
    stop_loss_pct: float = 0.020
    roundtrip_spread_bps: float = 8.0
    hourly_volatility: Optional[float] = None
    hourly_drift: float = 0.0
    horizons_hours: Optional[List[int]] = None


_QUANT_FP_CACHE: Dict[str, Any] = {}
_QUANT_FP_TTL_SECONDS = 45.0


@app.get("/v1/quant/first-passage")
def get_quant_first_passage(
    request: Request,
    pair: str = "BONK/SOL",
    target_net_pct: float = 0.015,
    stop_loss_pct: float = 0.020,
    roundtrip_spread_bps: float = 8.0,
    hourly_volatility: Optional[float] = None,
    hourly_drift: float = 0.0,
    refresh: bool = False,
):
    """
    Computes analytical Brownian reflection and drift-adjusted inverse Gaussian
    first-passage probabilities across multiple time horizons (4h, 8h, 12h, 24h, 48h, 72h),
    two-barrier win odds (take-profit before stop-loss), Kelly sizing, and an optimal
    target velocity ladder, bound to an Ed25519 cryptographic state witness.
    Includes a 45-second TTL cache (?refresh=true to bypass).
    """
    if target_net_pct <= 0 or target_net_pct > 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_net_pct must be between 0.0001 and 1.0 (e.g. 0.015 for +1.5%).",
        )
    if stop_loss_pct <= 0 or stop_loss_pct >= 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stop_loss_pct must be between 0.0001 and 0.9999 (e.g. 0.020 for -2.0%).",
        )

    cache_key = f"{pair.upper().strip()}|{target_net_pct:.5f}|{stop_loss_pct:.5f}|{roundtrip_spread_bps:.2f}|{hourly_volatility}|{hourly_drift:.5f}"
    now_ts = time.time()
    cached = _QUANT_FP_CACHE.get(cache_key)
    if cached and not refresh and (now_ts - cached["ts"]) < _QUANT_FP_TTL_SECONDS:
        out = dict(cached["profile"])
        out["cache_status"] = "HIT"
        out["cache_age_seconds"] = round(now_ts - cached["ts"], 2)
        return out

    from ops.trading.quant_trader import QuantTradingEngine

    q_engine = QuantTradingEngine()
    profile = q_engine.evaluate_trade_probability_profile(
        pair=pair,
        target_net_pct=target_net_pct,
        stop_loss_pct=stop_loss_pct,
        roundtrip_spread_bps=roundtrip_spread_bps,
        hourly_volatility=hourly_volatility,
        hourly_drift=hourly_drift,
    )

    w = witness_manager.create_witness(
        action="QUANT_FIRST_PASSAGE_EVALUATED",
        actor=profile["pair"],
        key_hash="public_quant_query",
        request_id=getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(6)}",
        environmental_anchor={
            "pair": profile["pair"],
            "target_net_pct": target_net_pct,
            "stop_loss_pct": stop_loss_pct,
            "recommended_target_net_pct": profile["recommended_target_net_pct"],
        },
    )
    profile["state_witness_id"] = w.get("witness_id")
    profile["witness_signature"] = w.get("signature")
    profile["generated_at"] = datetime.now(timezone.utc).isoformat()
    profile["cache_status"] = "MISS"
    profile["cache_age_seconds"] = 0.0
    _QUANT_FP_CACHE[cache_key] = {"ts": now_ts, "profile": profile}
    return profile


@app.post("/v1/quant/trade-viability")
def post_quant_trade_viability(
    payload: QuantTradeViabilityInput,
    request: Request,
):
    """
    Evaluates custom quantitative trade viability, round-trip spread drag, two-barrier
    win odds, and multi-horizon first-passage probabilities with an Ed25519 state witness.
    """
    if payload.target_net_pct <= 0 or payload.target_net_pct > 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_net_pct must be between 0.0001 and 1.0.",
        )
    if payload.stop_loss_pct <= 0 or payload.stop_loss_pct >= 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stop_loss_pct must be between 0.0001 and 0.9999.",
        )

    from ops.trading.quant_trader import QuantTradingEngine

    q_engine = QuantTradingEngine()
    profile = q_engine.evaluate_trade_probability_profile(
        pair=payload.pair,
        target_net_pct=payload.target_net_pct,
        stop_loss_pct=payload.stop_loss_pct,
        roundtrip_spread_bps=payload.roundtrip_spread_bps,
        hourly_volatility=payload.hourly_volatility,
        hourly_drift=payload.hourly_drift,
        horizons_hours=payload.horizons_hours,
    )

    w = witness_manager.create_witness(
        action="QUANT_TRADE_VIABILITY_EVALUATED",
        actor=profile["pair"],
        key_hash="public_quant_query",
        request_id=getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(6)}",
        environmental_anchor={
            "pair": profile["pair"],
            "target_net_pct": payload.target_net_pct,
            "stop_loss_pct": payload.stop_loss_pct,
            "recommended_target_net_pct": profile["recommended_target_net_pct"],
        },
    )
    profile["state_witness_id"] = w.get("witness_id")
    profile["witness_signature"] = w.get("signature")
    profile["generated_at"] = datetime.now(timezone.utc).isoformat()
    return profile


# =============================================================================
# Molt Alpha DEMS — 6 Pixel Artworks Lazy-Minted NFT Collection API
# =============================================================================

class CreateNftOrderInput(BaseModel):
    nft_id: str
    buyer_wallet: str
    asset: str = "SOL"


class ClaimNftOrderInput(BaseModel):
    order_id: str
    transaction_signature: str


@app.get("/v1/nfts/catalog")
def get_nfts_catalog():
    """
    Returns the complete Molt Alpha DEMS 6-piece pixel art NFT collection catalog,
    including rarities, traits, SOL/USDC prices, remaining edition supply, and bundled API credit grants.
    """
    from nft_collection import MoltAlphaDemsCollection

    col = MoltAlphaDemsCollection()
    return col.list_catalog()


@app.get("/v1/newsletter/latest")
def get_latest_daily_newsletter():
    """
    Returns the latest automated Daily Intelligence & Quant Newsletter (JSON + Markdown)
    combining verified submolt radar, first-passage probability matrices, and Molt Alpha DEMS NFT supply.
    """
    import json as _json

    news_json_path = REPORTS_DIR / "latest_newsletter.json"
    if news_json_path.is_file():
        try:
            return _json.loads(news_json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    from ops.publisher import publish_daily_alpha

    publish_daily_alpha(dry_run=True, force_refresh=False, storage_manager=storage, witness_manager=witness_manager)
    if news_json_path.is_file():
        return _json.loads(news_json_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=500, detail="Failed to synthesize daily newsletter.")


@app.get("/v1/nfts/assets/{filename}")
def get_nft_asset_image(filename: str):
    """
    Serves the 2x Nearest-Neighbor upscaled PNG pixel artwork files for Molt Alpha DEMS.
    """
    from nft_collection import NFT_ASSETS_DIR

    clean_name = Path(filename).name
    target = NFT_ASSETS_DIR / clean_name
    if not target.is_file() or target.suffix.lower() not in (".png", ".json"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NFT asset '{clean_name}' not found.",
        )
    media = "image/png" if target.suffix.lower() == ".png" else "application/json"
    return FileResponse(target, media_type=media)


@app.get("/v1/nfts/metadata/{nft_id}.json")
def get_nft_metaplex_metadata(nft_id: str, edition: Optional[int] = None):
    """
    Returns Metaplex Token Metadata standard JSON for wallet and marketplace indexing.
    """
    from nft_collection import MoltAlphaDemsCollection

    col = MoltAlphaDemsCollection()
    try:
        return col.build_metaplex_metadata(nft_id, edition_number=edition)
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@app.post("/v1/nfts/order", status_code=status.HTTP_201_CREATED)
def create_nft_lazy_mint_order(payload: CreateNftOrderInput, request: Request):
    """
    Creates a bound Lazy-Mint Order for one of the 6 Molt Alpha DEMS pixel artworks.
    Zero upfront rent is spent by the seller; the buyer pays the bound invoice on Solana
    to mint their edition and receive bundled Moltbook Alpha API credits.
    """
    from nft_collection import MoltAlphaDemsCollection

    col = MoltAlphaDemsCollection()
    try:
        order = col.create_lazy_mint_order(
            nft_id=payload.nft_id,
            buyer_wallet=payload.buyer_wallet,
            asset=payload.asset,
            storage=storage,
        )
        storage.log_audit_event(
            "nft_order_created",
            f"Created lazy-mint order {order['order_id']} for {order['nft_id']} ({order['buyer_wallet']})",
            ip_address=get_client_ip(request),
        )
        return order
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@app.post("/v1/nfts/claim")
def claim_nft_lazy_mint_order(payload: ClaimNftOrderInput, request: Request):
    """
    Verifies on-chain Solana payment for a Lazy-Mint NFT Order, assigns the sequential
    edition number (#1..max_supply), mints the bundled Moltbook Alpha API key + credit lot,
    and returns an Ed25519-signed ownership & provenance witness certificate.
    """
    from nft_collection import MoltAlphaDemsCollection

    col = MoltAlphaDemsCollection()
    ledger = col._load_ledger()
    order = ledger.get("orders", {}).get(payload.order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"NFT order '{payload.order_id}' not found.",
        )

    if order.get("status") == "MINTED":
        return order["mint_receipt"]

    cfg = load_payment_config()
    verifier = SolanaPaymentVerifier(
        max_age_seconds=cfg.get("max_age_seconds", 3600),
        require_consensus=False,
    )
    try:
        verified = verifier.verify_payment(
            payload.transaction_signature.strip(),
            requested_tier=order["bundled_tier"],
            expected_payer=order["buyer_wallet"],
            expected_reference=order["memo_reference"],
        )
    except (VerificationError, RPCError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"On-chain payment verification failed for NFT order '{payload.order_id}': {e!s}",
        ) from e

    try:
        receipt = col.claim_lazy_mint_order(
            order_id=payload.order_id,
            tx_signature=verified.tx_signature,
            verified_payment=verified,
            storage=storage,
            witness_manager=witness_manager,
        )
        storage.log_audit_event(
            "nft_edition_minted",
            f"Minted {receipt['nft_name']} to {receipt['owner_wallet']} via tx {verified.tx_signature[:16]}...",
            ip_address=get_client_ip(request),
        )
        return receipt
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@app.get("/v1/intel/microstructure")
def get_intel_microstructure(
    request: Request,
    depth_bps: float = 50.0,
):
    """
    Returns fleet-wide DEX microstructure intelligence, active orderbook depth,
    and detected manipulation anomalies (tick vacuums, spoofed walls, fee volatility spikes)
    across tracked Solana concentrated liquidity pools.
    """
    tracked_pools = dex_microstructure.get_tracked_pools()
    pool_summaries = []
    for pid in tracked_pools:
        depth = dex_microstructure.get_latest_depth(pid)
        if depth:
            pool_summaries.append(depth.to_dict())

    anomalies = dex_microstructure.get_active_anomalies(limit=25)
    anomalies_data = [a.to_dict() for a in anomalies]

    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    witness_id = None
    if witness_manager:
        try:
            w = witness_manager.create_witness(
                action="MICROSTRUCTURE_FLEET_QUERY",
                actor="intel_engine_v1",
                key_hash=hashlib.sha256(f"fleet_{len(tracked_pools)}".encode()).hexdigest(),
                request_id=req_id,
                environmental_anchor={
                    "tracked_count": len(tracked_pools),
                    "anomalies_count": len(anomalies),
                    "depth_bps": depth_bps,
                },
            )
            witness_id = w.get("witness_id")
        except Exception:
            pass

    return {
        "status": "anomalies_detected" if anomalies else "healthy",
        "tracked_pool_count": len(tracked_pools),
        "active_anomaly_count": len(anomalies),
        "depth_bps": depth_bps,
        "pools": pool_summaries,
        "recent_anomalies": anomalies_data,
        "state_witness_id": witness_id,
        "timestamp_utc": time.time(),
    }


@app.get("/v1/intel/microstructure/{pool_id}")
def get_pool_microstructure(
    pool_id: str,
    request: Request,
    depth_bps: float = 50.0,
):
    """
    Returns deep orderbook liquidity distribution, tick arrays, bid/ask depth,
    imbalance ratio, and anomaly telemetry for a specific concentrated liquidity pool.
    Binds the observation to a verifiable cryptographic state witness.
    """
    depth = dex_microstructure.get_latest_depth(pool_id)
    if not depth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DEX pool '{pool_id}' is not tracked by the microstructure engine. Tracked: {dex_microstructure.get_tracked_pools()}",
        )

    pool_anomalies = [
        a.to_dict()
        for a in dex_microstructure.get_active_anomalies(limit=50)
        if a.pool_id == pool_id
    ]

    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    witness_record = None
    if witness_manager:
        try:
            witness_record = witness_manager.create_witness(
                action="POOL_MICROSTRUCTURE_OBSERVED",
                actor="dex_microstructure_engine",
                key_hash=hashlib.sha256(pool_id.encode()).hexdigest(),
                request_id=req_id,
                environmental_anchor={
                    "pool_id": pool_id,
                    "protocol": depth.protocol.value,
                    "current_price": depth.current_price,
                    "imbalance_ratio": depth.imbalance_ratio,
                    "bid_depth_usd": depth.bid_depth_usd,
                    "ask_depth_usd": depth.ask_depth_usd,
                },
            )
        except Exception:
            pass

    res = depth.to_dict()
    res["raw_bins"] = depth.raw_bins
    res["anomalies"] = pool_anomalies
    res["state_witness"] = witness_record
    return res


@app.post("/v1/intel/refresh")
def refresh_intelligence():
    """
    Triggers an immediate collection and synthesis cycle across all approved sources.
    """
    stats = intel_engine.collect_all_sources(dex_microstructure=dex_microstructure)
    signals_count = intel_engine.extract_signals(limit_items=100)
    briefing = intel_engine.generate_briefing(witness_manager=witness_manager)
    return {
        "status": "success",
        "sources_collected": stats,
        "signals_extracted": signals_count,
        "briefing_id": briefing["briefing_id"],
        "state_witness_id": briefing["state_witness_id"],
    }


class SubscribeWebhookInput(BaseModel):
    target_url: str
    secret_token: str
    subscribed_events: List[str] = ["ANOMALY_ALERT"]
    min_severity: str = "HIGH"

    @field_validator("target_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        from ops.security.egress_guard import validate_outbound_url, EgressSecurityError
        val = v.strip()
        try:
            return validate_outbound_url(val, allow_http=True, resolve_dns=False)
        except EgressSecurityError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("secret_token")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        val = v.strip()
        if len(val) < 8:
            raise ValueError("secret_token must be at least 8 characters")
        return val

    @field_validator("min_severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        val = v.strip().upper()
        if val not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            raise ValueError("min_severity must be LOW, MEDIUM, HIGH, or CRITICAL")
        return val


@app.post("/v1/webhooks/subscribe", status_code=status.HTTP_201_CREATED)
def subscribe_webhook(
    sub_input: SubscribeWebhookInput,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
):
    """
    Registers an automated HTTPS webhook subscription.
    When a DEX microstructure anomaly occurs matching the event filter and minimum severity,
    the event payload is signed with HMAC-SHA256 and pushed to target_url.
    """
    existing_active = storage.list_webhook_subscriptions(active_only=True)
    if len(existing_active) >= 100:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maximum active webhook subscriptions (100) reached. Delete unused subscriptions.",
        )

    subscription = storage.create_webhook_subscription(
        target_url=sub_input.target_url,
        secret_token=sub_input.secret_token,
        subscribed_events=sub_input.subscribed_events,
        min_severity=sub_input.min_severity,
    )
    storage.log_audit_event(
        "webhook_subscribed",
        f"Registered webhook {subscription['subscription_id']} for events {sub_input.subscribed_events}",
        ip_address=get_client_ip(request),
    )
    return subscription


@app.get("/v1/webhooks")
def list_webhooks(
    active_only: bool = True,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
):
    """
    Lists active webhook subscriptions with masked secret tokens.
    """
    subs = storage.list_webhook_subscriptions(active_only=active_only)
    masked = []
    for s in subs:
        item = dict(s)
        token = item.get("secret_token", "")
        if len(token) <= 4:
            item["secret_token"] = "****"
        else:
            item["secret_token"] = token[:2] + "****" + token[-2:]
        masked.append(item)
    return {
        "count": len(masked),
        "subscriptions": masked,
    }


@app.delete("/v1/webhooks/{subscription_id}")
def delete_webhook(
    subscription_id: str,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
):
    """
    Deregisters a webhook callback subscription.
    """
    deleted = storage.delete_webhook_subscription(subscription_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook subscription '{subscription_id}' not found.",
        )
    storage.log_audit_event(
        "webhook_deleted",
        f"Deleted webhook subscription {subscription_id}",
        ip_address=get_client_ip(request),
    )
    return {
        "status": "deleted",
        "subscription_id": subscription_id,
    }


@app.post("/v1/webhooks/test/{subscription_id}")
async def test_webhook(
    subscription_id: str,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
):
    """
    Dispatches a test ping payload signed with HMAC-SHA256 to verify webhook receiver connectivity.
    """
    sub = storage.get_webhook_subscription(subscription_id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook subscription '{subscription_id}' not found.",
        )

    test_data = {
        "test": True,
        "message": "Moltbook Alpha webhook test verification ping",
        "subscription_id": subscription_id,
        "subscribed_events": sub["subscribed_events"],
        "min_severity": sub["min_severity"],
        "timestamp": time.time(),
    }
    dispatch_result = await microstructure_broadcaster.dispatch_webhook(
        target_url=sub["target_url"],
        secret_token=sub["secret_token"],
        event_type="TEST_PING",
        data=test_data,
        timeout_seconds=5.0,
    )
    storage.log_audit_event(
        "webhook_tested",
        f"Tested webhook {subscription_id} to {sub['target_url']}: success={dispatch_result['success']}",
        ip_address=get_client_ip(request),
    )
    return {
        "subscription_id": subscription_id,
        "target_url": sub["target_url"],
        "dispatch_result": dispatch_result,
    }


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
    Real-time streaming WebSocket endpoint for verified Moltbook Alpha signals.
    Enforces per-session authentication and 1-credit lot deduction.
    Supports heartbeats, category filters, and live push notifications.
    """
    await websocket.accept()
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
