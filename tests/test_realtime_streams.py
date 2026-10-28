"""
Unit and integration tests for Pillar 3: Real-Time WebSocket & Webhook Subscriptions.
Tests /v1/ws/microstructure, subscribe/ping/pong, tick deltas, HMAC-SHA256 webhook dispatch.
"""

import asyncio
import hashlib
import hmac
import json
import httpx
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from api_server import app
from ops.trading.dex_microstructure import (
    MicrostructureBroadcaster,
    microstructure_broadcaster,
    TickLiquidityDepth,
    MicrostructureAnomaly,
    DEXProtocol,
)


@pytest.fixture
def client():
    return TestClient(app)


# =============================================================================
# WebSocket /v1/ws/microstructure Tests
# =============================================================================


def test_websocket_microstructure_handshake_and_ping(client):
    """Verifies WebSocket connection handshake, pool catalogue, and ping/pong."""
    with client.websocket_connect("/v1/ws/microstructure") as ws:
        init_frame = ws.receive_json()
        assert init_frame["type"] == "connected"
        assert "session_id" in init_frame
        assert isinstance(init_frame["tracked_pools"], list)
        assert len(init_frame["tracked_pools"]) >= 1

        # Test heartbeat ping/pong
        ws.send_json({"type": "ping"})
        pong_frame = ws.receive_json()
        assert pong_frame["type"] == "pong"
        assert pong_frame["session_id"] == init_frame["session_id"]


def test_websocket_pool_subscription_filtering(client):
    """Verifies that clients can subscribe to specific pools and receive tick deltas."""
    with client.websocket_connect("/v1/ws/microstructure") as ws:
        ws.receive_json()  # Consume initial 'connected' frame

        # Subscribe to Raydium_SOL_USDC only
        ws.send_json({"type": "subscribe", "pools": ["Raydium_SOL_USDC"]})
        sub_ack = ws.receive_json()
        assert sub_ack["type"] == "subscribed"
        assert "Raydium_SOL_USDC" in sub_ack["pools"]

        # Synthesize a depth update for Raydium
        depth = TickLiquidityDepth(
            pool_id="Raydium_SOL_USDC",
            protocol=DEXProtocol.RAYDIUM_CLMM,
            pair="SOL/USDC",
            current_tick=-15620,
            current_price=103.50,
            bid_depth_usd=250000.0,
            ask_depth_usd=230000.0,
            imbalance_ratio=0.0417,
            active_bin_count=5,
            timestamp_utc=1700000000.0,
        )

        asyncio.run(microstructure_broadcaster.broadcast_tick_delta(depth))

        delta_frame = ws.receive_json()
        assert delta_frame["type"] == "TICK_DELTA"
        assert delta_frame["data"]["pool_id"] == "Raydium_SOL_USDC"
        assert delta_frame["data"]["current_price"] == 103.50


def test_websocket_anomaly_alert_broadcast(client):
    """Verifies that anomaly alerts are dispatched over WebSocket."""
    with client.websocket_connect("/v1/ws/microstructure") as ws:
        ws.receive_json()  # Consume initial 'connected' frame

        # Subscribed to all pools by default
        anomaly = MicrostructureAnomaly(
            pool_id="Orca_SOL_USDC",
            protocol=DEXProtocol.ORCA_WHIRLPOOL,
            anomaly_type="TICK_VACUUM",
            severity="CRITICAL",
            confidence_score=0.98,
            evidence_details={"thin_side": "ask", "ratio": 12.5},
            detected_at=1700000010.0,
        )

        asyncio.run(microstructure_broadcaster.broadcast_anomaly(anomaly))

        alert_frame = ws.receive_json()
        assert alert_frame["type"] == "ANOMALY_ALERT"
        assert alert_frame["data"]["anomaly_type"] == "TICK_VACUUM"
        assert alert_frame["data"]["severity"] == "CRITICAL"
        assert alert_frame["data"]["confidence_score"] == 0.98


# =============================================================================
# Webhook Subscription Management (CRUD) Tests
# =============================================================================


def test_webhook_subscribe_validation_errors(client):
    """Ensures invalid URLs, weak secrets, and invalid severities are rejected."""
    # Invalid URL
    res = client.post("/v1/webhooks/subscribe", json={
        "target_url": "ftp://bad-url",
        "secret_token": "valid_secret_123",
        "subscribed_events": ["ANOMALY_ALERT"],
    })
    assert res.status_code == 422

    # Secret too short (< 8 chars)
    res = client.post("/v1/webhooks/subscribe", json={
        "target_url": "https://example.com/webhook",
        "secret_token": "short",
        "subscribed_events": ["ANOMALY_ALERT"],
    })
    assert res.status_code == 422

    # Invalid severity
    res = client.post("/v1/webhooks/subscribe", json={
        "target_url": "https://example.com/webhook",
        "secret_token": "valid_secret_123",
        "min_severity": "SUPER_HIGH",
    })
    assert res.status_code == 422


def test_webhook_lifecycle_and_masking(client):
    """Verifies registration, listing with masked secrets, and deletion."""
    secret = "super_secret_webhook_key_2026"
    sub_payload = {
        "target_url": "https://agent-receiver.xyz/moltbook-hooks",
        "secret_token": secret,
        "subscribed_events": ["ANOMALY_ALERT", "TICK_DELTA"],
        "min_severity": "HIGH",
    }
    # 1. Register subscription
    res_sub = client.post("/v1/webhooks/subscribe", json=sub_payload)
    assert res_sub.status_code == 201
    sub_data = res_sub.json()
    sub_id = sub_data["subscription_id"]
    assert sub_id.startswith("whsub_")
    assert sub_data["target_url"] == sub_payload["target_url"]
    assert sub_data["min_severity"] == "HIGH"
    assert sub_data["is_active"] is True

    # 2. List webhooks (verifying secret token is masked)
    res_list = client.get("/v1/webhooks")
    assert res_list.status_code == 200
    list_data = res_list.json()
    matching = [s for s in list_data["subscriptions"] if s["subscription_id"] == sub_id]
    assert len(matching) == 1
    masked_item = matching[0]
    assert masked_item["secret_token"] != secret
    assert "****" in masked_item["secret_token"]
    assert masked_item["secret_token"].startswith(secret[:2])
    assert masked_item["secret_token"].endswith(secret[-2:])

    # 3. Delete subscription
    res_del = client.delete(f"/v1/webhooks/{sub_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "deleted"

    # 4. Deleting again should return 404
    res_del_again = client.delete(f"/v1/webhooks/{sub_id}")
    assert res_del_again.status_code == 404


# =============================================================================
# Webhook Test Dispatch & HMAC-SHA256 Signature Verification
# =============================================================================


def test_webhook_test_dispatch_signature(client):
    """Verifies /v1/webhooks/test/{id} signs payloads with HMAC-SHA256."""
    secret = "hmac_verification_secret_key_999"
    sub_res = client.post("/v1/webhooks/subscribe", json={
        "target_url": "https://mock-endpoint.moltbook.internal/hook",
        "secret_token": secret,
        "subscribed_events": ["ALL"],
        "min_severity": "MEDIUM",
    })
    sub_id = sub_res.json()["subscription_id"]

    captured_requests = []

    async def mock_post(self, url, content=None, headers=None):
        class MockResponse:
            status_code = 200
            is_success = True

        captured_requests.append({
            "url": url,
            "content": content,
            "headers": headers,
        })
        return MockResponse()

    with patch.object(httpx.AsyncClient, "post", mock_post):
        test_res = client.post(f"/v1/webhooks/test/{sub_id}")
        assert test_res.status_code == 200
        test_data = test_res.json()
        assert test_data["subscription_id"] == sub_id
        assert test_data["dispatch_result"]["success"] is True

        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert req["url"] == "https://mock-endpoint.moltbook.internal/hook"

        # Verify HMAC-SHA256 signature
        sent_sig = req["headers"].get("X-Moltbook-Signature")
        assert sent_sig is not None
        assert sent_sig.startswith("sha256=")

        # Compute expected HMAC
        expected_hash = hmac.new(secret.encode("utf-8"), req["content"], hashlib.sha256).hexdigest()
        expected_sig = f"sha256={expected_hash}"
        assert sent_sig == expected_sig

        # Verify payload structure
        payload = json.loads(req["content"].decode("utf-8"))
        assert payload["event"] == "TEST_PING"
        assert payload["data"]["test"] is True
        assert payload["data"]["subscription_id"] == sub_id

    # Clean up
    client.delete(f"/v1/webhooks/{sub_id}")


# =============================================================================
# Broadcaster Unit Tests & Multi-Webhook Routing
# =============================================================================


def test_broadcaster_severity_and_event_filtering():
    """Tests dispatch_to_matching_webhooks filtering logic."""
    broadcaster = MicrostructureBroadcaster()

    class MockStorage:
        def list_webhook_subscriptions(self, active_only=True):
            return [
                {
                    "subscription_id": "whsub_critical_only",
                    "target_url": "https://example.com/crit",
                    "secret_token": "secret_1",
                    "subscribed_events": ["ANOMALY_ALERT"],
                    "min_severity": "CRITICAL",
                },
                {
                    "subscription_id": "whsub_high_or_better",
                    "target_url": "https://example.com/high",
                    "secret_token": "secret_2",
                    "subscribed_events": ["ANOMALY_ALERT"],
                    "min_severity": "HIGH",
                },
                {
                    "subscription_id": "whsub_ticks_only",
                    "target_url": "https://example.com/ticks",
                    "secret_token": "secret_3",
                    "subscribed_events": ["TICK_DELTA"],
                    "min_severity": "LOW",
                },
            ]

    # Mock dispatch_webhook to avoid network calls
    async def mock_dispatch(target_url, secret_token, event_type, data):
        return {"success": True, "status_code": 200, "url": target_url}

    broadcaster.dispatch_webhook = mock_dispatch

    mock_storage = MockStorage()

    # 1. Fire a HIGH severity ANOMALY_ALERT
    # Should match 'whsub_high_or_better', but NOT 'whsub_critical_only' or 'whsub_ticks_only'
    results_high = asyncio.run(
        broadcaster.dispatch_to_matching_webhooks(
            storage=mock_storage,
            event_type="ANOMALY_ALERT",
            data={"test": "high_anomaly"},
            severity="HIGH",
        )
    )
    assert len(results_high) == 1
    assert results_high[0]["subscription_id"] == "whsub_high_or_better"

    # 2. Fire a CRITICAL severity ANOMALY_ALERT
    # Should match BOTH 'whsub_critical_only' AND 'whsub_high_or_better'
    results_crit = asyncio.run(
        broadcaster.dispatch_to_matching_webhooks(
            storage=mock_storage,
            event_type="ANOMALY_ALERT",
            data={"test": "crit_anomaly"},
            severity="CRITICAL",
        )
    )
    assert len(results_crit) == 2
    matched_ids = {r["subscription_id"] for r in results_crit}
    assert matched_ids == {"whsub_critical_only", "whsub_high_or_better"}
