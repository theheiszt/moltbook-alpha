"""
Moltbook Alpha — Account Quota and Usage Routes.
"""

from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request, status
from routes.schemas import AccountQuotaUsageResponse
from app_state import (
    storage,
    rate_limiter,
    token_bucket_limiter,
    concurrency_limiter,
    get_client_ip,
    load_payment_config,
    record_rate_limit,
    DEFAULT_RATE_LIMIT_BURST_CAPACITY,
    DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
    DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
)

router = APIRouter(prefix="/v1/account", tags=["Account"])


def create_account_router() -> APIRouter:
    return router


@router.get("/quota", response_model=AccountQuotaUsageResponse)
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


@router.get("/usage", response_model=AccountQuotaUsageResponse)
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
