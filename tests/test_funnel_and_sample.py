"""
Tests for Stage 3 (Developer Onboarding & Sample Briefing) and Stage 4 (Funnel Analytics & Conversion Metrics).
"""
import pytest
from fastapi.testclient import TestClient
from api_server import app, storage


@pytest.fixture
def client():
    return TestClient(app)


def test_intel_sample_endpoint_unmetered(client):
    """
    Verifies GET /v1/intel/sample returns HTTP 200 without API key or payment,
    serves valid briefing schema, and emits sample_viewed funnel event.
    """
    initial_metrics = storage.get_funnel_metrics()
    initial_views = initial_metrics.get("sample_viewed", 0)

    response = client.get("/v1/intel/sample")
    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["sample"] is True
    assert data["mode"] == "evaluation_unmetered"
    assert "briefing_markdown" in data
    assert len(data["signals"]) >= 1
    assert "microstructure_summary" in data
    assert "state_witness" in data
    assert data["state_witness"]["action"] == "SAMPLE_EVALUATION"
    assert data["credits_remaining"] == "unmetered"

    # Verify sample_viewed event recorded
    updated_metrics = storage.get_funnel_metrics()
    assert updated_metrics["sample_viewed"] >= initial_views + 1


def test_funnel_privacy_sanitization():
    """
    Verifies that funnel events enforce strict privacy rules:
    - Redacts raw API keys and secrets
    - Redacts IP addresses
    - Truncates wallet addresses to 4...4 format
    - Truncates hashes
    """
    event_id = storage.record_funnel_event(
        "test_privacy_event",
        {
            "api_key": "molt_sol_secretkey1234567890",
            "claim_secret": "sec_verysecretvalue987654321",
            "client_ip": "192.168.1.100",
            "payer_wallet": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            "key_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "tier": "tier_starter",
            "credits": 50,
        },
    )
    assert event_id.startswith("fnl_")

    events = storage.get_funnel_events(limit=5, event_name="test_privacy_event")
    assert len(events) >= 1
    ev = next(e for e in events if e["event_id"] == event_id)
    props = ev["properties"]

    # Redactions
    assert "api_key" not in props
    assert "claim_secret" not in props
    assert "client_ip" not in props

    # Truncation
    assert props["payer_wallet"] == "7xKX...gAsU"
    assert props["key_hash"].startswith("a1b2c3d4...")
    assert props["tier"] == "tier_starter"
    assert props["credits"] == 50


def test_funnel_lifecycle_progression(client):
    """
    Verifies end-to-end progression through the conversion funnel:
    invoice_created -> payment_verified -> key_delivered -> first_query.
    """
    # 1. Create Invoice
    inv_res = client.post(
        "/v1/payments/invoice",
        json={"target_tier": "tier_starter", "asset": "USDC"},
    )
    assert inv_res.status_code == 200
    inv_data = inv_res.json()
    invoice_id = inv_data["invoice_id"]
    claim_secret = inv_data["claim_secret"]

    metrics = storage.get_funnel_metrics()
    assert metrics["invoice_created"] >= 1

    # 2. Simulate payment fulfillment in storage
    redeem_res = storage.fulfill_invoice_and_redeem(
        invoice_id=invoice_id,
        tx_signature=f"tx_test_{invoice_id}",
        asset="USDC",
        amount_raw=1_000_000,
        tier="tier_starter",
        credits_to_grant=50,
        claim_secret=claim_secret,
        payer="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    )
    assert redeem_res["status"] == "newly_minted"
    api_key = redeem_res["api_key"]

    metrics = storage.get_funnel_metrics()
    assert metrics["payment_verified"] >= 1
    assert metrics["key_delivered"] >= 1

    # 3. First paid query deduction
    res_info, state = storage.reserve_quota(api_key, request_id="req_funnel_test_1")
    assert state == "ok"
    assert res_info["credits"] == 49

    metrics = storage.get_funnel_metrics()
    assert metrics["first_query"] >= 1


def test_metrics_funnel_endpoint(client):
    """
    Verifies GET /v1/metrics/funnel exposes aggregate counts and recent events.
    """
    res = client.get("/v1/metrics/funnel")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "funnel_metrics" in data
    assert "recent_events" in data
    assert isinstance(data["funnel_metrics"]["sample_viewed"], int)
    assert isinstance(data["funnel_metrics"]["invoice_created"], int)


def test_openapi_json_schema(client):
    """
    Verifies that FastAPI serves valid OpenAPI 3.x schema containing our new endpoints.
    """
    res = client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert schema["openapi"].startswith("3.")
    assert "/v1/intel/sample" in schema["paths"]
    assert "/v1/metrics/funnel" in schema["paths"]
    assert "/v1/payments/invoice" in schema["paths"]
