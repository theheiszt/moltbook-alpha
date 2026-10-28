"""
Tests for Real-Time WebSocket Streaming Endpoint (/v1/ws/alpha).
Verifies authentication via query param and message payload, credit quota deduction,
subscription filtering, heartbeat ping-pong, and error handling.
"""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api_server import app, storage


def test_websocket_unauthenticated_rejected():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/v1/ws/alpha") as ws:
            # Client doesn't send auth message within timeout or closes
            msg = ws.receive_json()
            assert msg.get("type") == "error"
            assert msg.get("code") == "AUTH_REQUIRED"
            ws.receive_json()  # triggers close
    assert exc_info.value.code == 4408


def test_websocket_invalid_key_rejected():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/v1/ws/alpha?token=molt_intel_invalid_bogus_key") as ws:
            msg = ws.receive_json()
            assert msg.get("type") == "error"
            assert msg.get("code") == "FORBIDDEN"
            ws.receive_json()
    assert exc_info.value.code == 4403


def test_websocket_exhausted_key_rejected():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="starter", credits=0, prefix_tag="molt_intel_api")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/v1/ws/alpha?api_key={raw_key}") as ws:
            msg = ws.receive_json()
            assert msg.get("type") == "error"
            assert msg.get("code") == "PAYMENT_REQUIRED"
            ws.receive_json()
    assert exc_info.value.code == 4402


def test_websocket_authenticated_streaming_and_ping_pong():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="starter", credits=10, prefix_tag="molt_intel_api")

    with client.websocket_connect(f"/v1/ws/alpha?token={raw_key}") as ws:
        # First message must be authenticated acknowledgment
        auth_ack = ws.receive_json()
        assert auth_ack["type"] == "authenticated"
        assert auth_ack["tier"] == "starter"
        assert auth_ack["remaining_credits"] == 9  # 1 credit deducted for live session

        # Heartbeat ping
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        # Note: Initial signal backlogs may precede pong if signals exist, consume until pong
        while pong.get("type") == "signal":
            pong = ws.receive_json()

        assert pong["type"] == "pong"
        assert "timestamp" in pong

        # Subscribe message
        ws.send_json({"type": "subscribe", "categories": ["market_alpha", "arbitrage_spread"], "min_confidence": "HIGH"})
        sub_ack = ws.receive_json()
        while sub_ack.get("type") == "signal":
            sub_ack = ws.receive_json()

        assert sub_ack["type"] == "subscribed"
        assert "arbitrage_spread" in sub_ack["categories"]


def test_websocket_auth_via_first_message():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="pro", credits=25, prefix_tag="molt_intel_api")

    with client.websocket_connect("/v1/ws/alpha") as ws:
        # Send auth message as first frame
        ws.send_json({"type": "auth", "api_key": raw_key})

        auth_ack = ws.receive_json()
        assert auth_ack["type"] == "authenticated"
        assert auth_ack["tier"] == "pro"
        assert auth_ack["remaining_credits"] == 24
