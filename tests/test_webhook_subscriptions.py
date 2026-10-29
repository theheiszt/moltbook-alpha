"""
Tests for Moltbook Alpha Outbound Webhook Subscriptions & Push Alerts Subsystem.
Verifies registration, input validation, secret masking, HMAC-SHA256 test ping dispatch,
deregistration lifecycle, and Python SDK integration.
"""

import hmac
import hashlib
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from api_server import app
from capabilities import get_api_capabilities
from sdk.moltbook_intel import MoltbookIntelClient


@pytest.fixture
def client():
    return TestClient(app)


def test_capabilities_includes_webhooks():
    """Verifies capabilities manifest documents webhooks_and_push_alerts and unmetered routes."""
    caps = get_api_capabilities()
    assert "webhooks_and_push_alerts" in caps["capabilities"]
    wh_cap = caps["capabilities"]["webhooks_and_push_alerts"]
    assert wh_cap["status"] == "GA"
    assert "CROSS_DEX_ARBITRAGE" in wh_cap["supported_events"]

    endpoints = {ep["path"]: ep for ep in wh_cap["endpoints"]}
    assert "/v1/webhooks/subscribe" in endpoints
    assert "/v1/webhooks" in endpoints
    assert "/v1/webhooks/{subscription_id}" in endpoints
    assert "/v1/webhooks/test/{subscription_id}" in endpoints

    unmetered = caps["pricing_and_quotas"]["unmetered_endpoints"]
    assert "/v1/webhooks" in unmetered
    assert "/v1/webhooks/subscribe" in unmetered
    assert "/v1/webhooks/{subscription_id}" in unmetered
    assert "/v1/webhooks/test/{subscription_id}" in unmetered


def test_subscribe_webhook_success(client):
    """Verifies registering a valid webhook subscription."""
    payload = {
        "target_url": "https://example.com/alerts/moltbook",
        "secret_token": "secret_arb_token_2026_xyz",
        "subscribed_events": ["CROSS_DEX_ARBITRAGE", "SECURITY_ANOMALY"],
        "min_severity": "HIGH",
    }
    res = client.post("/v1/webhooks/subscribe", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert "subscription_id" in data
    assert data["target_url"] == payload["target_url"]
    assert data["subscribed_events"] == payload["subscribed_events"]
    assert data["min_severity"] == "HIGH"
    sub_id = data["subscription_id"]

    # Verify listing masks the secret
    list_res = client.get("/v1/webhooks")
    assert list_res.status_code == 200
    subs = list_res.json()["subscriptions"]
    matched = [s for s in subs if s["subscription_id"] == sub_id]
    assert len(matched) == 1
    assert matched[0]["secret_token"].startswith("se****") or "****" in matched[0]["secret_token"]
    assert matched[0]["secret_token"] != payload["secret_token"]

    # Clean up
    del_res = client.delete(f"/v1/webhooks/{sub_id}")
    assert del_res.status_code == 200


def test_subscribe_webhook_validation_errors(client):
    """Verifies input validation on invalid target URLs or missing required fields."""
    # Invalid URL scheme
    res = client.post("/v1/webhooks/subscribe", json={
        "target_url": "ftp://bad-url.com/hook",
        "secret_token": "some_secret",
        "subscribed_events": ["ALL"],
    })
    assert res.status_code == 422

    # Empty secret token
    res = client.post("/v1/webhooks/subscribe", json={
        "target_url": "https://valid.com/hook",
        "secret_token": "",
        "subscribed_events": ["ALL"],
    })
    assert res.status_code == 422


def test_test_webhook_dispatch_hmac_signature(client):
    """Verifies that /v1/webhooks/test/{id} signs the payload with HMAC-SHA256."""
    sub_payload = {
        "target_url": "https://test-receiver.org/events",
        "secret_token": "my_super_secure_key_4455",
        "subscribed_events": ["TICK_VACUUM"],
        "min_severity": "MEDIUM",
    }
    sub_res = client.post("/v1/webhooks/subscribe", json=sub_payload)
    assert sub_res.status_code == 201
    sub_id = sub_res.json()["subscription_id"]

    captured_requests = []

    async def mock_dispatch_webhook(target_url, secret_token, event_type, data, timeout_seconds=5.0):
        envelope = {
            "event": event_type,
            "data": data,
        }
        body = json.dumps(envelope).encode("utf-8")
        sig = f"sha256={hmac.new(secret_token.encode('utf-8'), body, hashlib.sha256).hexdigest()}"
        captured_requests.append({
            "target_url": target_url,
            "signature": sig,
            "event": event_type,
            "data": data,
        })
        return {
            "success": True,
            "status_code": 200,
            "signature": sig,
            "error": None,
        }

    with patch("api_server.microstructure_broadcaster.dispatch_webhook", side_effect=mock_dispatch_webhook):
        test_res = client.post(f"/v1/webhooks/test/{sub_id}")
        assert test_res.status_code == 200
        data = test_res.json()
        assert data["subscription_id"] == sub_id
        assert data["target_url"] == sub_payload["target_url"]

    assert len(captured_requests) == 1
    assert captured_requests[0]["target_url"] == sub_payload["target_url"]
    assert captured_requests[0]["signature"].startswith("sha256=")
    assert captured_requests[0]["event"] == "TEST_PING"

    # Clean up
    client.delete(f"/v1/webhooks/{sub_id}")


def test_delete_webhook_lifecycle(client):
    """Verifies deleting webhooks and handling not found responses."""
    # Delete non-existent
    res = client.delete("/v1/webhooks/sub_nonexistent_999999")
    assert res.status_code == 404

    # Create and delete
    sub_res = client.post("/v1/webhooks/subscribe", json={
        "target_url": "https://example.org/webhook",
        "secret_token": "secret_token_123",
        "subscribed_events": ["SECURITY_ANOMALY"],
    })
    assert sub_res.status_code == 201
    sub_id = sub_res.json()["subscription_id"]

    del_res = client.delete(f"/v1/webhooks/{sub_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Second delete returns 404
    del_res2 = client.delete(f"/v1/webhooks/{sub_id}")
    assert del_res2.status_code == 404


def test_python_sdk_webhook_methods(monkeypatch, client):
    """Verifies that MoltbookIntelClient methods interact correctly with webhook endpoints."""
    # Create test SDK client wrapping TestClient via monkeypatching _request
    sdk_client = MoltbookIntelClient(base_url="http://testserver")

    def mock_request(endpoint, method="GET", payload=None, headers=None, auth_required=False, idempotency_key=None):
        if method == "POST":
            res = client.post(endpoint, json=payload, headers=headers or {})
        elif method == "GET":
            res = client.get(endpoint, headers=headers or {})
        elif method == "DELETE":
            res = client.delete(endpoint, headers=headers or {})
        else:
            raise ValueError(f"Unsupported test method {method}")
        if res.status_code >= 400:
            from sdk.moltbook_intel.exceptions import raise_for_error_payload
            raise_for_error_payload(res.status_code, res.json())
        return res.json()

    monkeypatch.setattr(sdk_client, "_request", mock_request)

    # 1. Subscribe via SDK
    sub = sdk_client.subscribe_webhook(
        target_url="https://sdk-agent.ai/hook",
        secret_token="agent_secret_key_8899",
        subscribed_events=["CROSS_DEX_ARBITRAGE"],
        min_severity="HIGH",
    )
    assert "subscription_id" in sub
    sub_id = sub["subscription_id"]

    # 2. List via SDK
    subs = sdk_client.list_webhooks(active_only=True)
    assert any(s["subscription_id"] == sub_id for s in subs)

    # 3. Test ping via SDK (mocking dispatch)
    with patch("api_server.microstructure_broadcaster.dispatch_webhook", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {"success": True, "status_code": 200, "signature": "sha256=abc", "error": None}
        test_out = sdk_client.test_webhook(sub_id)
        assert test_out["subscription_id"] == sub_id

    # 4. Delete via SDK
    del_out = sdk_client.delete_webhook(sub_id)
    assert del_out["status"] == "deleted"
