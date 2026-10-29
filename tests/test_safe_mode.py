"""
Tests for Moltbook Alpha Read-Only Safe Mode (ops/security/safe_mode.py) and API integration.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from api_server import app, storage
from ops.security.safe_mode import (
    SafeModeController,
    disable_safe_mode,
    enable_safe_mode,
    get_safe_mode_status,
    is_safe_mode_active,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def ensure_safe_mode_off():
    # Make sure safe mode is disabled before and after each test
    disable_safe_mode(operator="test_setup")
    yield
    disable_safe_mode(operator="test_teardown")


def test_safe_mode_controller_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "safe_mode.json"
        sm = SafeModeController(state_file=state_file)

        assert sm.is_active() is False
        status = sm.get_status()
        assert status["active"] is False

        # Enable safe mode
        status = sm.enable(reason="Database schema migration", operator="ops_lead")
        assert status["active"] is True
        assert status["reason"] == "Database schema migration"
        assert status["operator"] == "ops_lead"
        assert status["enabled_at"] is not None
        assert sm.is_active() is True
        assert state_file.exists()

        # Reload from disk in a fresh instance
        sm_reloaded = SafeModeController(state_file=state_file)
        assert sm_reloaded.is_active() is True
        assert sm_reloaded.get_status()["reason"] == "Database schema migration"

        # Check path filtering
        assert sm_reloaded.is_mutation_allowed("GET", "/v1/quant/dex-microstructure") is True
        assert sm_reloaded.is_mutation_allowed("HEAD", "/v1/health") is True
        assert sm_reloaded.is_mutation_allowed("POST", "/v1/admin/login") is True
        assert sm_reloaded.is_mutation_allowed("POST", "/v1/admin/safemode") is True
        assert sm_reloaded.is_mutation_allowed("POST", "/v1/payments/invoice") is False
        assert sm_reloaded.is_mutation_allowed("DELETE", "/v1/webhooks/sub_123") is False

        # Disable safe mode
        status = sm.disable(operator="ops_lead")
        assert status["active"] is False
        assert sm.is_active() is False

        # Check path filtering when inactive
        assert sm.is_mutation_allowed("POST", "/v1/payments/invoice") is True


def test_safe_mode_read_requests_allowed_in_api(client):
    enable_safe_mode(reason="Hotfix maintenance", operator="admin")
    try:
        # GET endpoints must succeed
        res = client.get("/v1/health")
        assert res.status_code == 200

        res_card = client.get("/.well-known/agent-card.json")
        assert res_card.status_code == 200

        res_cap = client.get("/v1/capabilities")
        assert res_cap.status_code == 200
    finally:
        disable_safe_mode(operator="admin")


def test_safe_mode_blocks_mutations_with_503(client):
    enable_safe_mode(reason="Urgent security patch", operator="admin")
    try:
        # Mutating POST request should be blocked with 503
        res = client.post(
            "/v1/payments/invoice",
            json={"target_tier": "tier_starter", "rail": "solana", "asset": "USDC"},
        )
        assert res.status_code == 503
        data = res.json()
        assert "error" in data
        err = data["error"]
        assert err["code"] == "SERVICE_READ_ONLY_MODE"
        assert "Read-Only Safe Mode: Urgent security patch" in err["message"]
        assert err["retryable"] is True
        assert err["details"]["active"] is True
        assert err["details"]["reason"] == "Urgent security patch"
        assert res.headers.get("Retry-After") == "60"
        assert "X-Request-ID" in res.headers
    finally:
        disable_safe_mode(operator="admin")


def test_admin_safemode_endpoints(client):
    # Unauthenticated attempts must fail
    res_unauth = client.get("/v1/admin/safemode")
    assert res_unauth.status_code == 401

    res_post_unauth = client.post("/v1/admin/safemode", json={"active": True})
    assert res_post_unauth.status_code == 401

    # Create admin session
    admin_user = "SYSADMIN"
    session_token = storage.create_admin_session(admin_user, duration_hours=1)
    auth_headers = {"Authorization": f"Bearer {session_token}"}

    try:
        # Get status
        res = client.get("/v1/admin/safemode", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["safe_mode"]["active"] is False

        # Toggle Safe Mode ON
        res_enable = client.post(
            "/v1/admin/safemode",
            headers=auth_headers,
            json={"active": True, "reason": "Scheduled node upgrade"},
        )
        assert res_enable.status_code == 200
        assert res_enable.json()["safe_mode"]["active"] is True
        assert is_safe_mode_active() is True
        assert get_safe_mode_status()["reason"] == "Scheduled node upgrade"

        # Toggle Safe Mode OFF
        res_disable = client.post(
            "/v1/admin/safemode",
            headers=auth_headers,
            json={"active": False},
        )
        assert res_disable.status_code == 200
        assert res_disable.json()["safe_mode"]["active"] is False
        assert is_safe_mode_active() is False
    finally:
        storage.revoke_admin_session(session_token)
        disable_safe_mode(operator="admin")
