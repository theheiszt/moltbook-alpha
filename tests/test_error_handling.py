"""
Comprehensive automated tests for Agent-Native Error Taxonomy,
Schema Conformance, Request ID Propagation, Redaction, and Backwards Compatibility.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient

from api_server import app, storage, rate_limiter
from errors import ErrorCode, ERROR_REGISTRY
from payment_verifier import SolanaPaymentVerifier, RPCError


def test_error_schema_conformance_on_402():
    client = TestClient(app)
    resp = client.get("/v1/briefing/latest")
    assert resp.status_code == 402
    assert resp.headers["content-type"].startswith("application/json")

    data = resp.json()
    # Required taxonomy fields
    assert "code" in data
    assert data["code"] == ErrorCode.PAYMENT_REQUIRED.value
    assert "message" in data
    assert isinstance(data["message"], str)
    assert "details" in data
    assert data["retryable"] is False
    assert data["retry_after"] is None
    assert "request_id" in data
    assert data["request_id"].startswith("req_")
    assert "docs_url" in data
    assert ErrorCode.PAYMENT_REQUIRED.value in data["docs_url"]

    # Header correlation
    assert "x-request-id" in resp.headers
    assert resp.headers["x-request-id"] == data["request_id"]

    # Backwards compatibility bridge
    assert "detail" in data
    assert isinstance(data["detail"], dict)
    assert data["detail"]["error"] == "Payment Required"
    assert "purchase_instructions" in data["detail"]


def test_request_id_propagation_and_custom_header():
    client = TestClient(app)
    custom_id = "req_custom_agent_trace_987654321"

    # Send custom X-Request-ID
    resp = client.get("/v1/briefing/latest", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 402
    data = resp.json()

    assert resp.headers["x-request-id"] == custom_id
    assert data["request_id"] == custom_id


def test_malformed_requests_and_field_validation_422():
    client = TestClient(app)

    # Submit invalid tier to /v1/payments/invoice
    resp = client.post("/v1/payments/invoice", json={"target_tier": "tier_non_existent"})
    assert resp.status_code == 422
    data = resp.json()

    assert data["code"] == ErrorCode.VALIDATION_ERROR.value
    assert data["retryable"] is False
    assert "details" in data
    assert "errors" in data["details"]
    assert len(data["details"]["errors"]) > 0

    first_err = data["details"]["errors"][0]
    assert "field" in first_err
    assert "message" in first_err
    assert "type" in first_err

    # Legacy detail list bridge preserved
    assert isinstance(data["detail"], list)


def test_missing_invalid_and_revoked_credentials():
    client = TestClient(app)

    # 1. Missing credentials on quota endpoint -> 401 AUTHENTICATION_REQUIRED
    resp_unauth = client.get("/v1/account/quota")
    assert resp_unauth.status_code == 401
    assert resp_unauth.json()["code"] == ErrorCode.AUTHENTICATION_REQUIRED.value
    assert "WWW-Authenticate" in resp_unauth.headers

    # 2. Invalid credentials -> 403 INVALID_API_KEY
    resp_inv = client.get("/v1/account/quota", headers={"X-API-KEY": "molt_completely_bogus_key"})
    assert resp_inv.status_code == 403
    assert resp_inv.json()["code"] == ErrorCode.INVALID_API_KEY.value

    # 3. Revoked credentials -> 403 API_KEY_REVOKED
    raw_key, record = storage.create_api_key(tier="starter", credits=10, prefix_tag="molt_err_rev")
    storage.revoke_key(record["key_prefix"])

    resp_rev = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
    assert resp_rev.status_code == 403
    assert resp_rev.json()["code"] == ErrorCode.API_KEY_REVOKED.value


def test_credits_exhausted_and_entitlement_expired():
    client = TestClient(app)

    # 1. Key with 0 credits -> 402 CREDITS_EXHAUSTED
    raw_key, _ = storage.create_api_key(tier="starter", credits=0, prefix_tag="molt_err_exh")
    resp_exh = client.get("/v1/briefing/latest", headers={"X-API-KEY": raw_key})
    assert resp_exh.status_code == 402
    assert resp_exh.json()["code"] == ErrorCode.CREDITS_EXHAUSTED.value

    from datetime import timedelta
    # 2. Key with expired entitlement -> 402 ENTITLEMENT_EXPIRED
    prem_key, _ = storage.create_api_key(tier="tier_premium", credits=10000, prefix_tag="molt_err_prem")
    storage.renew_entitlement(storage.hash_key(prem_key), tier="tier_premium", validity_days=30)
    # Fast forward clock past 30 days
    storage.advance_clock(timedelta(days=31))

    try:
        resp_exp = client.get("/v1/briefing/latest", headers={"X-API-KEY": prem_key})
        assert resp_exp.status_code == 402
        assert resp_exp.json()["code"] == ErrorCode.ENTITLEMENT_EXPIRED.value
    finally:
        storage.reset_clock()


def test_missing_resources_404():
    client = TestClient(app)

    # 1. Non-existent invoice
    resp = client.get("/v1/payments/invoice/inv_does_not_exist_9999")
    assert resp.status_code == 404
    assert resp.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND.value

    # 2. Non-existent error code in registry
    resp_err = client.get("/v1/errors/NON_EXISTENT_ERROR_CODE")
    assert resp_err.status_code == 404
    assert resp_err.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND.value


def test_unbound_payment_rejection_400():
    client = TestClient(app)
    # Payment without invoice ID or reference account
    resp = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": "1" * 88},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.UNBOUND_PAYMENT_REJECTED.value
    assert "requires an active invoice" in resp.json()["detail"]


def test_rate_limiting_and_retry_guidance_429():
    client = TestClient(app)
    rate_limiter.reset()

    # Rate limit on /v1/payments/invoice is 20 per minute
    ip_headers = {"X-Forwarded-For": "198.51.100.42"}
    for _ in range(20):
        r = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}, headers=ip_headers)
        assert r.status_code == 200

    # 21st must be throttled
    blocked = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}, headers=ip_headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers

    data = blocked.json()
    assert data["code"] == ErrorCode.RATE_LIMIT_EXCEEDED.value
    assert data["retryable"] is True
    assert isinstance(data["retry_after"], int)
    assert data["retry_after"] > 0
    assert str(data["retry_after"]) == blocked.headers["Retry-After"]

    rate_limiter.reset()


def test_transient_infrastructure_errors_502_and_503(monkeypatch):
    client = TestClient(app)

    # 1. Solana RPC Failure -> 502 RPC_GATEWAY_ERROR with retryable=True
    inv_resp = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"})
    inv_id = inv_resp.json()["invoice_id"]
    claim_sec = inv_resp.json()["claim_secret"]

    def mock_rpc_fail(*args, **kwargs):
        raise RPCError("Simulated Solana RPC connection timeout")

    monkeypatch.setattr(SolanaPaymentVerifier, "verify_payment", mock_rpc_fail)

    resp_rpc = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": "2" * 88, "invoice_id": inv_id, "claim_secret": claim_sec},
    )
    assert resp_rpc.status_code == 502
    data_rpc = resp_rpc.json()
    assert data_rpc["code"] == ErrorCode.RPC_GATEWAY_ERROR.value
    assert data_rpc["retryable"] is True
    assert data_rpc["retry_after"] == 5

    # 2. Database Health Failure -> 503 DATABASE_UNAVAILABLE with retryable=True
    def mock_db_fail():
        raise Exception("Disk I/O error on database file")

    monkeypatch.setattr(storage, "check_health", mock_db_fail)

    resp_db = client.get("/v1/health")
    assert resp_db.status_code == 503
    data_db = resp_db.json()
    assert data_db["code"] == ErrorCode.DATABASE_UNAVAILABLE.value
    assert data_db["retryable"] is True
    assert data_db["retry_after"] == 10


def test_unexpected_server_errors_redaction_500():
    client = TestClient(app, raise_server_exceptions=False)
    raw_key, _ = storage.create_api_key(tier="admin", credits=999, prefix_tag="molt_err_500")

    # Patch storage.authenticate_and_deduct to simulate unexpected internal crash
    with patch.object(storage, "authenticate_and_deduct", side_effect=RuntimeError("Secret path C:\\SensDir\\db.sqlite cannot be opened")):
        resp = client.get("/v1/briefing/latest", headers={"X-API-KEY": raw_key})
        assert resp.status_code == 500
        data = resp.json()

        assert data["code"] == ErrorCode.INTERNAL_SERVER_ERROR.value
        assert data["retryable"] is False
        assert "request_id" in data
        assert data["request_id"].startswith("req_")

        # Confirm internal file paths and secret stack traces are NEVER leaked in client response
        assert "SensDir" not in str(data)
        assert "RuntimeError" not in str(data)
        assert "Internal server error" in data["message"]


def test_error_registry_endpoints():
    client = TestClient(app)

    # 1. Full registry GET /v1/errors
    resp = client.get("/v1/errors")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "1.0.0"
    assert "errors" in data
    assert len(data["errors"]) == len(ERROR_REGISTRY)

    for code_name, defn in ERROR_REGISTRY.items():
        assert code_name in data["errors"]
        reg_item = data["errors"][code_name]
        assert reg_item["code"] == code_name
        assert reg_item["status_code"] == defn.status_code
        assert reg_item["retryable"] == defn.retryable
        assert reg_item["docs_url"] == defn.docs_url

    # 2. Single code lookup GET /v1/errors/{code}
    resp_single = client.get("/v1/errors/RATE_LIMIT_EXCEEDED")
    assert resp_single.status_code == 200
    single_data = resp_single.json()
    assert single_data["code"] == "RATE_LIMIT_EXCEEDED"
    assert single_data["status_code"] == 429
    assert single_data["retryable"] is True
    assert single_data["default_retry_after"] == 60


def test_secret_redaction_in_webhook_auth():
    client = TestClient(app)

    # Send wrong secret
    secret_attempt = "super_secret_password_attempt_12345"
    resp = client.post(
        "/v1/payments/webhook",
        json={"transaction_signature": "3" * 88},
        headers={"X-Webhook-Secret": secret_attempt},
    )
    assert resp.status_code == 401
    data = resp.json()

    assert data["code"] == ErrorCode.UNAUTHORIZED_WEBHOOK.value
    # Secret attempt must never be reflected in client error payload
    assert secret_attempt not in str(data)
