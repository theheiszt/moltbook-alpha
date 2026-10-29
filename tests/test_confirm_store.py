"""
Unit and API integration tests for Machine-Readable Step-Up Authorization Nonces (ConfirmStore).
"""

import time
from starlette.testclient import TestClient

from api_server import app, storage
from ops.security.confirm_store import confirm_store, ConfirmStore


def setup_function():
    confirm_store.clear()
    confirm_store.strict_mode = True


def test_confirm_store_unit_lifecycle():
    store = ConfirmStore(default_ttl_seconds=60.0)
    params = {"unmatched_id": "unm_test_01", "amount": 100}

    # 1. Issue challenge
    chal = store.issue(
        action="REFUND_PAYMENT",
        principal_id="user_alice",
        params=params,
        consequence_summary={"warning": "Permanent debit"},
    )
    assert chal.nonce.startswith("conf_")
    assert chal.action == "REFUND_PAYMENT"
    assert not chal.is_expired()

    # 2. Tampered parameters fail
    tampered_params = {"unmatched_id": "unm_test_01", "amount": 999}
    ok, reason = store.verify_and_consume(
        nonce=chal.nonce,
        action="REFUND_PAYMENT",
        principal_id="user_alice",
        params=tampered_params,
    )
    assert not ok
    assert "fingerprint mismatch" in reason

    # 3. Principal mismatch fails
    ok_p, reason_p = store.verify_and_consume(
        nonce=chal.nonce,
        action="REFUND_PAYMENT",
        principal_id="user_bob",
        params=params,
    )
    assert not ok_p
    assert "fingerprint mismatch" in reason_p

    # 4. Valid consumption succeeds
    ok_valid, reason_valid = store.verify_and_consume(
        nonce=chal.nonce,
        action="REFUND_PAYMENT",
        principal_id="user_alice",
        params=params,
    )
    assert ok_valid
    assert reason_valid == "OK"

    # 5. Replay attempt fails (single-use burned)
    ok_replay, reason_replay = store.verify_and_consume(
        nonce=chal.nonce,
        action="REFUND_PAYMENT",
        principal_id="user_alice",
        params=params,
    )
    assert not ok_replay
    assert "does not exist or was already consumed" in reason_replay


def test_confirm_store_unit_expiration():
    store = ConfirmStore(default_ttl_seconds=0.05)
    params = {"order": 1}
    chal = store.issue("TEST_ACTION", "user_1", params, ttl_seconds=0.05)

    time.sleep(0.06)
    assert chal.is_expired()

    ok, reason = store.verify_and_consume(chal.nonce, "TEST_ACTION", "user_1", params)
    assert not ok
    assert "expired" in reason


def test_api_step_up_challenge_and_redemption_flow():
    client = TestClient(app)
    api_key, _ = storage.create_api_key(tier="standard", credits=100)
    auth_headers = {"x-api-key": api_key}

    # 1. Seed unmatched payments in HELD status
    payer = "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx"
    unm = storage.record_unmatched_payment(
        tx_signature="sig_step_up_test_001",
        payer_wallet=payer,
        rail="solana",
        asset="SOL",
        amount_raw=50_000_000,
        expected_amount_raw=60_000_000,
        reason="STEP_UP_TEST",
    )
    unm_id = unm["unmatched_id"]

    unm2 = storage.record_unmatched_payment(
        tx_signature="sig_step_up_test_002_target",
        payer_wallet=payer,
        rail="solana",
        asset="SOL",
        amount_raw=50_000_000,
        expected_amount_raw=60_000_000,
        reason="STEP_UP_TEST_REPLAY_TARGET",
    )
    unm2_id = unm2["unmatched_id"]

    # 2. Anonymous attempt -> Expect HTTP 401 Unauthorized
    res_anon = client.post(f"/v1/payments/refund/{unm_id}")
    assert res_anon.status_code == 401
    assert res_anon.json()["code"] == "AUTHENTICATION_REQUIRED"

    # 3. Authenticated attempt without nonce in strict mode -> Expect HTTP 428 Precondition Required
    res_chal = client.post(
        f"/v1/payments/refund/{unm_id}",
        headers=auth_headers,
    )
    assert res_chal.status_code == 428
    data_chal = res_chal.json()

    assert data_chal["code"] == "POLICY_CONFIRMATION_REQUIRED"
    assert data_chal["retryable"] is False
    assert data_chal["outcome"] == "not_committed"
    assert data_chal["recovery"]["action"] == "confirm_operation"
    nonce = data_chal["recovery"]["challenge_nonce"]
    assert nonce.startswith("conf_")

    # 4. Confirm with nonce + auth -> Expect HTTP 200 and successful refund
    res_confirm = client.post(
        f"/v1/payments/refund/{unm_id}",
        headers={**auth_headers, "X-Confirmation-Nonce": nonce},
    )
    assert res_confirm.status_code == 200
    data_confirm = res_confirm.json()
    assert data_confirm["success"] is True
    assert data_confirm["status"] == "REFUNDED"
    assert data_confirm["refund_amount_raw"] == 50_000_000 - 5000
    assert data_confirm["state_witness_id"].startswith("wit_")

    # 5. Attempt to replay the burned nonce on another held payment -> Expect HTTP 410 Gone
    res_replay = client.post(
        f"/v1/payments/refund/{unm2_id}",
        headers={**auth_headers, "X-Confirmation-Nonce": nonce},
    )
    assert res_replay.status_code == 410
    data_replay = res_replay.json()
    assert data_replay["code"] == "CONFIRMATION_NONCE_INVALID"
    assert data_replay["outcome"] == "not_committed"


def test_api_explicit_challenge_endpoint():
    client = TestClient(app)
    api_key, _ = storage.create_api_key(tier="standard", credits=100)
    auth_headers = {"x-api-key": api_key}

    # Seed unmatched payment
    payer = "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx"
    unm = storage.record_unmatched_payment(
        tx_signature="sig_step_up_test_003",
        payer_wallet=payer,
        rail="solana",
        asset="SOL",
        amount_raw=25_000_000,
        expected_amount_raw=30_000_000,
        reason="PRE_FLIGHT_CHALLENGE",
    )
    unm_id = unm["unmatched_id"]

    # Anonymous challenge request fails
    res_anon_req = client.post(f"/v1/payments/refund/{unm_id}/challenge")
    assert res_anon_req.status_code == 401
    assert res_anon_req.json()["code"] == "AUTHENTICATION_REQUIRED"

    # Authenticated request challenge via dedicated challenge endpoint
    res_req = client.post(f"/v1/payments/refund/{unm_id}/challenge", headers=auth_headers)
    assert res_req.status_code == 200
    chal_data = res_req.json()
    nonce = chal_data["challenge_nonce"]
    assert chal_data["action"] == "REFUND_PAYMENT"
    assert chal_data["confirm_header"] == "X-Confirmation-Nonce"

    # Redeem challenge
    res_redeem = client.post(
        f"/v1/payments/refund/{unm_id}",
        headers={**auth_headers, "X-Confirmation-Nonce": nonce},
    )
    assert res_redeem.status_code == 200
    assert res_redeem.json()["status"] == "REFUNDED"
