"""
Tests for Audit Logging, Key Revocation, Database Health, and Administrative CLI extensions.
"""

from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from storage import StorageManager
from api_server import app, storage, rate_limiter
import cli


def test_audit_logging_and_retrieval(tmp_path: Path):
    db_file = tmp_path / "test_audit.db"
    mgr = StorageManager(db_file)

    mgr.log_audit_event("auth_failure", "Invalid key provided", ip_address="192.0.2.1")
    mgr.log_audit_event("payment_redeemed", "Redeemed 1000000 USDC", ip_address="192.0.2.2")

    logs = mgr.get_audit_logs(limit=10)
    assert len(logs) == 2
    assert logs[0]["event_type"] == "payment_redeemed"
    assert "192.0.2.2" in logs[0]["detail"]
    assert logs[1]["event_type"] == "auth_failure"
    assert "192.0.2.1" in logs[1]["detail"]

    # Test filtering by event_type
    auth_logs = mgr.get_audit_logs(limit=10, event_type="auth_failure")
    assert len(auth_logs) == 1
    assert auth_logs[0]["event_type"] == "auth_failure"


def test_key_revocation_prevents_api_access(tmp_path: Path):
    db_file = tmp_path / "test_revocation.db"
    mgr = StorageManager(db_file)

    raw_token, record = mgr.create_api_key(tier="starter", credits=25, prefix_tag="molt_active")

    # Verify active
    info, state = mgr.authenticate_and_deduct(raw_token)
    assert state == "ok"
    assert info["credits"] == 24

    # Revoke key using prefix
    revoked = mgr.revoke_key(record["key_prefix"][:10])
    assert revoked is True

    # Subsequent auth must be rejected as 'revoked'
    info2, state2 = mgr.authenticate_and_deduct(raw_token)
    assert state2 == "revoked"
    assert info2 is None

    # Revocation was logged in audit_logs
    audit_events = mgr.get_audit_logs(limit=5, event_type="key_revocation")
    assert len(audit_events) == 1
    assert "Revoked API key" in audit_events[0]["detail"]


def test_storage_check_health(tmp_path: Path):
    db_file = tmp_path / "test_health.db"
    mgr = StorageManager(db_file)
    assert mgr.check_health() is True


def test_cli_revoke_key_command(capsys):
    # Create key to revoke
    raw_token, record = storage.create_api_key(tier="trial", credits=5, prefix_tag="molt_cli_test")
    cli.revoke_key(record["key_prefix"])

    captured = capsys.readouterr()
    assert "Successfully revoked API key" in captured.out

    # Authenticate should fail
    _, state = storage.authenticate_and_deduct(raw_token)
    assert state == "revoked"


def test_cli_view_audit_logs(capsys):
    storage.log_audit_event("cli_test_event", "Testing CLI output format")
    cli.view_audit_logs(limit=5)
    captured = capsys.readouterr()
    assert "SECURITY AUDIT LOGS" in captured.out
    assert "cli_test_event" in captured.out


def test_api_logs_audit_events_for_payments():
    client = TestClient(app)
    rate_limiter.reset()

    test_sig = "9zzzzz" * 15  # valid base58 length 90
    payload = {"transaction_signature": test_sig, "target_tier": "tier_starter"}

    with patch("api_server.SolanaPaymentVerifier.verify_payment") as mock_verify:
        from payment_verifier import VerifiedPayment
        mock_verify.return_value = VerifiedPayment(
            tx_signature=test_sig,
            asset="USDC",
            amount_raw=1_000_000,
            tier="tier_starter",
            credits=50,
            recipient="DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC",
        )

        resp = client.post(
            "/v1/payments/verify-solana",
            json=payload,
            headers={"x-forwarded-for": "192.0.2.99"},
        )
        assert resp.status_code == 200

        # Check that audit log recorded payment_redeemed_success
        logs = storage.get_audit_logs(limit=10, event_type="payment_redeemed_success")
        assert len(logs) >= 1
        assert any("Redeemed USDC" in log["detail"] and "192.0.2.99" in log["detail"] for log in logs)
