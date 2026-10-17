"""
Tests for Account Quota Inspection, Bearer Token Authentication, and Subsystem Diagnostics.
"""

from pathlib import Path
from fastapi.testclient import TestClient
from api_server import app, storage


def test_quota_endpoint_requires_auth():
    client = TestClient(app)
    response = client.get("/v1/account/quota")
    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["error"] == "Authentication Required"
    assert "remedy" in data["detail"]
    assert data["detail"]["remedy"]["action"] == "obtain_key"
    assert "WWW-Authenticate" in response.headers


def test_quota_endpoint_rejects_invalid_key():
    client = TestClient(app)
    response = client.get("/v1/account/quota", headers={"X-API-KEY": "molt_invalid_fake_key_12345"})
    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["error"] == "Invalid API Key"


def test_quota_endpoint_rejects_revoked_key():
    client = TestClient(app)
    raw_key, record = storage.create_api_key(tier="starter", credits=50, prefix_tag="molt_quota_rev")
    storage.revoke_key(record["key_prefix"])

    response = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["error"] == "API Key Revoked"


def test_quota_endpoint_returns_balance_without_deducting():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_pro", credits=300, prefix_tag="molt_pro_quota")

    # Call quota inspection 3 times
    for _ in range(3):
        resp = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["tier"] == "tier_pro"
        assert data["credits_remaining"] == 300
        assert data["is_active"] is True
        assert data["low_credit_warning"] is False

    # Verify storage balance was not decremented
    key_info = storage.get_key_info(raw_key)
    assert key_info["credits"] == 300


def test_quota_endpoint_supports_bearer_token():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=50, prefix_tag="molt_bearer")

    resp = client.get("/v1/account/quota", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["credits_remaining"] == 50


def test_quota_endpoint_low_credit_remedy():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=3, prefix_tag="molt_low")

    resp = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
    assert resp.status_code == 200
    data = resp.json()
    assert data["low_credit_warning"] is True
    assert "remedy" in data
    assert data["remedy"]["action"] == "top_up"
    assert "treasury_wallet" in data["remedy"]
    assert "pricing_tiers" in data["remedy"]


def test_briefing_supports_bearer_token(tmp_path: Path):
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=10, prefix_tag="molt_bearer_brief")

    resp = client.get("/v1/briefing/latest", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code in (200, 404)
    # Credit was deducted via Bearer auth
    key_info = storage.get_key_info(raw_key)
    assert key_info["credits"] == 9


def test_health_endpoint_subsystems_diagnostics():
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "moltbook-alpha-api"
    assert data["database"] == "healthy"
    assert "subsystems" in data
    assert data["subsystems"]["database"]["status"] == "ok"
    assert data["subsystems"]["database"]["journal_mode"] == "WAL"
    assert data["subsystems"]["payments"]["status"] == "ok"
    assert "DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC" in data["subsystems"]["payments"]["treasury_wallet"]
    assert data["subsystems"]["rpc_pool"]["cluster"] == "mainnet-beta"
    assert data["subsystems"]["rpc_pool"]["endpoints_configured"] >= 1
