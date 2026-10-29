"""
Tests for Google Agent-to-Agent (A2A) Protocol Discovery (/.well-known/agent-card.json).
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from api_server import app
from capabilities import get_api_capabilities


@pytest.fixture
def client():
    return TestClient(app)


def test_agent_card_endpoint_schema(client):
    response = client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    data = response.json()

    assert data["protocol_version"] == "0.1.0"
    assert data["name"] == "Moltbook Alpha Verifiable Intelligence Agent"
    assert "description" in data
    assert "url" in data
    assert data["version"] == "1.2.0"
    assert data["provider"]["organization"] == "Moltbook Alpha"

    # Verify capabilities
    caps = data["capabilities"]
    assert caps["streaming"] is True
    assert caps["push_notifications"] is True
    assert caps["state_witness"] is True
    assert caps["step_up_authorization"] is True
    assert caps["safe_mode"] is True

    # Verify skills
    skill_ids = [s["id"] for s in data["skills"]]
    assert "market_microstructure" in skill_ids
    assert "cryptographic_state_witness" in skill_ids
    assert "verifiable_intelligence" in skill_ids
    assert "data_product_exchange" in skill_ids
    assert "webhook_streaming" in skill_ids

    # Verify authentication schemes
    schemes = data["authentication"]["schemes"]
    scheme_types = [s["type"] for s in schemes]
    assert "apiKey" in scheme_types
    assert "http" in scheme_types
    assert "nonce_step_up" in scheme_types


def test_capabilities_manifest_links_agent_card(client):
    manifest = get_api_capabilities()
    assert manifest["agent_card_url"] == "/.well-known/agent-card.json"
    assert "/.well-known/agent-card.json" in manifest["pricing_and_quotas"]["unmetered_endpoints"]
