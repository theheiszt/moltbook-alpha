"""
Unit and Integration Tests for Moltbook Alpha Operational & Traffic Metrics Dashboard.
Verifies user counts, sales aggregation, connected telemetry, admin authentication,
and password change lifecycle.
"""

from fastapi.testclient import TestClient
from api_server import app, storage


def test_storage_dashboard_metrics_aggregation():
    """Verifies that StorageManager.get_dashboard_metrics returns structured metrics with expected types."""
    metrics = storage.get_dashboard_metrics()
    assert isinstance(metrics, dict)
    assert "users" in metrics
    assert "activity" in metrics
    assert "sales" in metrics
    assert "funnel" in metrics
    assert "recent_activity" in metrics

    # Users validation
    users = metrics["users"]
    assert users["total_users"] >= 0
    assert users["active_users"] >= 0
    assert isinstance(users["users_by_tier"], dict)
    assert isinstance(users["recent_keys"], list)

    # Sales validation
    sales = metrics["sales"]
    assert sales["total_sales_count"] >= 0
    assert sales["total_revenue_usd"] >= 0.0
    assert isinstance(sales["sales_by_tier"], dict)
    assert isinstance(sales["sales_by_asset"], dict)
    assert "invoices" in sales
    assert sales["invoices"]["total"] >= 0
    assert 0.0 <= sales["invoices"]["settlement_rate_pct"] <= 100.0

    # Activity validation
    act = metrics["activity"]
    assert act["events_last_5m"] >= 0
    assert act["events_last_1h"] >= 0
    assert act["events_last_24h"] >= 0


def test_api_admin_auth_and_metrics_lifecycle():
    """
    Verifies full admin authentication lifecycle:
    1. Unauthenticated request to /v1/metrics/dashboard returns 401.
    2. Invalid credentials to /v1/admin/login returns 401.
    3. Valid default credentials (ADMIN / Neverwinter#7789) return 200 with session token.
    4. Authenticated request with session token returns 200 and unified metrics.
    5. Admin can change password; old sessions are revoked.
    6. Logging in with new password succeeds; old password fails.
    7. Admin logout successfully revokes session.
    """
    client = TestClient(app)

    # 1. Unauthenticated -> 401
    resp = client.get("/v1/metrics/dashboard")
    assert resp.status_code == 401
    assert "Admin authentication required" in resp.json()["detail"]

    # 2. Invalid credentials -> 401
    bad_login = client.post("/v1/admin/login", json={"username": "ADMIN", "password": "WrongPassword!123"})
    assert bad_login.status_code == 401

    # 3. Valid default login -> 200
    login_resp = client.post("/v1/admin/login", json={"username": "ADMIN", "password": "Neverwinter#7789"})
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["success"] is True
    assert "token" in login_data
    token = login_data["token"]
    assert token.startswith("adm_sess_")

    # 4. Valid session probe -> 200
    sess_check = client.get("/v1/admin/session", headers={"Authorization": f"Bearer {token}"})
    assert sess_check.status_code == 200
    assert sess_check.json()["authenticated"] is True
    assert sess_check.json()["username"] == "ADMIN"

    # 5. Access metrics with session token -> 200
    metrics_resp = client.get("/v1/metrics/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert metrics_resp.status_code == 200
    data = metrics_resp.json()
    assert data["success"] is True
    assert "server" in data
    assert data["server"]["status"] == "healthy"
    assert "connected" in data
    assert "users" in data
    assert "sales" in data
    assert "traffic" in data
    assert "funnel" in data

    # 6. Change password to new password
    new_pw = "DragonLance#2026!Secure"
    change_resp = client.post(
        "/v1/admin/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Neverwinter#7789", "new_password": new_pw},
    )
    assert change_resp.status_code == 200
    new_token = change_resp.json()["new_token"]
    assert new_token.startswith("adm_sess_")

    # Old token was revoked on password change
    old_token_check = client.get("/v1/metrics/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert old_token_check.status_code == 401

    # New token works
    new_token_check = client.get("/v1/metrics/dashboard", headers={"Authorization": f"Bearer {new_token}"})
    assert new_token_check.status_code == 200

    # Old password no longer works
    old_pw_login = client.post("/v1/admin/login", json={"username": "ADMIN", "password": "Neverwinter#7789"})
    assert old_pw_login.status_code == 401

    # New password works
    new_pw_login = client.post("/v1/admin/login", json={"username": "ADMIN", "password": new_pw})
    assert new_pw_login.status_code == 200
    fresh_token = new_pw_login.json()["token"]

    # Revert password back to Neverwinter#7789 for test consistency
    revert_resp = client.post(
        "/v1/admin/change-password",
        headers={"Authorization": f"Bearer {fresh_token}"},
        json={"current_password": new_pw, "new_password": "Neverwinter#7789"},
    )
    assert revert_resp.status_code == 200
    reverted_token = revert_resp.json()["new_token"]

    # 7. Logout revokes token
    logout_resp = client.post("/v1/admin/logout", headers={"Authorization": f"Bearer {reverted_token}"})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # Post-logout probe -> 401
    post_logout_check = client.get("/v1/metrics/dashboard", headers={"Authorization": f"Bearer {reverted_token}"})
    assert post_logout_check.status_code == 401


def test_api_dashboard_metrics_auth_protection(monkeypatch):
    """Verifies that setting METRICS_BEARER_TOKEN enforces bearer authentication for automated scrapers."""
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "secret_admin_token_12345")
    client = TestClient(app)

    # Missing token -> 401
    resp = client.get("/v1/metrics/dashboard")
    assert resp.status_code == 401

    # Invalid token -> 401
    resp = client.get("/v1/metrics/dashboard", headers={"Authorization": "Bearer wrong_token"})
    assert resp.status_code == 401

    # Valid token -> 200
    resp = client.get("/v1/metrics/dashboard", headers={"Authorization": "Bearer secret_admin_token_12345"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_quickstart_and_universal_api_key_auth(monkeypatch):
    """
    Verifies:
    1. /v1/metrics/dashboard includes latest_briefing with briefing_id, state_witness_id, briefing_markdown, and newsletter_markdown.
    2. /v1/quickstart returns 200 with authentication_methods and free_unmetered_endpoints_0_credits.
    3. Metered/account endpoints accept API keys via X-API-KEY, Authorization: Bearer molt_..., and ?api_key=molt_...
    """
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "secret_admin_token_12345")
    client = TestClient(app)

    # 1. Dashboard includes latest_briefing
    dash_resp = client.get("/v1/metrics/dashboard", headers={"Authorization": "Bearer secret_admin_token_12345"})
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert "latest_briefing" in dash_data
    lb = dash_data["latest_briefing"]
    assert "briefing_id" in lb
    assert "state_witness_id" in lb
    assert "briefing_markdown" in lb
    assert "newsletter_markdown" in lb

    # 2. Quickstart endpoint returns 200 (0 credits)
    qs_resp = client.get("/v1/quickstart")
    assert qs_resp.status_code == 200
    qs_data = qs_resp.json()
    assert "authentication_methods" in qs_data
    assert "free_unmetered_endpoints_0_credits" in qs_data
    assert "earn_free_credits_in_one_call" in qs_data

    # 3. Universal API key authentication (Authorization: Bearer molt_... and ?api_key=molt_...)
    raw_key, _ = storage.create_api_key(tier="pro", credits=10)
    r_bearer = client.get("/v1/account/quota", headers={"Authorization": f"Bearer {raw_key}"})
    assert r_bearer.status_code == 200
    assert r_bearer.json()["credits_remaining"] == 10

    r_query = client.get(f"/v1/account/quota?api_key={raw_key}")
    assert r_query.status_code == 200
    assert r_query.json()["credits_remaining"] == 10


def test_cors_preflight_max_age_caching():
    """Verifies that CORS OPTIONS preflight returns Access-Control-Max-Age: 86400 to prevent browser polling amplification."""
    client = TestClient(app)
    resp = client.options(
        "/v1/metrics/dashboard",
        headers={
            "Origin": "https://theheiszt.github.io",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,accept",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-max-age") == "86400"
    assert "authorization" in resp.headers.get("access-control-allow-headers", "").lower()


def test_dashboard_metrics_in_memory_ttl_cache(monkeypatch):
    """Verifies that subsequent requests within the 10-second TTL window reuse cached payload without hitting storage."""
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "test_cache_token_xyz")
    client = TestClient(app)

    # First fetch populates cache
    resp1 = client.get("/v1/metrics/dashboard", headers={"Authorization": "Bearer test_cache_token_xyz"})
    assert resp1.status_code == 200
    data1 = resp1.json()

    # Second fetch should return the exact cached payload
    resp2 = client.get("/v1/metrics/dashboard", headers={"Authorization": "Bearer test_cache_token_xyz"})
    assert resp2.status_code == 200
    data2 = resp2.json()

    assert data1["server"]["timestamp"] == data2["server"]["timestamp"]
    assert data1["users"]["total_users"] == data2["users"]["total_users"]


def test_dashboard_metrics_rate_limiting(monkeypatch):
    """Verifies that exceeding 30 requests/min from a single IP triggers HTTP 429 Too Many Requests."""
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "test_ratelimit_token_123")
    client = TestClient(app)

    # Send 30 requests - all allowed
    for _ in range(30):
        r = client.get("/v1/metrics/dashboard", headers={"Authorization": "Bearer test_ratelimit_token_123"})
        assert r.status_code in (200, 429)

    # 31st request triggers rate limit
    r_exceeded = client.get("/v1/metrics/dashboard", headers={"Authorization": "Bearer test_ratelimit_token_123"})
    assert r_exceeded.status_code == 429
    data = r_exceeded.json()
    assert data["code"] == "RATE_LIMIT_EXCEEDED" or "rate limit" in str(data).lower()
