"""Baseline API smoke tests. Security-specific tests are added with each hardening stage."""

from fastapi.testclient import TestClient

from api_server import app


def test_health_endpoint_reports_service_status():
    client = TestClient(app)
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "moltbook-alpha-api"}
