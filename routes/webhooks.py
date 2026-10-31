"""
Moltbook Alpha — Webhook Subscriptions and Management Routes.
"""

import time
from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from app_state import (
    storage,
    get_client_ip,
)
from ops.trading.dex_microstructure import microstructure_broadcaster

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])


def create_webhooks_router() -> APIRouter:
    return router


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


@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
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


@router.get("")
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


@router.delete("/{subscription_id}")
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


@router.post("/test/{subscription_id}")
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
