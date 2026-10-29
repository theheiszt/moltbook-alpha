"""
Unit tests for Moltbook Alpha Observatory Source Adapter (ops/observatory_adapter.py).
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from storage import StorageManager
from ops.observatory_adapter import (
    ObservatoryClient,
    ObservatorySourceAdapter,
    ATTRIBUTION_NOTICE,
    SOURCE_ID_TRENDS,
    SOURCE_ID_SUBMOLTS,
)


@pytest.fixture
def test_storage(tmp_path):
    db_file = tmp_path / "test_observatory.db"
    return StorageManager(db_file)


def test_observatory_schema_init(test_storage):
    """Verify that adapter creates sync state table and seeds sources."""
    adapter = ObservatorySourceAdapter(storage_manager=test_storage)
    with test_storage.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='observatory_sync_state'")
        assert cur.fetchone() is not None

        cur.execute("SELECT source_id, source_name FROM intel_sources WHERE source_id IN (?, ?)", (SOURCE_ID_TRENDS, SOURCE_ID_SUBMOLTS))
        rows = cur.fetchall()
        assert len(rows) == 2
        assert any(SOURCE_ID_TRENDS in r[0] for r in rows)
        assert any(SOURCE_ID_SUBMOLTS in r[0] for r in rows)


def test_sync_macro_trends_success(test_storage):
    """Verify syncing macro trends, generating signals, and deduplicating."""
    mock_client = MagicMock(spec=ObservatoryClient)
    mock_client.base_url = "https://mock-observatory.local"
    mock_client.get_trends.return_value = {
        "success": True,
        "status": 200,
        "data": {
            "period_hours": 24,
            "trends": [
                {"word": "cve", "count": 120, "previous_count": 20, "change_percent": 500.0},
                {"word": "arbitrage", "count": 85, "previous_count": 40, "change_percent": 112.5},
                {"word": "rate", "count": 150, "previous_count": 120, "change_percent": 25.0},
                {"word": "randomfiller", "count": 2, "previous_count": 1, "change_percent": 10.0},  # Below threshold
            ]
        }
    }

    adapter = ObservatorySourceAdapter(storage_manager=test_storage, client=mock_client)
    res = adapter.sync_macro_trends(hours=24, min_count=20, min_change_pct=30.0)

    assert res["success"] is True
    assert res["new_items_ingested"] == 3  # cve, arbitrage, rate (randomfiller filtered out)
    assert res["new_signals_extracted"] == 3

    # Verify signals classification
    with test_storage.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT category, headline, confidence FROM intel_signals WHERE signal_id LIKE 'sig_obs_%'")
        sigs = cur.fetchall()
        assert len(sigs) == 3
        categories = {s[0] for s in sigs}
        assert "security_audit" in categories  # 'cve'
        assert "market_alpha" in categories    # 'arbitrage'

    # Duplicate run should ingest 0 new items
    res_dup = adapter.sync_macro_trends(hours=24, min_count=20, min_change_pct=30.0)
    assert res_dup["success"] is True
    assert res_dup["new_items_ingested"] == 0


def test_sync_submolt_directory(test_storage):
    """Verify syncing submolt directory metadata snapshot."""
    mock_client = MagicMock(spec=ObservatoryClient)
    mock_client.base_url = "https://mock-observatory.local"
    mock_client.get_submolts.return_value = {
        "success": True,
        "status": 200,
        "data": {
            "submolts": [
                {"name": "agentfinance", "subscriber_count": 250, "post_count": 400},
                {"name": "builds", "subscriber_count": 180, "post_count": 300},
                {"name": "deadcommunity", "subscriber_count": 0, "post_count": 0},
            ]
        }
    }

    adapter = ObservatorySourceAdapter(storage_manager=test_storage, client=mock_client)
    res = adapter.sync_submolt_directory(min_subscribers=5)

    assert res["success"] is True
    assert res["total_submolts"] == 3
    assert res["active_submolts"] == 2

    # Verify checkpoint
    st = adapter.get_status()
    assert "submolt_directory" in st["checkpoints"]
    assert st["checkpoints"]["submolt_directory"]["status"] == "IDLE"
    assert st["checkpoints"]["submolt_directory"]["records_count"] == 3


def test_sync_handles_503_gracefully(test_storage):
    """Verify graceful handling when Observatory API is unavailable."""
    mock_client = MagicMock(spec=ObservatoryClient)
    mock_client.get_trends.return_value = {
        "success": False,
        "status": 503,
        "error": "Service Temporarily Unavailable"
    }

    adapter = ObservatorySourceAdapter(storage_manager=test_storage, client=mock_client)
    res = adapter.sync_macro_trends()

    assert res["success"] is False
    assert "503" in res["error"] or "Unavailable" in res["error"]

    st = adapter.get_status()
    assert st["checkpoints"]["macro_trends_24h"]["status"] == "ERROR"


def test_disabled_feature_flag(test_storage):
    """Verify adapter skips execution when enabled=False."""
    mock_client = MagicMock(spec=ObservatoryClient)
    adapter = ObservatorySourceAdapter(storage_manager=test_storage, client=mock_client, enabled=False)

    res = adapter.sync_macro_trends()
    assert res["success"] is False
    assert res["skipped"] is True
    assert mock_client.get_trends.call_count == 0


def test_get_recent_trends_and_filtering(test_storage):
    """Verify retrieving recent trends and filtering by category."""
    mock_client = MagicMock(spec=ObservatoryClient)
    mock_client.base_url = "https://mock-observatory.local"
    mock_client.get_trends.return_value = {
        "success": True,
        "status": 200,
        "data": {
            "period_hours": 24,
            "trends": [
                {"word": "cve", "count": 100, "previous_count": 10, "change_percent": 900.0},
                {"word": "arbitrage", "count": 60, "previous_count": 20, "change_percent": 200.0},
            ]
        }
    }

    adapter = ObservatorySourceAdapter(storage_manager=test_storage, client=mock_client)
    res = adapter.get_recent_trends(hours=24)
    assert res["count"] == 2
    assert res["attribution"] == ATTRIBUTION_NOTICE

    # Filter by security_audit
    sec_res = adapter.get_recent_trends(category="security_audit")
    assert sec_res["count"] == 1
    assert sec_res["trends"][0]["category"] == "security_audit"
    assert "cve" in sec_res["trends"][0]["headline"].lower()


def test_api_server_observatory_endpoints():
    """Verify FastAPI routes for /v1/intel/observatory/status and /trends."""
    from fastapi.testclient import TestClient
    from api_server import app

    client = TestClient(app)

    # 1. Status endpoint
    resp_status = client.get("/v1/intel/observatory/status")
    assert resp_status.status_code == 200
    st_data = resp_status.json()
    assert "attribution" in st_data
    assert "checkpoints" in st_data

    # 2. Trends endpoint
    resp_trends = client.get("/v1/intel/observatory/trends")
    assert resp_trends.status_code == 200
    tr_data = resp_trends.json()
    assert "attribution" in tr_data
    assert "trends" in tr_data

