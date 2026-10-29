"""
Tests for Agent Capability Discovery and Agent Data Exchange (v1).
Verifies:
- Machine-readable runtime capability discovery (GET /v1/capabilities)
- Data product catalog and JSON Schema contracts (GET /v1/data-products, GET /v1/data-products/{product_id})
- Authenticated snapshot retrieval with atomic 1-credit settlement (GET /v1/data-products/{product_id}/latest)
- Idempotency replay with zero duplicate charges
- Zero charges for unauthorized, exhausted, or failed requests
- Comprehensive account usage report (GET /v1/account/usage)
- Python SDK and MCP tool integration
"""

import time
import pytest
from fastapi.testclient import TestClient

from api_server import app, storage
from mcp.moltbook_mcp import MoltbookMCPServer
from capabilities import get_api_capabilities


@pytest.fixture
def auth_key():
    """Generates an active test API key with 10 credits in the live test storage."""
    raw_key, _ = storage.create_api_key(tier="tier_pro", credits=10)
    return raw_key


@pytest.fixture
def exhausted_key():
    """Generates an active test API key with 0 credits."""
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=0)
    return raw_key


def test_capabilities_manifest_structure():
    caps = get_api_capabilities()
    assert caps["service"] == "moltbook-alpha-api"
    assert caps["api_version"] == "1.2.0"
    assert "agent_data_exchange" in caps["capabilities"]
    assert "market_intelligence" in caps["capabilities"]
    assert "trading_alpha_and_arbitrage" in caps["capabilities"]
    assert "account_and_usage" in caps["capabilities"]
    assert "dag_tool_parameters" in caps["capabilities"]
    assert "cryptographic_witnesses" in caps["capabilities"]
    assert "payments_and_settlement" in caps["capabilities"]
    assert "rate_limits" in caps
    assert caps["pricing_and_quotas"]["default_snapshot_credit_cost"] == 1


def test_http_api_capabilities_endpoint():
    client = TestClient(app)
    res = client.get("/v1/capabilities")
    assert res.status_code == 200
    data = res.json()
    assert data["service"] == "moltbook-alpha-api"
    assert "agent_data_exchange" in data["capabilities"]
    endpoints = data["capabilities"]["agent_data_exchange"]["endpoints"]
    paths = [e["path"] for e in endpoints]
    assert "/v1/data-products" in paths
    assert "/v1/data-products/{product_id}" in paths
    assert "/v1/data-products/{product_id}/latest" in paths


def test_http_api_data_products_catalog():
    client = TestClient(app)
    res = client.get("/v1/data-products")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert data["count"] >= 3
    prods = {p["product_id"]: p for p in data["products"]}

    assert "moltbook-agent-intelligence-feed" in prods
    assert "solana-dex-arbitrage-opportunities" in prods
    assert "solana-quantitative-trading-signals" in prods

    feed = prods["moltbook-agent-intelligence-feed"]
    assert feed["cost_credits"] == 1
    assert feed["update_frequency"] == "hourly"
    assert "contract_endpoint" in feed
    assert "latest_snapshot_endpoint" in feed


def test_http_api_data_product_contract_and_404():
    client = TestClient(app)

    # Valid product contract
    res = client.get("/v1/data-products/moltbook-agent-intelligence-feed")
    assert res.status_code == 200
    contract = res.json()
    assert contract["product_id"] == "moltbook-agent-intelligence-feed"
    assert "output_schema" in contract
    assert contract["output_schema"]["type"] == "object"
    assert "required" in contract["output_schema"]
    assert "snapshot_id" in contract["output_schema"]["required"]
    assert "usage_receipt" in contract["output_schema"]["required"]

    # Unknown product returns 404
    res_404 = client.get("/v1/data-products/unknown-non-existent-product")
    assert res_404.status_code == 404
    assert "not found in exchange catalog" in res_404.json()["detail"]


def test_data_product_unauthenticated_rejected():
    client = TestClient(app)
    res = client.get("/v1/data-products/moltbook-agent-intelligence-feed/latest")
    assert res.status_code == 402
    data = res.json()
    assert data["detail"]["error"] == "Payment Required"
    assert "1 credit" in data["detail"]["price"]


def test_data_product_invalid_key_rejected():
    client = TestClient(app)
    res = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest",
        headers={"X-API-KEY": "molt_invalid_fake_key_999"},
    )
    assert res.status_code == 403


def test_data_product_exhausted_key_rejected(exhausted_key):
    client = TestClient(app)
    res = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest",
        headers={"X-API-KEY": exhausted_key},
    )
    assert res.status_code == 402
    assert "credits exhausted" in res.json()["detail"].lower()

    # Verify balance did not change
    info = storage.get_key_info(exhausted_key)
    assert info["credits"] == 0


def test_data_product_snapshot_success_and_atomic_deduction(auth_key):
    client = TestClient(app)

    # 1. Retrieve Moltbook Agent Intelligence Feed snapshot
    res = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest",
        headers={"X-API-KEY": auth_key},
    )
    assert res.status_code == 200
    snap = res.json()

    assert snap["product_id"] == "moltbook-agent-intelligence-feed"
    assert "snapshot_id" in snap
    assert "generated_at" in snap
    assert "content" in snap
    assert "executive_summary" in snap["content"]
    assert "signals" in snap
    assert "source_attribution" in snap
    assert snap["source_attribution"]["publisher"] == "Moltbook Alpha Curated Pipeline"

    # Verify usage receipt
    receipt = snap["usage_receipt"]
    assert receipt["product_id"] == "moltbook-agent-intelligence-feed"
    assert receipt["credits_deducted"] == 1
    assert receipt["credits_remaining"] == 9

    # 2. Retrieve Solana Arbitrage snapshot (deducts 1 more credit)
    res_arb = client.get(
        "/v1/data-products/solana-dex-arbitrage-opportunities/latest",
        headers={"X-API-KEY": auth_key},
    )
    assert res_arb.status_code == 200
    snap_arb = res_arb.json()
    assert snap_arb["product_id"] == "solana-dex-arbitrage-opportunities"
    assert "opportunities" in snap_arb
    assert snap_arb["usage_receipt"]["credits_remaining"] == 8

    # 3. Retrieve Solana Quantitative Signals snapshot (deducts 1 more credit)
    res_sig = client.get(
        "/v1/data-products/solana-quantitative-trading-signals/latest?asset=SOL",
        headers={"X-API-KEY": auth_key},
    )
    assert res_sig.status_code == 200
    snap_sig = res_sig.json()
    assert snap_sig["product_id"] == "solana-quantitative-trading-signals"
    assert "trading_signals" in snap_sig
    assert snap_sig["usage_receipt"]["credits_remaining"] == 7

    # Verify storage balance directly
    key_info = storage.get_key_info(auth_key)
    assert key_info["credits"] == 7


def test_data_product_idempotency_replay_zero_duplicate_charge(auth_key):
    client = TestClient(app)
    idemp_key = f"idemp_test_data_{int(time.time())}"

    # First request: burns 1 credit (10 -> 9)
    res1 = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest",
        headers={"X-API-KEY": auth_key, "Idempotency-Key": idemp_key},
    )
    assert res1.status_code == 200
    snap1 = res1.json()
    assert snap1["usage_receipt"]["credits_remaining"] == 9

    # Second request with same idempotency key: replayed without additional charge
    res2 = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest",
        headers={"X-API-KEY": auth_key, "Idempotency-Key": idemp_key},
    )
    assert res2.status_code == 200
    snap2 = res2.json()

    assert snap1["snapshot_id"] == snap2["snapshot_id"]
    assert snap2["usage_receipt"]["credits_remaining"] == 9

    # Verify storage balance remained at 9 (no double deduction)
    key_info = storage.get_key_info(auth_key)
    assert key_info["credits"] == 9


def test_http_api_account_usage_endpoint(auth_key):
    client = TestClient(app)

    # Unauthenticated rejected with 401
    res_unauth = client.get("/v1/account/usage")
    assert res_unauth.status_code == 401

    # Authenticated returns usage report
    res = client.get(
        "/v1/account/usage",
        headers={"Authorization": f"Bearer {auth_key}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "tier" in data
    assert "credits_remaining" in data
    assert "credit_lots" in data
    assert "usage" in data
    assert "rate_limit_state" in data
    assert data["credits_remaining"] == 10

    # Verification: reading usage does not consume credits
    res_again = client.get(
        "/v1/account/usage",
        headers={"X-API-KEY": auth_key},
    )
    assert res_again.json()["credits_remaining"] == 10


def test_sdk_data_exchange_integration(auth_key):
    from sdk.moltbook_intel import MoltbookIntelClient

    # Point client to TestClient-compatible wrapper or simulate calls
    client = TestClient(app)

    # Use MoltbookIntelClient custom request interceptor
    class TestSdkClient(MoltbookIntelClient):
        def _request(self, endpoint, method="GET", json_body=None, auth_required=False, idempotency_key=None):
            headers = {}
            if auth_required or self.api_key:
                headers["X-API-KEY"] = self.api_key
            if idempotency_key:
                headers["Idempotency-Key"] = idempotency_key

            if method == "GET":
                r = client.get(endpoint, headers=headers)
            else:
                r = client.post(endpoint, json=json_body, headers=headers)
            if r.status_code >= 400:
                raise Exception(f"HTTP {r.status_code}: {r.text}")
            return r.json()

    sdk = TestSdkClient(base_url="http://testserver", api_key=auth_key)

    # 1. Capabilities
    caps = sdk.get_capabilities()
    assert caps["service"] == "moltbook-alpha-api"

    # 2. List Data Products
    prods = sdk.list_data_products()
    assert len(prods) >= 3

    # 3. Product Contract
    contract = sdk.get_data_product("moltbook-agent-intelligence-feed")
    assert contract["product_id"] == "moltbook-agent-intelligence-feed"

    # 4. Product Snapshot
    snap = sdk.get_data_product_latest("moltbook-agent-intelligence-feed")
    assert snap["product_id"] == "moltbook-agent-intelligence-feed"
    assert snap["usage_receipt"]["credits_deducted"] == 1

    # 5. Account Usage
    usage = sdk.get_usage()
    assert usage["success"] is True
    assert usage["credits_remaining"] == 9


def test_mcp_exchange_tools_discovery_and_execution(auth_key, monkeypatch):
    server = MoltbookMCPServer()

    # 1. Verify tools/list contains all exchange tools
    req_list = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/list",
        "params": {},
    }
    resp_list = server.handle_request(req_list)
    tool_names = {t["name"] for t in resp_list["result"]["tools"]}

    assert "get_api_capabilities" in tool_names
    assert "list_data_products" in tool_names
    assert "get_data_product_schema" in tool_names
    assert "get_data_product_snapshot" in tool_names
    assert "get_account_usage" in tool_names

    # 2. Test tool execution with monkeypatched client
    monkeypatch.setattr(server.client, "get_capabilities", lambda: {"service": "moltbook-alpha-api", "version": "1.2.0"})
    monkeypatch.setattr(server.client, "list_data_products", lambda: [{"product_id": "test_feed", "cost_credits": 1}])
    monkeypatch.setattr(server.client, "get_data_product", lambda product_id, *args, **kwargs: {"product_id": product_id, "schema": {}})
    monkeypatch.setattr(server.client, "get_data_product_latest", lambda product_id, idempotency_key=None, *args, **kwargs: {"product_id": product_id, "status": "ok"})
    monkeypatch.setattr(server.client, "get_usage", lambda: {"credits_remaining": 9, "tier": "pro"})

    # Call get_api_capabilities
    call_caps = server.handle_request({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {"name": "get_api_capabilities", "arguments": {}},
    })
    assert "moltbook-alpha-api" in call_caps["result"]["content"][0]["text"]

    # Call list_data_products
    call_list = server.handle_request({
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {"name": "list_data_products", "arguments": {}},
    })
    assert "test_feed" in call_list["result"]["content"][0]["text"]

    # Call get_data_product_snapshot
    call_snap = server.handle_request({
        "jsonrpc": "2.0",
        "id": 13,
        "method": "tools/call",
        "params": {"name": "get_data_product_snapshot", "arguments": {"product_id": "test_feed"}},
    })
    assert "test_feed" in call_snap["result"]["content"][0]["text"]

    # Call get_account_usage
    call_usage = server.handle_request({
        "jsonrpc": "2.0",
        "id": 14,
        "method": "tools/call",
        "params": {"name": "get_account_usage", "arguments": {}},
    })
    assert "pro" in call_usage["result"]["content"][0]["text"]
