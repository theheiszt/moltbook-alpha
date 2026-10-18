"""
Moltbook Alpha API Server with Hardened Solana / USDC Payment Verification.
Verifies on-chain transactions on Solana mainnet and automatically mints API keys
with ACID transactional SQLite storage, zero backdoors, rate limiting, and fail-closed security.
"""

import os
import ipaddress
import secrets
import re
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, field_validator
import uvicorn

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
from storage import StorageManager, StorageError
from payment_verifier import (
    SolanaPaymentVerifier,
    VerifyPaymentInput,
    VerificationError,
    RPCError,
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

app = FastAPI(
    title="Moltbook Alpha Intelligence API",
    description="Agentic Market Intelligence & Quant Insights with Solana Verification",
    version="1.2.0",
)


@app.middleware("http")
async def request_tracing_middleware(request: Request, call_next):
    req_id = request.headers.get("x-request-id")
    if not req_id or not re.match(r"^[a-zA-Z0-9_\-\.]{8,64}$", req_id):
        req_id = f"req_{secrets.token_hex(8)}"
    request.state.request_id = req_id

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
        elif endpoint.startswith("/v1/errors/"):
            norm_endpoint = "/v1/errors/:code"
        elif endpoint.startswith("/v1/tools/") and endpoint.endswith("/parameter-graph"):
            norm_endpoint = "/v1/tools/:tool/parameter-graph"
        elif endpoint.startswith("/v1/challenges/") and endpoint != "/v1/challenges/verify":
            norm_endpoint = "/v1/challenges/:id"
        elif endpoint.startswith("/v1/witnesses/") and endpoint not in {"/v1/witnesses/public-keys", "/v1/witnesses/verify"}:
            norm_endpoint = "/v1/witnesses/:id"
        elif endpoint in {
            "/",
            "/metrics",
            "/v1/health",
            "/v1/errors",
            "/v1/challenges",
            "/v1/challenges/verify",
            "/v1/tools",
            "/v1/witnesses/public-keys",
            "/v1/witnesses/verify",
            "/v1/intel/latest",
            "/v1/intel/signals",
            "/v1/intel/refresh",
            "/v1/payments/config",
            "/v1/payments/invoice",
            "/v1/payments/verify-solana",
            "/v1/payments/webhook",
            "/v1/keys/generate-demo",
            "/v1/briefing/latest",
            "/v1/account/quota",
        }:
            norm_endpoint = endpoint
        else:
            norm_endpoint = "unmatched_route"
        record_request(norm_endpoint, request.method, status_code)


@app.middleware("http")
async def timeout_and_rate_limit_middleware(request: Request, call_next):
    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
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


class CreateInvoiceInput(BaseModel):
    target_tier: Optional[str] = "tier_starter"
    asset: Optional[str] = "USDC"
    expected_payer: Optional[str] = None
    target_api_key: Optional[str] = None

    @field_validator("target_tier")
    @classmethod
    def validate_tier(cls, v: Optional[str]) -> str:
        t = (v or "tier_starter").strip()
        cfg = load_payment_config()
        valid = list(cfg["rates"].keys()) + list(cfg.get("topup_packages", {}).keys())
        if t not in valid:
            raise ValueError(f"Unknown target_tier '{t}'. Must be one of: {valid}")
        return t

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, v: Optional[str]) -> str:
        a = (v or "USDC").strip().upper()
        if a not in ("USDC", "SOL"):
            raise ValueError("Asset must be 'USDC' or 'SOL'.")
        return a

    @field_validator("expected_payer")
    @classmethod
    def validate_payer(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        s = v.strip()
        if not (32 <= len(s) <= 44) or not BASE58_PATTERN.match(s):
            raise ValueError("expected_payer must be valid base58 between 32 and 44 characters.")
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


@app.get("/v1/payments/config")
def get_payment_details():
    cfg = load_payment_config()
    return {
        "success": True,
        "treasury_wallet": cfg["solana_treasury_wallet"],
        "accepted_assets": ["SOL", "USDC (Solana SPL)"],
        "pricing_tiers": cfg["rates"],
        "topup_packages": cfg.get("topup_packages", {}),
        "create_invoice_endpoint": "POST /v1/payments/invoice",
        "verify_endpoint": "POST /v1/payments/verify-solana",
        "claim_endpoint": "POST /v1/payments/invoice/:invoice_id/claim",
        "verification_guide": (
            "1. Create an invoice via POST /v1/payments/invoice. "
            "2. Send SOL/USDC to treasury_wallet with invoice reference account. "
            "3. Submit signature and invoice_id to /v1/payments/verify-solana."
        ),
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
        raw_amount = tier_info["usdc_units"] if req.asset == "USDC" else tier_info["sol_lamports"]
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

    inv_record, claim_secret, reference = storage.create_invoice(
        tier=req.target_tier,
        credits=credits,
        asset=req.asset,
        amount_raw=raw_amount,
        recipient=cfg["solana_treasury_wallet"],
        cluster=cfg.get("cluster", "mainnet-beta"),
        expiry_seconds=ttl,
        expected_payer=req.expected_payer,
        target_key_hash=target_key_hash,
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
        return {
            "success": True,
            "message": "Key previously redeemed for this transaction signature.",
            "key_prefix": existing_redemption["key_prefix"],
            "tier": existing_redemption["tier"],
            "credits": existing_redemption["remaining_credits"],
            "invoice_id": existing_redemption.get("invoice_id") or req.invoice_id,
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
            return {
                "success": True,
                "message": "Invoice was already fulfilled.",
                "key_prefix": redemption["key_prefix"] if redemption else "",
                "tier": invoice["tier"],
                "credits": invoice["credits"],
                "invoice_id": invoice["invoice_id"],
            }
        if invoice["status"] == "expired":
            raise ApiError(
                code=ErrorCode.INVOICE_EXPIRED,
                status_code=400,
                message=f"Invoice '{req.invoice_id}' has expired. Please create a new invoice.",
                outcome=OperationOutcome.NOT_COMMITTED,
                state_effect="none",
                recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            )
        now_iso = datetime.now(timezone.utc).isoformat()
        if now_iso > invoice["expires_at"]:
            raise ApiError(
                code=ErrorCode.INVOICE_EXPIRED,
                status_code=400,
                message=f"Invoice '{req.invoice_id}' expired at {invoice['expires_at']}.",
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

    verifier = SolanaPaymentVerifier(max_age_seconds=cfg.get("max_age_seconds", 1800))

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
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"Payment asset '{payment.asset}' does not match invoice expected asset '{invoice['asset']}'.",
        )
    if payment.amount_raw < invoice["amount_raw"]:
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"Payment amount ({payment.amount_raw}) is below invoice required amount ({invoice['amount_raw']}).",
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
    verifier = SolanaPaymentVerifier(max_age_seconds=cfg.get("max_age_seconds", 1800))

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

        res = {
            "success": True,
            "user_tier": res_info.get("tier"),
            "credits_remaining": res_info.get("credits"),
            "briefing_markdown": content,
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


@app.post("/v1/intel/refresh")
def refresh_intelligence():
    """
    Triggers an immediate collection and synthesis cycle across all approved sources.
    """
    stats = intel_engine.collect_all_sources()
    signals_count = intel_engine.extract_signals(limit_items=100)
    briefing = intel_engine.generate_briefing(witness_manager=witness_manager)
    return {
        "status": "success",
        "sources_collected": stats,
        "signals_extracted": signals_count,
        "briefing_id": briefing["briefing_id"],
        "state_witness_id": briefing["state_witness_id"],
    }


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
