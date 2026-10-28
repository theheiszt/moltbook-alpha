"""
Unit & Integration Tests for Outbound Egress Guard & SSRF Firewall (ops/security/egress_guard.py).
"""

import pytest
from starlette.testclient import TestClient

from ops.security.egress_guard import (
    validate_outbound_url,
    EgressSecurityError,
    egress_audit,
    is_ip_blocked,
)
import ipaddress
from api_server import app


def setup_function():
    egress_audit.clear()


def test_blocks_loopback_literal():
    with pytest.raises(EgressSecurityError) as exc:
        validate_outbound_url("http://127.0.0.1:8000/api")
    assert "restricted IP address" in str(exc.value)

    with pytest.raises(EgressSecurityError) as exc2:
        validate_outbound_url("http://127.0.1.1/hook")
    assert "restricted IP address" in str(exc2.value)


def test_blocks_localhost_hostname():
    with pytest.raises(EgressSecurityError) as exc:
        validate_outbound_url("http://localhost:8080/events")
    assert "localhost" in str(exc.value)


def test_blocks_private_rfc1918():
    for private_url in [
        "https://10.0.0.1/webhook",
        "https://172.16.0.50:8443/alert",
        "http://192.168.1.100:8080/callback",
    ]:
        with pytest.raises(EgressSecurityError):
            validate_outbound_url(private_url)


def test_blocks_cloud_metadata():
    metadata_url = "http://169.254.169.254/latest/meta-data/"
    with pytest.raises(EgressSecurityError) as exc:
        validate_outbound_url(metadata_url)
    assert "restricted IP address" in str(exc.value)


def test_blocks_ipv6_loopback():
    with pytest.raises(EgressSecurityError):
        validate_outbound_url("http://[::1]:8080/hook")


def test_blocks_decimal_ip_encoding():
    # 2130706433 is integer encoding for 127.0.0.1
    with pytest.raises(EgressSecurityError):
        validate_outbound_url("http://2130706433/hook")


def test_blocks_forbidden_ports():
    with pytest.raises(EgressSecurityError) as exc:
        validate_outbound_url("https://example.com:22/hook")
    assert "Port 22" in str(exc.value)

    with pytest.raises(EgressSecurityError) as exc2:
        validate_outbound_url("https://example.com:3389/hook")
    assert "Port 3389" in str(exc2.value)


def test_blocks_forbidden_schemes():
    with pytest.raises(EgressSecurityError) as exc:
        validate_outbound_url("ftp://example.com/hook")
    assert "Scheme 'ftp'" in str(exc.value)

    with pytest.raises(EgressSecurityError) as exc2:
        validate_outbound_url("file:///etc/passwd")
    assert "Scheme 'file'" in str(exc2.value)


def test_allows_valid_domains():
    valid = validate_outbound_url("https://example.com/webhook")
    assert valid == "https://example.com/webhook"

    valid_mock = validate_outbound_url("https://mock-endpoint.moltbook.internal/hook")
    assert valid_mock == "https://mock-endpoint.moltbook.internal/hook"


def test_audit_ring_buffer_records_blocks():
    egress_audit.clear()
    try:
        validate_outbound_url("http://169.254.169.254/metadata")
    except EgressSecurityError:
        pass

    try:
        validate_outbound_url("http://127.0.0.1:8000/local")
    except EgressSecurityError:
        pass

    blocks = egress_audit.recent_blocks(limit=5)
    assert len(blocks) == 2
    assert blocks[0]["host"] == "127.0.0.1"
    assert blocks[1]["host"] == "169.254.169.254"


def test_webhook_subscription_api_rejects_ssrf():
    client = TestClient(app)
    
    # 1. Attempt to subscribe cloud metadata target
    res_meta = client.post("/v1/webhooks/subscribe", json={
        "target_url": "http://169.254.169.254/latest/meta-data/",
        "secret_token": "super_secret_token_123",
        "subscribed_events": ["ANOMALY_ALERT"],
        "min_severity": "HIGH",
    })
    assert res_meta.status_code == 422
    assert "restricted IP address" in res_meta.text

    # 2. Attempt to subscribe local network target
    res_local = client.post("/v1/webhooks/subscribe", json={
        "target_url": "http://127.0.0.1:8000/internal",
        "secret_token": "super_secret_token_123",
        "subscribed_events": ["ANOMALY_ALERT"],
        "min_severity": "HIGH",
    })
    assert res_local.status_code == 422
    assert "restricted IP address" in res_local.text

    # 3. Valid target passes validation
    res_valid = client.post("/v1/webhooks/subscribe", json={
        "target_url": "https://example.com/valid-hook",
        "secret_token": "super_secret_token_123",
        "subscribed_events": ["ANOMALY_ALERT"],
        "min_severity": "HIGH",
    })
    assert res_valid.status_code == 201
    sub_id = res_valid.json()["subscription_id"]

    # Cleanup
    client.delete(f"/v1/webhooks/{sub_id}")
