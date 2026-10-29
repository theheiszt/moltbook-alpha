"""
Regression and Security Verification Tests for Moltbook Alpha Payments Refund Pipeline.

Validates:
1. Mandatory authentication on POST /v1/payments/refund/{unmatched_id} (rejects anonymous with HTTP 401).
2. Mandatory authentication on POST /v1/payments/refund/{unmatched_id}/challenge (HTTP 401).
3. Fail-closed step-up confirmation enforcement (strict_mode=True returns HTTP 428 Precondition Required).
4. Nonce binding: action, principal_id, and parameter fingerprinting prevents cross-resource replay (HTTP 410).
5. Single-use nonce burning: replay attempts on another held resource fail (HTTP 410).
6. Admin privileges: unauthorized callers cannot forge X-Admin-Bypass-Confirmation without admin credentials.
7. Authorized admin bypass: valid admin session/key + bypass header executes without challenge.
8. Cryptographic audit trail: successful refund creates Ed25519 state witness and state audit record.
"""

from fastapi.testclient import TestClient

from api_server import app, storage
from ops.security.confirm_store import confirm_store


def setup_function():
    confirm_store.clear()
    confirm_store.strict_mode = True


def test_anonymous_refund_rejected_with_401():
    client = TestClient(app)
    unm = storage.record_unmatched_payment(
        tx_signature="sig_anon_test_001",
        payer_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        rail="solana",
        asset="SOL",
        amount_raw=10_000_000,
        expected_amount_raw=20_000_000,
        reason="ANON_TEST",
    )
    unm_id = unm["unmatched_id"]

    res = client.post(f"/v1/payments/refund/{unm_id}")
    assert res.status_code == 401
    data = res.json()
    assert data["code"] == "AUTHENTICATION_REQUIRED"
    assert data["outcome"] == "not_committed"
    assert data["retryable"] is False
    assert "WWW-Authenticate" in res.headers


def test_anonymous_challenge_request_rejected_with_401():
    client = TestClient(app)
    unm = storage.record_unmatched_payment(
        tx_signature="sig_anon_test_002",
        payer_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        rail="solana",
        asset="SOL",
        amount_raw=10_000_000,
        expected_amount_raw=20_000_000,
        reason="ANON_CHALLENGE_TEST",
    )
    unm_id = unm["unmatched_id"]

    res = client.post(f"/v1/payments/refund/{unm_id}/challenge")
    assert res.status_code == 401
    data = res.json()
    assert data["code"] == "AUTHENTICATION_REQUIRED"


def test_authenticated_standard_user_receives_428_step_up_challenge():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="standard", credits=50)

    unm = storage.record_unmatched_payment(
        tx_signature="sig_step_up_test_001",
        payer_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        rail="solana",
        asset="SOL",
        amount_raw=30_000_000,
        expected_amount_raw=40_000_000,
        reason="STEP_UP_CHALLENGE_TEST",
    )
    unm_id = unm["unmatched_id"]

    # Initial POST without nonce triggers HTTP 428
    res = client.post(f"/v1/payments/refund/{unm_id}", headers={"x-api-key": raw_key})
    assert res.status_code == 428
    data = res.json()
    assert data["code"] == "POLICY_CONFIRMATION_REQUIRED"
    assert data["retryable"] is False
    assert data["outcome"] == "not_committed"
    assert data["recovery"]["action"] == "confirm_operation"
    assert "challenge_nonce" in data["recovery"]
    nonce = data["recovery"]["challenge_nonce"]
    assert nonce.startswith("conf_")

    # Complete refund with nonce
    res_confirm = client.post(
        f"/v1/payments/refund/{unm_id}",
        headers={"x-api-key": raw_key, "X-Confirmation-Nonce": nonce},
    )
    assert res_confirm.status_code == 200
    res_data = res_confirm.json()
    assert res_data["success"] is True
    assert res_data["status"] == "REFUNDED"
    assert res_data["refund_amount_raw"] == 30_000_000 - 5000
    assert res_data["state_witness_id"].startswith("wit_")
    assert res_data["witness_signature"]


def test_standard_user_cannot_bypass_confirmation_with_admin_header():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="standard", credits=50)

    unm = storage.record_unmatched_payment(
        tx_signature="sig_bypass_tamper_001",
        payer_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        rail="solana",
        asset="SOL",
        amount_raw=20_000_000,
        expected_amount_raw=25_000_000,
        reason="TAMPER_BYPASS_TEST",
    )
    unm_id = unm["unmatched_id"]

    # Header X-Admin-Bypass-Confirmation without admin identity MUST be ignored and return 428
    res = client.post(
        f"/v1/payments/refund/{unm_id}",
        headers={"x-api-key": raw_key, "X-Admin-Bypass-Confirmation": "true"},
    )
    assert res.status_code == 428
    assert res.json()["code"] == "POLICY_CONFIRMATION_REQUIRED"


def test_admin_bypass_confirmation_succeeds_directly():
    client = TestClient(app)
    admin_key, _ = storage.create_api_key(tier="admin", credits=1000)

    unm = storage.record_unmatched_payment(
        tx_signature="sig_admin_bypass_001",
        payer_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        rail="solana",
        asset="SOL",
        amount_raw=15_000_000,
        expected_amount_raw=20_000_000,
        reason="ADMIN_BYPASS_TEST",
    )
    unm_id = unm["unmatched_id"]

    res = client.post(
        f"/v1/payments/refund/{unm_id}",
        headers={"x-api-key": admin_key, "X-Admin-Bypass-Confirmation": "true"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "REFUNDED"
    assert res.json()["success"] is True


def test_nonce_replay_and_cross_resource_tampering_rejected():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="standard", credits=50)

    unm1 = storage.record_unmatched_payment(
        tx_signature="sig_nonce_tamper_001",
        payer_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        rail="solana",
        asset="SOL",
        amount_raw=12_000_000,
        expected_amount_raw=15_000_000,
        reason="NONCE_TAMPER_1",
    )
    unm2 = storage.record_unmatched_payment(
        tx_signature="sig_nonce_tamper_002",
        payer_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        rail="solana",
        asset="SOL",
        amount_raw=12_000_000,
        expected_amount_raw=15_000_000,
        reason="NONCE_TAMPER_2",
    )
    unm3 = storage.record_unmatched_payment(
        tx_signature="sig_nonce_tamper_003",
        payer_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        rail="solana",
        asset="SOL",
        amount_raw=12_000_000,
        expected_amount_raw=15_000_000,
        reason="NONCE_TAMPER_3",
    )

    # Challenge for unm1
    res1 = client.post(f"/v1/payments/refund/{unm1['unmatched_id']}", headers={"x-api-key": raw_key})
    assert res1.status_code == 428
    nonce1 = res1.json()["recovery"]["challenge_nonce"]

    # Attempt to consume nonce1 against unm2 -> 410 (fingerprint mismatch)
    res_tamper = client.post(
        f"/v1/payments/refund/{unm2['unmatched_id']}",
        headers={"x-api-key": raw_key, "X-Confirmation-Nonce": nonce1},
    )
    assert res_tamper.status_code == 410
    assert res_tamper.json()["code"] == "CONFIRMATION_NONCE_INVALID"

    # Consume on unm1 successfully
    res_ok = client.post(
        f"/v1/payments/refund/{unm1['unmatched_id']}",
        headers={"x-api-key": raw_key, "X-Confirmation-Nonce": nonce1},
    )
    assert res_ok.status_code == 200

    # Attempt to replay already consumed nonce1 on unm3 -> 410 (burned nonce)
    res_replay = client.post(
        f"/v1/payments/refund/{unm3['unmatched_id']}",
        headers={"x-api-key": raw_key, "X-Confirmation-Nonce": nonce1},
    )
    assert res_replay.status_code == 410
    assert res_replay.json()["code"] == "CONFIRMATION_NONCE_INVALID"

    # Attempt to call refund again on already-refunded unm1 -> 400 Bad Request
    res_already_refunded = client.post(
        f"/v1/payments/refund/{unm1['unmatched_id']}",
        headers={"x-api-key": raw_key},
    )
    assert res_already_refunded.status_code == 400
