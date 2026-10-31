"""
Tests for Core and Metered Route Response Models and Schema Conformance.
"""

import pytest
from fastapi.testclient import TestClient
from api_server import app, storage


@pytest.fixture
def auth_key():
    raw_key, _ = storage.create_api_key(tier="tier_pro", credits=100)
    return raw_key


def test_openapi_response_models_registered():
    openapi = app.openapi()
    paths = openapi["paths"]
    schemas = openapi["components"]["schemas"]

    required_endpoints = [
        ("/v1/intel/signals", "get", "IntelSignalsResponse"),
        ("/v1/intel/opportunities", "get", "IntelOpportunitiesResponse"),
        ("/v1/intel/signals/trading", "get", "IntelTradingSignalsResponse"),
        ("/v1/intel/microstructure", "get", "IntelMicrostructureOverviewResponse"),
        ("/v1/intel/microstructure/{pool_id}", "get", "IntelPoolMicrostructureResponse"),
        ("/v1/briefing/latest", "get", "BriefingLatestResponse"),
        ("/v1/data-products/{product_id}/latest", "get", "DataProductLatestResponse"),
        ("/v1/account/quota", "get", "AccountQuotaUsageResponse"),
        ("/v1/account/usage", "get", "AccountQuotaUsageResponse"),
        ("/v1/quant/first-passage", "get", "QuantFirstPassageResponse"),
        ("/v1/quant/trade-viability", "post", "QuantTradeViabilityResponse"),
    ]

    for path, method, schema_name in required_endpoints:
        assert path in paths, f"Path {path} missing from OpenAPI paths"
        route_def = paths[path][method]
        resp_schema = route_def["responses"]["200"]["content"]["application/json"]["schema"]
        expected_ref = f"#/components/schemas/{schema_name}"
        assert resp_schema.get("$ref") == expected_ref, (
            f"Expected {path} {method} to reference {expected_ref}, got {resp_schema}"
        )
        assert schema_name in schemas, f"Schema {schema_name} not defined in OpenAPI components"


def test_intel_signals_response_keys(auth_key):
    client = TestClient(app)
    resp = client.get("/v1/intel/signals", headers={"X-API-KEY": auth_key})
    assert resp.status_code == 200
    data = resp.json()
    for key in ["count", "signals"]:
        assert key in data


def test_intel_opportunities_response_keys(auth_key):
    client = TestClient(app)
    resp = client.get("/v1/intel/opportunities", headers={"X-API-KEY": auth_key})
    assert resp.status_code == 200
    data = resp.json()
    for key in ["count", "min_profit_pct", "opportunities", "timestamp_utc"]:
        assert key in data


def test_intel_trading_signals_response_keys(auth_key):
    client = TestClient(app)
    resp = client.get("/v1/intel/signals/trading", headers={"X-API-KEY": auth_key})
    assert resp.status_code == 200
    data = resp.json()
    for key in ["count", "min_confidence", "trading_signals", "timestamp_utc"]:
        assert key in data


def test_intel_microstructure_response_keys(auth_key):
    client = TestClient(app)
    resp = client.get("/v1/intel/microstructure", headers={"X-API-KEY": auth_key})
    assert resp.status_code == 200
    data = resp.json()
    for key in [
        "status",
        "tracked_pool_count",
        "active_anomaly_count",
        "depth_bps",
        "pools",
        "recent_anomalies",
        "state_witness_id",
        "timestamp_utc",
    ]:
        assert key in data


def test_intel_pool_microstructure_response_keys(auth_key):
    client = TestClient(app)
    resp = client.get("/v1/intel/microstructure/Raydium_SOL_USDC", headers={"X-API-KEY": auth_key})
    assert resp.status_code == 200
    data = resp.json()
    for key in [
        "pool_id",
        "protocol",
        "pair",
        "current_tick",
        "current_price",
        "bid_depth_usd",
        "ask_depth_usd",
        "imbalance_ratio",
        "active_bin_count",
        "timestamp_utc",
        "raw_bins",
        "anomalies",
        "state_witness",
    ]:
        assert key in data


def test_briefing_latest_response_keys(auth_key):
    client = TestClient(app)
    resp = client.get("/v1/briefing/latest", headers={"X-API-KEY": auth_key})
    assert resp.status_code == 200
    data = resp.json()
    for key in [
        "success",
        "user_tier",
        "credits_remaining",
        "briefing_markdown",
        "trading_signals",
        "opportunities",
        "state_witness_id",
    ]:
        assert key in data


def test_data_product_latest_response_keys(auth_key):
    client = TestClient(app)
    resp = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest",
        headers={"X-API-KEY": auth_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    for key in [
        "product_id",
        "snapshot_id",
        "generated_at",
        "retrieval_outcome",
        "freshness_seconds",
        "source_attribution",
        "state_witness_id",
        "usage_receipt",
        "evidence_summary",
        "evidence_items",
    ]:
        assert key in data


def test_account_quota_and_usage_response_keys(auth_key):
    client = TestClient(app)
    for path in ["/v1/account/quota", "/v1/account/usage"]:
        resp = client.get(path, headers={"X-API-KEY": auth_key})
        assert resp.status_code == 200
        data = resp.json()
        for key in [
            "success",
            "key_prefix",
            "tier",
            "credits_remaining",
            "is_active",
            "created_at",
            "low_credit_warning",
            "entitlement",
            "credit_lots",
            "usage",
            "rate_limit_state",
        ]:
            assert key in data


def test_quant_first_passage_response_keys(auth_key):
    client = TestClient(app)
    resp = client.get(
        "/v1/quant/first-passage?pair=BONK/SOL&target_return=0.015",
        headers={"X-API-KEY": auth_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    for key in [
        "pair",
        "target_net_pct",
        "roundtrip_spread_bps",
        "required_gross_move_pct",
        "volatility_metrics",
        "two_barrier_analysis",
        "horizon_probabilities",
        "optimal_target_ladder",
        "recommended_target_net_pct",
        "state_witness_id",
        "witness_signature",
        "generated_at",
    ]:
        assert key in data


def test_quant_trade_viability_response_keys(auth_key):
    client = TestClient(app)
    payload = {
        "pair": "BONK/SOL",
        "target_net_pct": 0.02,
        "holding_time_minutes": 15,
        "simulations": 1000,
    }
    resp = client.post(
        "/v1/quant/trade-viability",
        json=payload,
        headers={"X-API-KEY": auth_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    for key in [
        "pair",
        "target_net_pct",
        "roundtrip_spread_bps",
        "required_gross_move_pct",
        "volatility_metrics",
        "two_barrier_analysis",
        "horizon_probabilities",
        "optimal_target_ladder",
        "recommended_target_net_pct",
        "state_witness_id",
        "witness_signature",
        "generated_at",
    ]:
        assert key in data
