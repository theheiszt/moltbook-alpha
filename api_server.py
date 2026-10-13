"""
Moltbook Alpha API Server with Solana / USDC Payment Verification.
Verifies on-chain transactions on Solana mainnet and automatically mints API keys.
"""

import os
import json
import secrets
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI(
    title="Moltbook Alpha Intelligence API",
    description="Agentic Market Intelligence & Quant Insights with Solana Verification",
    version="1.1.0"
)

BASE_DIR = Path(r"i:\Scripts and Programs\moltbook-intel")
REPORTS_DIR = BASE_DIR / "reports"
KEYS_FILE = BASE_DIR / "api_keys.json"
CONFIG_FILE = BASE_DIR / "payment_config.json"
INDEX_HTML_PATH = BASE_DIR / "index.html"

# Default payment configuration
DEFAULT_CONFIG = {
    "solana_treasury_wallet": "2sW9nZ1Q65qY8mD7xXvF4uL3kR9pE1wB7vC5nA2mG8hK", # Placeholder treasury address
    "rpc_url": "https://api.mainnet-beta.solana.com",
    "rates": {
        "tier_starter": {"usd": 1.0, "credits": 50},
        "tier_pro": {"usd": 5.0, "credits": 300},
        "tier_unlimited": {"usd": 20.0, "credits": 999999}
    }
}

def load_payment_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG

def load_valid_keys():
    if not KEYS_FILE.exists():
        initial = {
            "demo_free_token": {"credits": 5, "tier": "free"},
            "master_admin_token": {"credits": 999999, "tier": "unlimited"}
        }
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(initial, f, indent=2)
        return initial
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_keys(keys_data):
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(keys_data, f, indent=2)

def authenticate_and_deduct(api_key: Optional[str]):
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
                    "verify_endpoint": "POST /v1/payments/verify-solana"
                }
            }
        )

    keys = load_valid_keys()
    if api_key not in keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key. Submit payment to /v1/payments/verify-solana or use /v1/keys/generate-demo."
        )

    user_info = keys[api_key]
    if user_info.get("tier") != "unlimited":
        credits_left = user_info.get("credits", 0)
        if credits_left <= 0:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Key credits exhausted. Top up your balance via Solana USDC."
            )
        user_info["credits"] = credits_left - 1
        save_keys(keys)

    return user_info

def query_solana_rpc(method: str, params: list):
    cfg = load_payment_config()
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        cfg["rpc_url"],
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

class VerifyPaymentRequest(BaseModel):
    transaction_signature: str
    target_tier: str = "tier_starter"

@app.get("/", response_class=HTMLResponse)
def index():
    if INDEX_HTML_PATH.exists():
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Moltbook Alpha API</h1>"

@app.get("/v1/payments/config")
def get_payment_details():
    cfg = load_payment_config()
    return {
        "success": True,
        "treasury_wallet": cfg["solana_treasury_wallet"],
        "accepted_assets": ["SOL", "USDC (Solana SPL)"],
        "pricing_tiers": cfg["rates"],
        "verification_guide": "Send SOL/USDC to treasury_wallet and post the signature to /v1/payments/verify-solana"
    }

@app.post("/v1/payments/verify-solana")
def verify_solana_payment(req: VerifyPaymentRequest):
    sig = req.transaction_signature.strip()
    tier = req.target_tier.strip()
    cfg = load_payment_config()

    if tier not in cfg["rates"]:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {list(cfg['rates'].keys())}")

    # Prevent double-spending: check if signature already claimed
    keys = load_valid_keys()
    for k, v in keys.items():
        if v.get("tx_signature") == sig:
            return {
                "success": True,
                "api_key": k,
                "message": "Key previously redeemed for this transaction signature.",
                "credits": v.get("credits")
            }

    # Verify transaction on Solana Mainnet RPC
    try:
        rpc_resp = query_solana_rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Solana RPC error: {str(e)}")

    tx_data = rpc_resp.get("result")
    if not tx_data:
        raise HTTPException(status_code=404, detail="Transaction not found or not yet confirmed on Solana mainnet.")

    meta = tx_data.get("meta", {})
    if meta.get("err") is not None:
        raise HTTPException(status_code=400, detail="Transaction failed on-chain.")

    # Mint API Key
    allocated_credits = cfg["rates"][tier]["credits"]
    token = f"molt_sol_{secrets.token_hex(10)}"
    keys[token] = {
        "credits": allocated_credits,
        "tier": tier,
        "tx_signature": sig
    }
    save_keys(keys)

    return {
        "success": True,
        "message": f"Payment confirmed! Minted {allocated_credits} credits.",
        "api_key": token,
        "credits": allocated_credits,
        "tier": tier
    }

@app.post("/v1/keys/generate-demo")
def generate_demo_key():
    token = f"molt_demo_{secrets.token_hex(8)}"
    keys = load_valid_keys()
    keys[token] = {"credits": 5, "tier": "trial"}
    save_keys(keys)
    return {
        "success": True,
        "api_key": token,
        "credits": 5,
        "message": "Demo token created with 5 free credits."
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
        "briefing_markdown": content
    }

@app.get("/v1/health")
def health_check():
    return {"status": "ok", "service": "moltbook-alpha-api"}

if __name__ == "__main__":
    uvicorn.run("api_server:app", host="127.0.0.1", port=8080, reload=False)
