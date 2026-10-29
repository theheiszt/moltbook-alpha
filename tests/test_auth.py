"""
Tests for API authentication, key validation, credit deduction, and demo gating.
"""

import pytest
from fastapi.testclient import TestClient
from config import REPORTS_DIR
from api_server import app, storage


@pytest.fixture(autouse=True)
def setup_test_briefing():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    briefing_file = REPORTS_DIR / "latest_briefing.md"
    existed = briefing_file.exists()
    if not existed:
        briefing_file.write_text("# Test Briefing\nSynthetic briefing for auth tests.", encoding="utf-8")
    yield
    if not existed and briefing_file.exists():
        try:
            briefing_file.unlink()
        except OSError:
            pass


def test_missing_api_key_returns_402_with_payment_instructions():
    client = TestClient(app)
    response = client.get("/v1/briefing/latest")
    assert response.status_code == 402
    data = response.json()
    assert "detail" in data
    assert data["detail"]["error"] == "Payment Required"
    assert "purchase_instructions" in data["detail"]
    assert "treasury_wallet" in data["detail"]["purchase_instructions"]


def test_invalid_api_key_returns_403():
    client = TestClient(app)
    response = client.get("/v1/briefing/latest", headers={"x-api-key": "molt_fake_invalid_token_123"})
    assert response.status_code == 403
    assert "Invalid API key" in response.json()["detail"]


def test_backdoor_master_admin_token_is_rejected():
    client = TestClient(app)
    response = client.get("/v1/briefing/latest", headers={"x-api-key": "master_admin_token"})
    assert response.status_code == 403


def test_valid_key_deducts_credits_and_exhausts():
    raw_key, _ = storage.create_api_key(tier="test_tier", credits=2, prefix_tag="molt_test")
    client = TestClient(app)

    # First request: 2 -> 1
    resp1 = client.get("/v1/briefing/latest", headers={"x-api-key": raw_key})
    assert resp1.status_code in (200, 404)  # 404 if no briefing generated, but auth passed
    key_info = storage.get_key_info(raw_key)
    assert key_info["credits"] == 1

    # Second request: 1 -> 0
    resp2 = client.get("/v1/briefing/latest", headers={"x-api-key": raw_key})
    assert resp2.status_code in (200, 404)
    key_info = storage.get_key_info(raw_key)
    assert key_info["credits"] == 0

    # Third request: exhausted -> 402 Payment Required
    resp3 = client.get("/v1/briefing/latest", headers={"x-api-key": raw_key})
    assert resp3.status_code == 402
    assert "credits exhausted" in resp3.json()["detail"]


def test_unlimited_tier_deducts_from_10k_allowance():
    raw_key, _ = storage.create_api_key(tier="unlimited", credits=10000, prefix_tag="molt_unlimited")
    client = TestClient(app)
    client.get("/v1/briefing/latest", headers={"x-api-key": raw_key})
    key_info = storage.get_key_info(raw_key)
    assert key_info["credits"] == 9999
    assert key_info["tier"] == "premium"


def test_admin_tier_does_not_deduct():
    raw_key, _ = storage.create_api_key(tier="admin", credits=999999, prefix_tag="molt_admin")
    client = TestClient(app)
    client.get("/v1/briefing/latest", headers={"x-api-key": raw_key})
    key_info = storage.get_key_info(raw_key)
    assert key_info["credits"] == 999999


def test_demo_key_generation_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_DEMO_KEYS", raising=False)
    client = TestClient(app)
    response = client.post("/v1/keys/generate-demo")
    assert response.status_code == 403
    assert "Demo key issuance is disabled" in response.json()["detail"]


def test_demo_key_generation_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_DEMO_KEYS", "true")
    client = TestClient(app)
    response = client.post("/v1/keys/generate-demo")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["credits"] == 5
    assert data["api_key"].startswith("molt_demo_")

    # Verify minted key is stored in DB and usable
    key_info = storage.get_key_info(data["api_key"])
    assert key_info is not None
    assert key_info["credits"] == 5
    assert key_info["tier"] == "trial"
