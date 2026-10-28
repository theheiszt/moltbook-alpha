"""
Unit and Integration Tests for Moltbook Alpha Operational & Traffic Metrics Dashboard.
Verifies user counts, sales aggregation, connected telemetry, and funnel tracking.
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


def test_api_dashboard_metrics_endpoint():
    """Verifies GET /v1/metrics/dashboard returns 200 with unified server, connected, users, and sales data."""
    client = TestClient(app)
    resp = client.get("/v1/metrics/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is True
    assert "server" in data
    assert data["server"]["status"] == "healthy"
    assert data["server"]["version"] == "1.2.0"
    assert data["server"]["uptime_seconds"] >= 0

    assert "connected" in data
    assert data["connected"]["active_websockets"] >= 0
    assert data["connected"]["in_flight_requests"] >= 0

    assert "users" in data
    assert data["users"]["total_users"] >= 0

    assert "sales" in data
    assert data["sales"]["total_sales_count"] >= 0
    assert data["sales"]["total_revenue_usd"] >= 0.0

    assert "traffic" in data
    assert isinstance(data["traffic"]["status_codes"], dict)
    assert isinstance(data["traffic"]["top_endpoints"], list)

    assert "funnel" in data
    assert isinstance(data["recent_activity"], list)


def test_api_dashboard_metrics_auth_protection(monkeypatch):
    """Verifies that setting METRICS_BEARER_TOKEN enforces bearer authentication."""
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
