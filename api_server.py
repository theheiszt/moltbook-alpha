"""
Moltbook Alpha API Server with Hardened Solana / USDC Payment Verification.
Verifies on-chain transactions on Solana mainnet and automatically mints API keys
with ACID transactional SQLite storage, zero backdoors, rate limiting, and fail-closed security.
"""

from typing import Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
import uvicorn

from config import (
    DB_PATH,
    REPORTS_DIR,
    INDEX_HTML_PATH,
    BASE_DIR,
    BASE58_PATTERN,
    WEBHOOK_SECRET,
    load_payment_config,
    is_demo_keys_enabled,
)
from storage import StorageManager
from payment_verifier import (
    SolanaPaymentVerifier,
    VerifyPaymentInput,
    VerificationError,
    RPCError,
)
from rate_limiter import SlidingWindowRateLimiter, InFlightDeduplicator

app = FastAPI(
    title="Moltbook Alpha Intelligence API",
    description="Agentic Market Intelligence & Quant Insights with Solana Verification",
    version="1.2.0",
)

# Initialize storage, rate limiter, and deduplicator
storage = StorageManager(DB_PATH)
rate_limiter = SlidingWindowRateLimiter()
in_flight_deduplicator = InFlightDeduplicator()

# Run one-time legacy migration from api_keys.json if present (skipping any admin backdoors)
legacy_keys_file = BASE_DIR / "api_keys.json"
if legacy_keys_file.exists():
    storage.migrate_from_json(legacy_keys_file)


def get_client_ip(request: Request) -> str:
    """Extracts client IP address safely, respecting reverse-proxy X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def authenticate_and_deduct(api_key: Optional[str]) -> Dict[str, Any]:
    cfg = load_payment_config()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Payment Required",
                "message": "Access requires an active API key or payment.",
                "price": "$0.02 USDC per query or $20/month unlimited.",
                "purchase_instructions": {
                    "treasury_wallet": cfg["solana_treasury_wallet"],
                    "rates": cfg["rates"],
                    "verify_endpoint": "POST /v1/payments/verify-solana",
                },
            },
        )

    user_info, state = storage.authenticate_and_deduct(api_key)
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
    try:
        db_healthy = storage.check_health()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database health check failed: {e!s}",
        ) from e

    return {
        "status": "ok",
        "service": "moltbook-alpha-api",
        "database": "healthy" if db_healthy else "degraded",
    }


@app.get("/v1/payments/config")
def get_payment_details():
    cfg = load_payment_config()
    return {
        "success": True,
        "treasury_wallet": cfg["solana_treasury_wallet"],
        "accepted_assets": ["SOL", "USDC (Solana SPL)"],
        "pricing_tiers": cfg["rates"],
        "verification_guide": "Send SOL/USDC to treasury_wallet and post the signature to /v1/payments/verify-solana",
    }


@app.post("/v1/payments/verify-solana")
def verify_solana_payment(req: VerifyPaymentInput, request: Request, response: Response):
    client_ip = get_client_ip(request)

    # Rate limiting: max 10 payment verification attempts per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"verify_solana:{client_ip}", limit=10, window_seconds=60)
    if not allowed:
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
    verifier = SolanaPaymentVerifier()

    try:
        # In-flight deduplication: concurrent requests for the exact same signature
        # share the single ongoing verification rather than firing redundant RPC queries
        payment = in_flight_deduplicator.execute(
            sig,
            lambda: verifier.verify_payment(sig, req.target_tier),
        )
    except VerificationError as e:
        storage.log_audit_event(
            "payment_verification_failed",
            f"Verification rejected for sig={sig[:16]}...: {e!s}",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment verification failed: {e!s}",
        ) from e
    except RPCError as e:
        storage.log_audit_event(
            "payment_rpc_error",
            f"RPC failure verifying sig={sig[:16]}...: {e!s}",
            ip_address=client_ip,
        )
        # Network, timeout, or node failures fail closed with 502/503
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Solana RPC communication error: {e!s}",
        ) from e

    # Atomic redemption into persistent storage
    redemption_result = storage.redeem_payment(
        tx_signature=payment.tx_signature,
        asset=payment.asset,
        amount_raw=payment.amount_raw,
        tier=payment.tier,
        credits_to_grant=payment.credits,
    )

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
        f"Redeemed {payment.asset} (raw: {payment.amount_raw}) for tier {payment.tier} ({payment.credits} credits). Key: {redemption_result['key_prefix']} [rpc: {payment.rpc_endpoint_used}]",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "message": redemption_result["message"],
        "api_key": redemption_result["api_key"],
        "key_prefix": redemption_result["key_prefix"],
        "credits": redemption_result["credits"],
        "tier": redemption_result["tier"],
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
    verifier = SolanaPaymentVerifier()

    try:
        payment = in_flight_deduplicator.execute(
            sig,
            lambda: verifier.verify_payment(sig, req.target_tier),
        )
    except VerificationError as e:
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


@app.get("/v1/briefing/latest")
def get_latest_briefing(request: Request, x_api_key: Optional[str] = Header(None)):
    client_ip = get_client_ip(request)

    # General rate limit: 60 requests per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"briefing:{client_ip}", limit=60, window_seconds=60)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    user_info = authenticate_and_deduct(x_api_key)
    latest_path = REPORTS_DIR / "latest_briefing.md"
    if not latest_path.exists():
        raise HTTPException(status_code=404, detail="No briefing generated yet.")

    with open(latest_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "success": True,
        "user_tier": user_info.get("tier"),
        "credits_remaining": user_info.get("credits"),
        "briefing_markdown": content,
    }


if __name__ == "__main__":
    uvicorn.run("api_server:app", host="127.0.0.1", port=8080, reload=False)
