"""
Moltbook Alpha API Server with Hardened Solana / USDC Payment Verification.
Verifies on-chain transactions on Solana mainnet and automatically mints API keys
with ACID transactional SQLite storage, zero backdoors, and fail-closed security.
"""

from typing import Optional, Dict, Any
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
import uvicorn

from config import (
    DB_PATH,
    REPORTS_DIR,
    INDEX_HTML_PATH,
    BASE_DIR,
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

app = FastAPI(
    title="Moltbook Alpha Intelligence API",
    description="Agentic Market Intelligence & Quant Insights with Solana Verification",
    version="1.1.0",
)

# Initialize storage and verify payment config at startup
storage = StorageManager(DB_PATH)

# Run one-time legacy migration from api_keys.json if present (skipping any admin backdoors)
legacy_keys_file = BASE_DIR / "api_keys.json"
if legacy_keys_file.exists():
    storage.migrate_from_json(legacy_keys_file)


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
    return {"status": "ok", "service": "moltbook-alpha-api"}


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
def verify_solana_payment(req: VerifyPaymentInput):
    sig = req.transaction_signature.strip()
    verifier = SolanaPaymentVerifier()

    try:
        payment = verifier.verify_payment(sig, req.target_tier)
    except VerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment verification failed: {e!s}",
        ) from e
    except RPCError as e:
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
        return {
            "success": True,
            "message": "Key previously redeemed for this transaction signature.",
            "key_prefix": redemption_result["key_prefix"],
            "tier": redemption_result["tier"],
            "credits": redemption_result["credits"],
        }

    return {
        "success": True,
        "message": redemption_result["message"],
        "api_key": redemption_result["api_key"],
        "key_prefix": redemption_result["key_prefix"],
        "credits": redemption_result["credits"],
        "tier": redemption_result["tier"],
    }


@app.post("/v1/keys/generate-demo")
def generate_demo_key():
    if not is_demo_keys_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo key issuance is disabled. Provide payment or contact administrator.",
        )

    raw_token, record = storage.create_api_key(tier="trial", credits=5, prefix_tag="molt_demo")
    return {
        "success": True,
        "api_key": raw_token,
        "key_prefix": record["key_prefix"],
        "credits": 5,
        "message": "Demo token created with 5 free credits.",
    }


@app.get("/v1/briefing/latest")
def get_latest_briefing(x_api_key: Optional[str] = Header(None)):
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
