"""
Tests for Moltbook Alpha Python Client SDK (sdk/moltbook_intel).
Verifies client initialization, exception taxonomy mapping, DAG parameter planning,
local cryptographic state witness verification, and API method bindings.
"""

import pytest
from sdk.moltbook_intel import (
    MoltbookIntelClient,
    ToolDAGResolver,
    verify_witness_payload_offline,
    PaymentRequiredError,
    RateLimitExceededError,
    InvalidApiKeyError,
)
from sdk.moltbook_intel.exceptions import raise_for_error_payload
from storage import StorageManager
from cryptographic_witness import WitnessManager, WitnessKeyManager


def test_sdk_client_initialization():
    client = MoltbookIntelClient(base_url="http://127.0.0.1:8080/", api_key="test_key_123")
    assert client.base_url == "http://127.0.0.1:8080"
    assert client.api_key == "test_key_123"
    assert client.timeout == 15.0
    assert client.auto_retry is True


def test_sdk_exception_taxonomy_mapping():
    # Test PaymentRequiredError mapping
    with pytest.raises(PaymentRequiredError) as exc_info:
        raise_for_error_payload(
            status_code=402,
            payload={
                "code": "PAYMENT_REQUIRED",
                "message": "Payment Required.",
                "retryable": False,
                "request_id": "req_12345678",
                "docs_url": "https://example.com/docs#PAYMENT_REQUIRED",
            }
        )
    err = exc_info.value
    assert err.code == "PAYMENT_REQUIRED"
    assert err.status_code == 402
    assert err.retryable is False
    assert err.request_id == "req_12345678"

    # Test RateLimitExceededError mapping
    with pytest.raises(RateLimitExceededError) as exc_info_rate:
        raise_for_error_payload(
            status_code=429,
            payload={
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Too many requests.",
                "retryable": True,
                "retry_after": 60,
                "request_id": "req_rate_123",
            }
        )
    err_rate = exc_info_rate.value
    assert err_rate.code == "RATE_LIMIT_EXCEEDED"
    assert err_rate.retryable is True
    assert err_rate.retry_after == 60

    # Test InvalidApiKeyError mapping
    with pytest.raises(InvalidApiKeyError):
        raise_for_error_payload(
            status_code=403,
            payload={"code": "INVALID_API_KEY", "message": "Invalid key."}
        )


def test_sdk_dag_resolver_validation():
    mock_tool_graph = {
        "tool_name": "verify_solana_payment",
        "version": "1.0.0",
        "parameters": {
            "invoice_id": {"name": "invoice_id", "required": True, "prerequisites": []},
            "transaction_signature": {"name": "transaction_signature", "required": True, "prerequisites": []},
            "asset": {"name": "asset", "required": False, "prerequisites": ["transaction_signature"]},
        },
        "topological_stages": [
            ["invoice_id", "transaction_signature"],
            ["asset"]
        ],
    }

    resolver = ToolDAGResolver(mock_tool_graph)
    assert resolver.tool_name == "verify_solana_payment"
    assert resolver.get_stage_for_parameter("invoice_id") == 0
    assert resolver.get_stage_for_parameter("asset") == 1

    # Valid input satisfies all required and prerequisites
    valid_inputs = {
        "invoice_id": "inv_123",
        "transaction_signature": "sig_456",
        "asset": "USDC",
    }
    res_valid = resolver.validate(valid_inputs)
    assert res_valid["valid"] is True
    assert len(res_valid["missing_required"]) == 0

    # Missing required parameter: transaction_signature
    missing_inputs = {"invoice_id": "inv_123"}
    res_missing = resolver.validate(missing_inputs)
    assert res_missing["valid"] is False
    assert "transaction_signature" in res_missing["missing_required"]

    # Prerequisite violation: asset provided without transaction_signature
    violated_inputs = {"invoice_id": "inv_123", "asset": "USDC"}
    res_violation = resolver.validate(violated_inputs)
    assert res_violation["valid"] is False
    assert len(res_violation["prerequisite_violations"]) > 0


def test_sdk_offline_cryptographic_witness_verification(tmp_path):
    db_file = tmp_path / "sdk_test.db"
    key_file = tmp_path / "sdk_key.pem"
    sm = StorageManager(db_file)
    km = WitnessKeyManager(key_file)
    wm = WitnessManager(sm, km)

    witness = wm.create_witness(
        action="QUERY_DEDUCTED",
        actor="sdk_agent_tester",
        key_hash="hash_sdk_test",
        lot_id="lot_sdk_001",
        pre_balance=100,
        credit_delta=-1,
        post_balance=99,
        request_id="req_sdk_001",
    )

    # 1. Offline verification passes with legitimate witness and public key
    pub_key_b58 = km.public_key_base58
    res = verify_witness_payload_offline(witness, pub_key_b58)
    assert res["valid"] is True
    assert res["digest_matches"] is True
    assert res["signature_valid"] is True

    # 2. Tampered witness fails offline verification
    tampered = dict(witness)
    tampered["post_balance"] = 999  # modify state
    res_tamper = verify_witness_payload_offline(tampered, pub_key_b58)
    assert res_tamper["valid"] is False
    assert res_tamper["digest_matches"] is False


def test_sdk_rate_limit_retry_with_backoff_and_jitter():
    import io
    import json
    import urllib.error
    import urllib.request
    from unittest.mock import patch, MagicMock
    from sdk.moltbook_intel import MoltbookIntelClient

    client = MoltbookIntelClient(base_url="http://mock-api.test", api_key="molt_test_key", max_retries=2)

    err_429_body = json.dumps({
        "error": {
            "code": "RATE_LIMITED",
            "message": "Request rate exceeded.",
            "retryable": True,
            "retry_after_seconds": 1,
        }
    }).encode("utf-8")
    mock_hdrs = {"Retry-After": "1", "X-Request-ID": "req_sdk_test"}
    http_err_429 = urllib.error.HTTPError(
        "http://mock-api.test/v1/briefing/latest",
        429,
        "Too Many Requests",
        mock_hdrs,
        io.BytesIO(err_429_body),
    )

    resp_200 = MagicMock()
    resp_200.read.return_value = json.dumps({"success": True, "briefing_markdown": "Market Analysis"}).encode("utf-8")
    resp_200.__enter__.return_value = resp_200

    with patch("urllib.request.urlopen", side_effect=[http_err_429, resp_200]) as mock_open, \
         patch("time.sleep") as mock_sleep:
        data = client.get_latest_briefing()
        assert data["success"] is True
        assert mock_open.call_count == 2
        assert mock_sleep.call_count == 1
        sleep_dur = mock_sleep.call_args[0][0]
        assert sleep_dur >= 1.0


def test_sdk_entitlement_exhausted_halts_retries():
    import io
    import json
    import urllib.error
    from unittest.mock import patch
    from sdk.moltbook_intel import MoltbookIntelClient, EntitlementExhaustedError

    client = MoltbookIntelClient(base_url="http://mock-api.test", api_key="molt_test_key", max_retries=3)

    err_402_body = json.dumps({
        "error": {
            "code": "ENTITLEMENT_EXHAUSTED",
            "message": "Monthly entitlement exhausted.",
            "retryable": False,
        }
    }).encode("utf-8")
    http_err_402 = urllib.error.HTTPError(
        "http://mock-api.test/v1/briefing/latest",
        402,
        "Payment Required",
        {},
        io.BytesIO(err_402_body),
    )

    with patch("urllib.request.urlopen", side_effect=http_err_402) as mock_open:
        with pytest.raises(EntitlementExhaustedError) as exc_info:
            client.get_latest_briefing()

        # Crucial requirement: Must halt immediately without retrying
        assert mock_open.call_count == 1
        assert exc_info.value.code == "ENTITLEMENT_EXHAUSTED"
        assert exc_info.value.retryable is False


def test_sdk_idempotency_key_propagation():
    import json
    from unittest.mock import patch, MagicMock
    from sdk.moltbook_intel import MoltbookIntelClient

    client = MoltbookIntelClient(base_url="http://mock-api.test", api_key="molt_test_key")

    resp_200 = MagicMock()
    resp_200.read.return_value = json.dumps({"success": True}).encode("utf-8")
    resp_200.__enter__.return_value = resp_200

    with patch("urllib.request.urlopen", return_value=resp_200) as mock_open:
        client.get_latest_briefing(idempotency_key="idemp_unique_xyz_789")
        assert mock_open.call_count == 1
        req_obj = mock_open.call_args[0][0]
        header_keys = {k.lower(): v for k, v in req_obj.headers.items()}
        assert header_keys.get("idempotency-key") == "idemp_unique_xyz_789"
