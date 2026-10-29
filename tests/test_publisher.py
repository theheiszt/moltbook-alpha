"""
Tests for Automated Community Alpha Publisher (ops/publisher.py).
Verifies briefing synthesis, Ed25519 cryptographic state witness signing,
static documentation generation in docs/reports/, and community dispatch to Moltbook.
"""

from unittest.mock import MagicMock
from storage import StorageManager
from cryptographic_witness import WitnessManager, WitnessKeyManager
from ops.publisher import publish_daily_alpha


def test_publish_daily_alpha_dry_run(tmp_path):
    db_file = tmp_path / "test_pub.db"
    key_file = tmp_path / "test_wit.pem"
    docs_dir = tmp_path / "docs" / "reports"

    sm = StorageManager(db_file)
    w_km = WitnessKeyManager(key_file)
    w_mgr = WitnessManager(sm, w_km)

    res = publish_daily_alpha(
        submolt="builds",
        dry_run=True,
        force_refresh=False,
        output_docs_dir=docs_dir,
        storage_manager=sm,
        witness_manager=w_mgr,
    )

    assert res["success"] is True
    assert res["briefing_id"].startswith("brf_")
    assert res["state_witness_id"].startswith("wit_")
    assert res["moltbook_posted"] is False

    # Verify static report files exist and have content
    assert (docs_dir / "latest_briefing.md").exists()
    content = (docs_dir / "latest_briefing.md").read_text(encoding="utf-8")
    assert "# Moltbook Alpha" in content
    assert res["briefing_id"] in content or "Briefing" in content


def test_publish_daily_alpha_with_mock_client(tmp_path):
    db_file = tmp_path / "test_pub_client.db"
    key_file = tmp_path / "test_wit_client.pem"
    docs_dir = tmp_path / "docs" / "reports"

    sm = StorageManager(db_file)
    w_km = WitnessKeyManager(key_file)
    w_mgr = WitnessManager(sm, w_km)

    mock_client = MagicMock()
    mock_client.create_post.return_value = ({"success": True, "post": {"id": "p_test_123"}}, True)

    res = publish_daily_alpha(
        submolt="builds",
        dry_run=False,
        force_refresh=False,
        output_docs_dir=docs_dir,
        storage_manager=sm,
        witness_manager=w_mgr,
        client=mock_client,
    )

    assert res["success"] is True
    assert res["moltbook_posted"] is True
    assert res["moltbook_post_result"]["verified"] is True
    mock_client.create_post.assert_called_once()
    args, _ = mock_client.create_post.call_args
    assert args[0] == "builds"
    assert "Moltbook Alpha Daily" in args[1]

    # Verify audit event in database
    audit_logs = sm.get_audit_logs(limit=10)
    pub_events = [e for e in audit_logs if e["event_type"] == "community_alpha_published"]
    assert len(pub_events) >= 1
    assert res["briefing_id"] in pub_events[0]["detail"]
