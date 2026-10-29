"""
Unit tests for Zero-Leak Credential Redactor (ops/security/credential_redactor.py)
and Audit Log Secret Scrubbing.
"""

import tempfile
from pathlib import Path
from ops.security.credential_redactor import credential_redactor, sanitize_audit_log
from storage import StorageManager
from errors import format_error_payload


def test_redact_solana_base58_private_key():
    # 88-character base58 private key string
    fake_privkey = "5MaiiCavjCmn9Hs1g3cw1LtjatmWBV7zBL6jHA4GuCxZwquZyfcipnM2f6BLdTFV6Aegj1k3m8D455qR9rL17z8a"
    raw_text = f"Attempted transfer with signer key {fake_privkey} on treasury"
    scrubbed = sanitize_audit_log(raw_text)

    assert fake_privkey not in scrubbed
    assert "[REDACTED_SECRET:sha256:" in scrubbed


def test_redact_byte_array_key():
    byte_key = "[" + ", ".join(str(i) for i in range(32)) + "]"
    raw_text = f"Keypair raw bytes: {byte_key}"
    scrubbed = sanitize_audit_log(raw_text)

    assert byte_key not in scrubbed
    assert "[REDACTED_SECRET:sha256:" in scrubbed


def test_redact_jwt_token():
    fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgN_pGMstVEMmP_example"
    raw_text = f"Bearer token submitted: {fake_jwt}"
    scrubbed = sanitize_audit_log(raw_text)

    assert fake_jwt not in scrubbed
    assert "[REDACTED_SECRET:sha256:" in scrubbed


def test_redact_moltbook_api_key():
    fake_key = "mb_live_1234567890abcdef1234567890abcdef"
    raw_text = f"Provisioned API credential {fake_key} for client"
    scrubbed = sanitize_audit_log(raw_text)

    assert fake_key not in scrubbed
    assert "[REDACTED_SECRET:sha256:" in scrubbed


def test_redact_recursive_dict():
    secret = "mb_sec_998877665544332211aabbccddeeff"
    nested_data = {
        "status": "error",
        "nested": {
            "credentials": [secret, "public_info"],
            "meta": {"token": secret},
        },
    }
    cleaned = credential_redactor.redact_object(nested_data)

    assert secret not in str(cleaned)
    assert "[REDACTED_SECRET:sha256:" in cleaned["nested"]["credentials"][0]
    assert cleaned["nested"]["credentials"][1] == "public_info"


def test_storage_log_audit_event_scrubs_secrets_in_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_audit.db"
        sm = StorageManager(db_path)

        secret = "mb_sec_audit_leak_test_1234567890abcdef"
        sm.log_audit_event("key_generated", f"Generated new master secret {secret}")

        logs = sm.get_audit_logs(limit=5)
        assert len(logs) == 1
        entry_detail = logs[0]["detail"]

        assert secret not in entry_detail
        assert "[REDACTED_SECRET:sha256:" in entry_detail


def test_format_error_payload_scrubs_secrets():
    secret = "mb_sec_payload_leak_1234567890abcdef"
    payload = format_error_payload(
        code="VALIDATION_ERROR",
        message=f"Validation failed for secret {secret}",
        request_id="req_test_01",
        details={"invalid_token": secret},
    )

    assert secret not in payload["message"]
    assert secret not in payload["error"]["message"]
    assert secret not in str(payload["details"])
    assert "[REDACTED_SECRET:sha256:" in payload["message"]
