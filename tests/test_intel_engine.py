"""
Tests for Moltbook Alpha Information Collection & Intelligence Engine.
Verifies schema initialization, approved source seeding, content deduplication,
signal extraction across all categories, briefing synthesis, and API endpoints.
"""

from fastapi.testclient import TestClient
from storage import StorageManager
from cryptographic_witness import WitnessManager, WitnessKeyManager
from intel_engine import IntelEngine
from api_server import app, storage


def test_intel_schema_and_sources_seeding(tmp_path):
    db_file = tmp_path / "test_intel.db"
    sm = StorageManager(db_file)
    engine = IntelEngine(sm)
    assert engine.storage is sm

    with sm.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT source_id, source_name, source_type FROM intel_sources")
        sources = cur.fetchall()
        assert len(sources) >= 8
        sids = {s["source_id"] for s in sources}
        assert "moltbook_submolt_builds" in sids
        assert "internal_audit_logs" in sids
        assert "git_repository_log" in sids


def test_intel_deduplication_by_content_hash(tmp_path):
    db_file = tmp_path / "test_dedup.db"
    sm = StorageManager(db_file)
    engine = IntelEngine(sm)

    # Ingest internal audit logs
    sm.log_audit_event("test_event_1", "Audit details for deduplication test")
    sm.log_audit_event("test_event_2", "Audit details for second event")

    count1 = engine.ingest_internal_audit_logs(limit=10)
    assert count1 >= 2

    # Second ingestion of the same logs should yield 0 new items
    count2 = engine.ingest_internal_audit_logs(limit=10)
    assert count2 == 0


def test_signal_extraction_heuristic_rules(tmp_path):
    db_file = tmp_path / "test_signals.db"
    sm = StorageManager(db_file)
    engine = IntelEngine(sm)

    # Insert items across different categories
    now_iso = "2026-10-18T00:00:00Z"
    with sm.connection() as conn:
        cur = conn.cursor()
        # Security item
        cur.execute("""
            INSERT INTO intel_items (
                item_id, source_id, content_hash, author, title, content,
                url, raw_metadata_json, published_at, ingested_at, engagement_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "itm_sec_1", "moltbook_submolt_builds", "hash_sec_1", "security_researcher",
            "Critical CVE Exploit in Unsigned Skills",
            "Discovered a privilege escalation vulnerability where unsigned skill binaries leak private keys.",
            "https://moltbook.com/posts/sec1", "{}", now_iso, now_iso, 15
        ))

        # Operational failure item
        cur.execute("""
            INSERT INTO intel_items (
                item_id, source_id, content_hash, author, title, content,
                url, raw_metadata_json, published_at, ingested_at, engagement_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "itm_fail_1", "internal_audit_logs", "hash_fail_1", "system",
            "[Audit Event] RPC_GATEWAY_ERROR",
            "502 Bad Gateway and connection refused while querying Solana primary RPC endpoint timeout.",
            "local://audit/1", "{}", now_iso, now_iso, 20
        ))

        # Architecture pattern item
        cur.execute("""
            INSERT INTO intel_items (
                item_id, source_id, content_hash, author, title, content,
                url, raw_metadata_json, published_at, ingested_at, engagement_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "itm_arch_1", "moltbook_submolt_builds", "hash_arch_1", "architect",
            "Designing DAG Parameters for Autonomous Agents",
            "Using directed acyclic graph compilation with Kahn topological sort and cryptographic state witnesses.",
            "https://moltbook.com/posts/arch1", "{}", now_iso, now_iso, 12
        ))
        conn.commit()

    extracted = engine.extract_signals(limit_items=10)
    assert extracted >= 3

    # Verify signals in database
    sec_signals = engine.search_signals(category="security_advisory")
    assert len(sec_signals) >= 1
    assert sec_signals[0]["requires_human_review"] is True
    assert "security_researcher" in sec_signals[0]["author"]

    fail_signals = engine.search_signals(category="operational_failure")
    assert len(fail_signals) >= 1
    assert fail_signals[0]["automated_remedy_available"] is True

    arch_signals = engine.search_signals(category="architecture_pattern")
    assert len(arch_signals) >= 1


def test_briefing_synthesis_and_witnessing(tmp_path):
    db_file = tmp_path / "test_synth.db"
    key_file = tmp_path / "witness.pem"
    sm = StorageManager(db_file)
    w_km = WitnessKeyManager(key_file)
    w_mgr = WitnessManager(sm, w_km)
    engine = IntelEngine(sm)

    # Ingest git history and extract signals
    engine.ingest_git_history(limit=5)
    engine.extract_signals(limit_items=10)

    # Synthesize briefing
    res = engine.generate_briefing(witness_manager=w_mgr)
    assert "briefing_id" in res
    assert res["briefing_id"].startswith("brf_")
    assert res["state_witness_id"] is not None
    assert res["state_witness_id"].startswith("wit_")

    # Verify the generated state witness payload
    w_record = w_mgr.get_witness(res["state_witness_id"])
    assert w_record is not None
    assert w_record["action"] == "BRIEFING_COMPILED"
    v_res = w_mgr.verify_witness_payload(w_record)
    assert v_res["valid"] is True


def test_api_intel_signals_endpoint():
    client = TestClient(app)
    assert client.get("/v1/intel/signals?limit=10").status_code == 402

    raw_key, _ = storage.create_api_key(tier="tier_pro", credits=10)
    resp = client.get("/v1/intel/signals?limit=10", headers={"X-API-KEY": raw_key})
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "signals" in data
    assert isinstance(data["signals"], list)


def test_api_intel_latest_endpoint_with_auth():
    client = TestClient(app)

    # Unauthenticated request must return 402 with structured error contract
    resp_unauth = client.get("/v1/intel/latest")
    assert resp_unauth.status_code == 402
    assert "PAYMENT_REQUIRED" in resp_unauth.json()["code"]

    # Authenticated request with valid key must succeed
    raw_key, _ = storage.create_api_key(tier="starter", credits=10, prefix_tag="molt_intel_api")
    resp_auth = client.get("/v1/intel/latest", headers={"X-API-KEY": raw_key})
    assert resp_auth.status_code == 200
    body = resp_auth.json()
    assert body["success"] is True
    assert "briefing_markdown" in body
    assert len(body["briefing_markdown"]) > 100
    assert "state_witness_id" in body


def test_onchain_dex_telemetry_ingestion_and_quant_signals(tmp_path):
    db_file = tmp_path / "test_dex.db"
    sm = StorageManager(db_file)
    engine = IntelEngine(sm)

    mock_feed = [
        {
            "symbol": "SOL",
            "mint": "So11111111111111111111111111111111111111112",
            "price": 182.45,
            "confidence": "HIGH",
            "depth": {"bids": 1200000, "asks": 1150000},
            "last_swapped": {"buyPrice": 182.90, "sellPrice": 181.80},
        },
        {
            "symbol": "JUP",
            "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
            "price": 1.25,
            "confidence": "HIGH",
            "depth": {"bids": 400000, "asks": 380000},
            "last_swapped": {"buyPrice": 1.25, "sellPrice": 1.25},
        }
    ]

    count = engine.ingest_onchain_dex_telemetry(mock_feed=mock_feed)
    assert count == 2

    # Deduplication test
    count_dupe = engine.ingest_onchain_dex_telemetry(mock_feed=mock_feed)
    assert count_dupe == 0

    # Extract quant signals
    sig_count = engine.extract_signals(limit_items=10)
    assert sig_count >= 1

    signals = engine.search_signals(category="arbitrage_spread")
    assert len(signals) >= 1
    assert "Cross-Pool Arbitrage" in signals[0]["headline"]
    assert signals[0]["confidence"] == "VERIFIED"
    assert "Jupiter" in signals[0]["remedy_description"]


def test_solana_cluster_telemetry_ingestion_and_signals(tmp_path):
    db_file = tmp_path / "test_cluster.db"
    sm = StorageManager(db_file)
    engine = IntelEngine(sm)

    # Ingest high-throughput telemetry
    telemetry_surge = {
        "slot": 312050000,
        "tps": 2850.5,
        "non_vote_tps": 1120.0,
        "sample_period_secs": 60,
        "health": "ok",
        "rpc_endpoint": "https://api.mainnet-beta.solana.com",
    }

    count = engine.ingest_solana_cluster_telemetry(mock_telemetry=telemetry_surge)
    assert count == 1

    # Extract signals
    engine.extract_signals(limit_items=10)
    surge_sigs = engine.search_signals(category="liquidity_surge")
    assert len(surge_sigs) >= 1
    assert "Throughput Surge" in surge_sigs[0]["headline"]

    # Ingest degraded cluster telemetry
    telemetry_degraded = {
        "slot": 312050500,
        "tps": 340.0,
        "non_vote_tps": 85.0,
        "sample_period_secs": 60,
        "health": "degraded",
        "rpc_endpoint": "https://api.mainnet-beta.solana.com",
    }
    engine.ingest_solana_cluster_telemetry(mock_telemetry=telemetry_degraded)
    engine.extract_signals(limit_items=10)

    fail_sigs = engine.search_signals(category="operational_failure")
    cluster_fail = [s for s in fail_sigs if "Cluster Health Notice" in s["headline"]]
    assert len(cluster_fail) >= 1
    assert cluster_fail[0]["confidence"] == "VERIFIED"
