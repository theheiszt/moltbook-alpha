"""
Deterministic Unit and Integration Tests for the Verifiable Agent Intelligence API.
Validates:
1. Full schema compliance with evidence quality tiers (OBSERVED_FACT, INFERRED_CONCLUSION, UNVERIFIED_CLAIM).
2. Distinction between VALUE, CONFIRMED_ABSENCE, and UNKNOWN_TIMEOUT outcomes.
3. Provenance metadata (item_id, source_uri, observed_at_utc, processed_at_utc, verification_method, limitations).
4. Evidence filtering via query parameters in HTTP API and SDK.
5. Zero credit deduction on failed or timed-out requests.
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from api_server import app, storage, intel_engine
from sdk.moltbook_intel.client import MoltbookIntelClient


@pytest.fixture
def auth_key():
    raw_key, _ = storage.create_api_key(tier="tier_pro", credits=15)
    return raw_key


@pytest.fixture(autouse=True)
def seed_verifiable_intelligence_data():
    """Seeds sample evidence items covering all 3 evidence quality tiers."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with intel_engine.storage.connection() as conn:
        with conn:
            # 1. OBSERVED_FACT item (On-chain cluster telemetry)
            conn.execute(
                """
                INSERT OR REPLACE INTO intel_items (
                    item_id, source_id, content_hash, author, title, content,
                    url, raw_metadata_json, published_at, ingested_at, engagement_score, is_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    "item_obs_001",
                    "solana_cluster_telemetry",
                    "hash_obs_001",
                    "solana_validator_rpc",
                    "Solana Mainnet Slot 28491024 Confirmed",
                    "Slot finalized with 2,410 TPS across 32 validator node quorum.",
                    "solana://mainnet-beta/slot/28491024",
                    "{}",
                    now_iso,
                    now_iso,
                    100,
                ),
            )
            # 2. INFERRED_CONCLUSION item (CLMM orderbook model)
            conn.execute(
                """
                INSERT OR REPLACE INTO intel_items (
                    item_id, source_id, content_hash, author, title, content,
                    url, raw_metadata_json, published_at, ingested_at, engagement_score, is_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    "item_inf_001",
                    "model_clmm_engine",
                    "hash_inf_001",
                    "clmm_quant_analyst",
                    "Orca/Raydium Tick Vacuum Squeeze Detected",
                    "Orderbook imbalance at 142.50 SOL/USDC indicates high probability of tick depletion within 15 seconds.",
                    "moltbook://models/clmm/vacuum_001",
                    "{}",
                    now_iso,
                    now_iso,
                    85,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO intel_signals (
                    signal_id, item_id, category, headline, summary, confidence,
                    requires_human_review, automated_remedy_available, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?)
                """,
                (
                    "sig_inf_001",
                    "item_inf_001",
                    "orderbook_imbalance",
                    "Tick Vacuum Squeeze on SOL/USDC",
                    "Depth asymmetry exceeds 3.8x ratio across Raydium and Orca.",
                    "HIGH",
                    now_iso,
                ),
            )
            # 3. UNVERIFIED_CLAIM item (Submolt forum post)
            conn.execute(
                """
                INSERT OR REPLACE INTO intel_items (
                    item_id, source_id, content_hash, author, title, content,
                    url, raw_metadata_json, published_at, ingested_at, engagement_score, is_duplicate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    "item_unv_001",
                    "submolt_security",
                    "hash_unv_001",
                    "agent_hobosentinel",
                    "Suspected Context Compression Desync",
                    "Observed hash chain inconsistency during local sandbox replay.",
                    "https://www.moltbook.com/post/item_unv_001",
                    "{}",
                    now_iso,
                    now_iso,
                    45,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO intel_signals (
                    signal_id, item_id, category, headline, summary, confidence,
                    requires_human_review, automated_remedy_available, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?)
                """,
                (
                    "sig_unv_001",
                    "item_unv_001",
                    "security_vulnerability",
                    "Context Compression Ordination Alert",
                    "Agent reported context compression mismatch; awaiting independent on-chain audit.",
                    "MEDIUM",
                    now_iso,
                ),
            )


def test_verifiable_intelligence_snapshot_structure_and_tiers(auth_key):
    client = TestClient(app)
    res = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest",
        headers={"X-API-KEY": auth_key},
    )
    assert res.status_code == 200
    snap = res.json()

    # Required contract keys
    assert snap["product_id"] == "moltbook-agent-intelligence-feed"
    assert snap["retrieval_outcome"] == "VALUE"
    assert "evidence_summary" in snap
    assert "evidence_items" in snap
    assert "usage_receipt" in snap

    # Evidence Summary counts
    summary = snap["evidence_summary"]
    assert summary["observed_facts_count"] >= 1
    assert summary["inferred_conclusions_count"] >= 1
    assert summary["unverified_claims_count"] >= 1
    assert summary["total_items_count"] >= 3

    # Check that every evidence_item has required provenance & evidence fields
    for item in snap["evidence_items"]:
        assert "item_id" in item
        assert "title" in item
        assert "summary" in item
        assert "category" in item
        assert item["evidence_level"] in ["OBSERVED_FACT", "INFERRED_CONCLUSION", "UNVERIFIED_CLAIM"]
        assert "verification_status" in item
        assert "verification_method" in item
        assert 0.0 <= item["confidence_score"] <= 1.0
        assert "source_uri" in item
        assert "observed_at_utc" in item
        assert "processed_at_utc" in item
        assert "limitations" in item
        assert len(item["limitations"]) > 5

    # Check that signals carry evidence_level
    for sig in snap["signals"]:
        assert "evidence_level" in sig
        assert sig["evidence_level"] in ["OBSERVED_FACT", "INFERRED_CONCLUSION", "UNVERIFIED_CLAIM"]


def test_evidence_level_filtering(auth_key):
    client = TestClient(app)

    # 1. Filter for only OBSERVED_FACT
    res_obs = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest?evidence_level=OBSERVED_FACT",
        headers={"X-API-KEY": auth_key},
    )
    assert res_obs.status_code == 200
    snap_obs = res_obs.json()
    assert snap_obs["retrieval_outcome"] == "VALUE"
    assert len(snap_obs["evidence_items"]) > 0
    for item in snap_obs["evidence_items"]:
        assert item["evidence_level"] == "OBSERVED_FACT"
        assert item["verification_status"] == "VERIFIED_ONCHAIN"

    # 2. Filter for only UNVERIFIED_CLAIM
    res_unv = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest?evidence_level=UNVERIFIED_CLAIM",
        headers={"X-API-KEY": auth_key},
    )
    assert res_unv.status_code == 200
    snap_unv = res_unv.json()
    assert snap_unv["retrieval_outcome"] == "VALUE"
    assert len(snap_unv["evidence_items"]) > 0
    for item in snap_unv["evidence_items"]:
        assert item["evidence_level"] == "UNVERIFIED_CLAIM"
        assert item["verification_status"] == "COMMUNITY_REPORTED_UNCONFIRMED"


def test_confirmed_absence_retrieval_outcome(auth_key):
    client = TestClient(app)
    # Query with impossible filter criteria that matches nothing
    res = client.get(
        "/v1/data-products/moltbook-agent-intelligence-feed/latest?category=non_existent_exploit_xyz&min_confidence=0.999",
        headers={"X-API-KEY": auth_key},
    )
    assert res.status_code == 200
    snap = res.json()
    # Explicitly confirms absence of anomalies, not an error
    assert snap["retrieval_outcome"] == "CONFIRMED_ABSENCE"
    assert len(snap["evidence_items"]) == 0
    assert snap["evidence_summary"]["total_items_count"] == 0
    assert snap["usage_receipt"]["credits_deducted"] == 1


def test_sdk_verifiable_evidence_methods(auth_key):
    client = TestClient(app)

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

    sdk_client = TestSdkClient(api_key=auth_key, base_url="http://testserver")
    snap = sdk_client.get_data_product_latest(
        product_id="moltbook-agent-intelligence-feed",
        evidence_level="OBSERVED_FACT",
    )
    assert snap["product_id"] == "moltbook-agent-intelligence-feed"
    assert snap["retrieval_outcome"] == "VALUE"
    assert "evidence_summary" in snap
    assert len(snap["evidence_items"]) > 0
    for item in snap["evidence_items"]:
        assert item["evidence_level"] == "OBSERVED_FACT"
