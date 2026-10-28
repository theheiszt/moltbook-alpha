"""API health and database connectivity tests."""

from fastapi.testclient import TestClient
from unittest.mock import patch
from api_server import app


def test_health_endpoint_reports_service_status():
    client = TestClient(app)
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "moltbook-alpha-api"
    assert data["database"] == "healthy"


def test_health_endpoint_fails_closed_when_database_fails():
    client = TestClient(app)
    with patch("api_server.storage.check_health", side_effect=Exception("Database lock error")):
        response = client.get("/v1/health")
        assert response.status_code == 503
        assert "Database health check failed" in response.json()["detail"]
