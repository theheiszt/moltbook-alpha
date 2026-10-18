"""
Comprehensive automated tests for Machine-Readable Error Contract:
- Verification challenge semantics (WRONG_ANSWER, CHALLENGE_EXPIRED, CHALLENGE_CONSUMED,
  CHALLENGE_ALREADY_ANSWERED, CHALLENGE_NOT_FOUND, no secret leakage).
- Payment redemption hardening (single credit grant, idempotent replay, cross-invoice
  signature reuse rejection, cross-account reuse rejection, atomic boundary consistency,
  indeterminate RPC error handling).
- Contract-wide schema validation & Python SDK exception mapping.
"""

import secrets
import threading
from unittest.mock import patch
from fastapi.testclient import TestClient

from api_server import app, storage, rate_limiter
from errors import (
    ErrorCode,
    OperationOutcome,
    RecoveryAction,
    ERROR_REGISTRY,
)
from payment_verifier import VerifiedPayment, RPCError, VerificationError
from sdk.moltbook_intel.exceptions import (
    raise_for_error_payload,
    WrongAnswerError,
    ChallengeExpiredError,
    ChallengeConsumedError,
    ChallengeAlreadyAnsweredError,
    ChallengeNotFoundError,
    DuplicatePaymentReuseError,
    RpcGatewayError,
)


# ==============================================================================
# STAGE 3: VERIFICATION CHALLENGE TESTS
# ==============================================================================

def test_challenge_creation_and_no_secret_disclosure():
    client = TestClient(app)
    resp = client.post("/v1/challenges", json={"challenge_type": "arithmetic", "expiry_seconds": 120})
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is True
    assert "challenge_id" in data
    assert data["challenge_id"].startswith("ch_")
    assert "challenge_text" in data
    assert data["status"] == "pending"
    assert "expires_at" in data
    assert "created_at" in data

    # Verify that expected answer and hashes are NEVER exposed
    assert "expected_answer" not in data
    assert "expected_answer_hash" not in data
    assert "answer" not in data

    # Check status endpoint also shields secrets
    status_resp = client.get(f"/v1/challenges/{data['challenge_id']}")
    assert status_resp.status_code == 200
    st_data = status_resp.json()
    assert "expected_answer" not in st_data
    assert "expected_answer_hash" not in st_data


def test_challenge_wrong_answer_consumes_challenge():
    client = TestClient(app)
    # Create challenge with fixed question and answer
    ch = storage.create_verification_challenge(
        challenge_type="arithmetic",
        challenge_text="Calculate 25 plus 15 to verify.",
        expected_answer="40.00",
        expiry_seconds=120,
    )
    cid = ch["challenge_id"]

    # Submit WRONG answer
    resp = client.post("/v1/challenges/verify", json={"challenge_id": cid, "answer": "999.00"})
    assert resp.status_code == 400
    data = resp.json()

    # Verify shared error contract
    assert "error" in data
    err_sub = data["error"]
    assert err_sub["code"] == ErrorCode.WRONG_ANSWER.value
    assert err_sub["retryable"] is False
    assert err_sub["outcome"] == OperationOutcome.NOT_COMMITTED.value
    assert err_sub["state_effect"] == "challenge_consumed"
    assert err_sub["recovery"]["action"] == RecoveryAction.REQUEST_NEW_CHALLENGE.value
    assert "request_id" in err_sub

    # Root fields mirror contract
    assert data["code"] == ErrorCode.WRONG_ANSWER.value
    assert data["retryable"] is False
    assert data["outcome"] == OperationOutcome.NOT_COMMITTED.value
    assert data["state_effect"] == "challenge_consumed"
    assert data["recovery"]["action"] == RecoveryAction.REQUEST_NEW_CHALLENGE.value

    # Verify that challenge in DB has transitioned to consumed
    db_record = storage.get_verification_challenge(cid)
    assert db_record["status"] == "consumed"
    assert db_record["attempts"] == 1

    # Second attempt on consumed challenge returns CHALLENGE_CONSUMED
    second_resp = client.post("/v1/challenges/verify", json={"challenge_id": cid, "answer": "40.00"})
    assert second_resp.status_code == 410
    sec_data = second_resp.json()
    assert sec_data["error"]["code"] == ErrorCode.CHALLENGE_CONSUMED.value
    assert sec_data["error"]["retryable"] is False
    assert sec_data["error"]["outcome"] == OperationOutcome.NOT_COMMITTED.value
    assert sec_data["error"]["state_effect"] == "challenge_consumed"
    assert sec_data["error"]["recovery"]["action"] == RecoveryAction.REQUEST_NEW_CHALLENGE.value


def test_challenge_expired_semantics():
    client = TestClient(app)
    # Create challenge with 0s TTL (already expired)
    ch = storage.create_verification_challenge(
        challenge_type="arithmetic",
        challenge_text="Calculate 10 plus 10 to verify.",
        expected_answer="20.00",
        expiry_seconds=-10,
    )
    cid = ch["challenge_id"]

    resp = client.post("/v1/challenges/verify", json={"challenge_id": cid, "answer": "20.00"})
    assert resp.status_code == 410
    data = resp.json()

    assert data["error"]["code"] == ErrorCode.CHALLENGE_EXPIRED.value
    assert data["error"]["retryable"] is False
    assert data["error"]["outcome"] == OperationOutcome.NOT_COMMITTED.value
    assert data["error"]["recovery"]["action"] == RecoveryAction.REQUEST_NEW_CHALLENGE.value


def test_challenge_already_answered_and_idempotent_proof_recovery():
    client = TestClient(app)
    ch = storage.create_verification_challenge(
        challenge_type="arithmetic",
        challenge_text="Calculate 14 plus 16 to verify.",
        expected_answer="30.00",
        expiry_seconds=120,
    )
    cid = ch["challenge_id"]

    # 1. Correct submission succeeds
    resp1 = client.post("/v1/challenges/verify", json={"challenge_id": cid, "answer": "30.00"})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["success"] is True
    assert data1["status"] == "solved"
    proof = data1["proof_token"]
    assert proof.startswith("proof_")

    # 2. Resubmission of solved challenge returns CHALLENGE_ALREADY_ANSWERED (409 Conflict)
    # with retrieve_existing_result and the prior proof_token
    resp2 = client.post("/v1/challenges/verify", json={"challenge_id": cid, "answer": "30.00"})
    assert resp2.status_code == 409
    data2 = resp2.json()

    assert data2["error"]["code"] == ErrorCode.CHALLENGE_ALREADY_ANSWERED.value
    assert data2["error"]["retryable"] is False
    assert data2["error"]["outcome"] == OperationOutcome.COMMITTED.value
    assert data2["error"]["state_effect"] == "none"
    assert data2["error"]["recovery"]["action"] == RecoveryAction.RETRIEVE_EXISTING_RESULT.value
    assert data2["details"]["proof_token"] == proof


def test_challenge_not_found():
    client = TestClient(app)
    resp = client.post("/v1/challenges/verify", json={"challenge_id": "ch_does_not_exist_9999", "answer": "42.00"})
    assert resp.status_code == 404
    data = resp.json()

    assert data["error"]["code"] == ErrorCode.CHALLENGE_NOT_FOUND.value
    assert data["error"]["retryable"] is False
    assert data["error"]["outcome"] == OperationOutcome.NOT_COMMITTED.value
    assert data["error"]["recovery"]["action"] == RecoveryAction.REQUEST_NEW_CHALLENGE.value


# ==============================================================================
# STAGE 4: PAYMENT REDEMPTION & CREDIT HARDENING TESTS
# ==============================================================================

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def make_sig() -> str:
    prefix = "5wHu1qwLq7Xg5WpS1Gv7nJ8cK3L9bM2rT4vN6pQ8sY1xZ3aB5cD7eF9gH2jK4mN6pQ8sY1xZ3aB5cD"
    suffix = "".join(secrets.choice(BASE58_ALPHABET) for _ in range(8))
    return f"{prefix}{suffix}"


def test_payment_redemption_exact_once_and_idempotent_replay():
    client = TestClient(app)
    sig = make_sig()

    # Create invoice
    inv_resp = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter", "asset": "USDC"})
    assert inv_resp.status_code == 200
    inv = inv_resp.json()
    inv_id = inv["invoice_id"]
    claim_sec = inv["claim_secret"]

    fake_payment = VerifiedPayment(
        tx_signature=sig,
        asset="USDC",
        amount_raw=inv["amount_raw"],
        tier="starter",
        credits=10,
        recipient=inv["treasury_wallet"],
        payer="PayerWallet1111111111111111111111111111111111",
        reference=inv["reference"],
        slot=100000,
        block_time=1700000000,
        rpc_endpoint_used="mock_solana_rpc",
    )

    with patch("api_server.SolanaPaymentVerifier.verify_payment", return_value=fake_payment):
        # First redemption: mints credits
        resp1 = client.post("/v1/payments/verify-solana", json={
            "transaction_signature": sig,
            "invoice_id": inv_id,
            "claim_secret": claim_sec,
        })
        assert resp1.status_code == 200
        d1 = resp1.json()
        assert d1["success"] is True
        assert d1["status"] == "newly_minted"
        assert d1["credits"] == 10
        raw_api_key = d1["api_key"]

        # Check DB consistency: exactly 1 redemption, 1 invoice fulfilled, 1 lot
        redemption = storage.get_payment_redemption(sig)
        assert redemption is not None
        assert redemption["invoice_id"] == inv_id
        assert redemption["credits_granted"] == 10

        inv_record = storage.get_invoice(inv_id)
        assert inv_record["status"] == "fulfilled"
        assert inv_record["tx_signature"] == sig

        # Second redemption with same signature and invoice (idempotent replay)
        resp2 = client.post("/v1/payments/verify-solana", json={
            "transaction_signature": sig,
            "invoice_id": inv_id,
            "claim_secret": claim_sec,
        })
        assert resp2.status_code == 200
        d2 = resp2.json()
        assert d2["success"] is True
        assert "previously redeemed" in d2["message"].lower()
        assert d2["key_prefix"] == redemption["key_prefix"]

        # Credited account did NOT double-credit
        key_info = storage.get_key_info(raw_api_key)
        assert key_info["credits"] == 10


def test_cross_invoice_signature_reuse_rejected():
    client = TestClient(app)
    sig = make_sig()

    # Create Invoice 1 and fulfill it
    inv1_resp = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter", "asset": "USDC"})
    inv1 = inv1_resp.json()
    inv1_id = inv1["invoice_id"]

    fake_payment = VerifiedPayment(
        tx_signature=sig,
        asset="USDC",
        amount_raw=inv1["amount_raw"],
        tier="starter",
        credits=10,
        recipient=inv1["treasury_wallet"],
        payer="PayerWallet1111111111111111111111111111111111",
        reference=inv1["reference"],
        slot=100000,
        block_time=1700000000,
        rpc_endpoint_used="mock_solana_rpc",
    )

    with patch("api_server.SolanaPaymentVerifier.verify_payment", return_value=fake_payment):
        resp1 = client.post("/v1/payments/verify-solana", json={
            "transaction_signature": sig,
            "invoice_id": inv1_id,
            "claim_secret": inv1["claim_secret"],
        })
        assert resp1.status_code == 200

        # Create Invoice 2
        inv2_resp = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter", "asset": "USDC"})
        inv2 = inv2_resp.json()
        inv2_id = inv2["invoice_id"]

        # Attempt to redeem Invoice 2 with the SAME signature used for Invoice 1
        resp2 = client.post("/v1/payments/verify-solana", json={
            "transaction_signature": sig,
            "invoice_id": inv2_id,
            "claim_secret": inv2["claim_secret"],
        })

        assert resp2.status_code == 409
        data2 = resp2.json()
        assert data2["error"]["code"] == ErrorCode.DUPLICATE_PAYMENT_REUSE.value
        assert data2["error"]["retryable"] is False
        assert data2["error"]["outcome"] == OperationOutcome.NOT_COMMITTED.value
        assert data2["error"]["state_effect"] == "none"
        assert data2["error"]["recovery"]["action"] == RecoveryAction.CREATE_NEW_INVOICE.value

        # Invoice 2 must remain pending and unfulfilled
        inv2_record = storage.get_invoice(inv2_id)
        assert inv2_record["status"] == "pending"


def test_cross_account_signature_reuse_rejected():
    client = TestClient(app)
    sig = make_sig()

    # Create key 1 and key 2
    raw_key1, rec1 = storage.create_api_key(tier="starter", credits=5)
    raw_key2, rec2 = storage.create_api_key(tier="starter", credits=5)

    # Create invoice targeted at key 1
    inv1_resp = client.post("/v1/payments/invoice", json={
        "target_tier": "topup_500",
        "asset": "USDC",
        "target_api_key": raw_key1,
    })
    assert inv1_resp.status_code == 200
    inv1 = inv1_resp.json()
    inv1_id = inv1["invoice_id"]

    fake_payment = VerifiedPayment(
        tx_signature=sig,
        asset="USDC",
        amount_raw=inv1["amount_raw"],
        tier="topup_500",
        credits=500,
        recipient=inv1["treasury_wallet"],
        payer="PayerWallet1111111111111111111111111111111111",
        reference=inv1["reference"],
        slot=100000,
        block_time=1700000000,
        rpc_endpoint_used="mock_solana_rpc",
    )

    with patch("api_server.SolanaPaymentVerifier.verify_payment", return_value=fake_payment):
        # Redeem invoice 1
        r1 = client.post("/v1/payments/verify-solana", json={
            "transaction_signature": sig,
            "invoice_id": inv1_id,
        })
        assert r1.status_code == 200

        # Create invoice 2 targeted at key 2
        inv2_resp = client.post("/v1/payments/invoice", json={
            "target_tier": "topup_500",
            "asset": "USDC",
            "target_api_key": raw_key2,
        })
        assert inv2_resp.status_code == 200
        inv2 = inv2_resp.json()
        inv2_id = inv2["invoice_id"]

        # Attempt to redeem invoice 2 with sig from invoice 1
        r2 = client.post("/v1/payments/verify-solana", json={
            "transaction_signature": sig,
            "invoice_id": inv2_id,
        })
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == ErrorCode.DUPLICATE_PAYMENT_REUSE.value

        # Verify key 2 balance did NOT change
        k2_info = storage.get_key_info(raw_key2)
        assert k2_info["credits"] == 5


def test_concurrent_redemption_atomic_boundary():
    sig = make_sig()
    inv_record, sec, ref = storage.create_invoice(
        tier="starter",
        credits=10,
        asset="USDC",
        amount_raw=5000000,
        recipient="Treasury1111111111111111111111111111111111",
    )
    inv_id = inv_record["invoice_id"]

    results = []
    errors = []

    def run_fulfill():
        try:
            res = storage.fulfill_invoice_and_redeem(
                invoice_id=inv_id,
                tx_signature=sig,
                asset="USDC",
                amount_raw=5000000,
                tier="starter",
                credits_to_grant=10,
                claim_secret=sec,
            )
            results.append(res)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=run_fulfill) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Zero exceptions
    assert len(errors) == 0
    assert len(results) == 5

    # Exactly one newly minted, remainder already_redeemed
    minted_count = sum(1 for r in results if r["status"] == "newly_minted")
    already_count = sum(1 for r in results if r["status"] == "already_redeemed")
    assert minted_count == 1
    assert already_count == 4


def test_rpc_gateway_indeterminate_outcome_semantics():
    client = TestClient(app)
    sig = make_sig()

    inv_resp = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter", "asset": "USDC"})
    inv = inv_resp.json()

    with patch("api_server.SolanaPaymentVerifier.verify_payment", side_effect=RPCError("RPC timeout connecting to Solana node")):
        resp = client.post("/v1/payments/verify-solana", json={
            "transaction_signature": sig,
            "invoice_id": inv["invoice_id"],
            "claim_secret": inv["claim_secret"],
        })
        assert resp.status_code == 502
        data = resp.json()

        assert data["error"]["code"] == ErrorCode.RPC_GATEWAY_ERROR.value
        assert data["error"]["retryable"] is True
        assert data["error"]["outcome"] == OperationOutcome.INDETERMINATE.value
        assert data["error"]["state_effect"] == "none"
        assert data["error"]["recovery"]["action"] == RecoveryAction.POLL_PAYMENT_STATUS.value
        assert data["error"]["retry_after_seconds"] == 5

        # Check invoice remains pending
        inv_record = storage.get_invoice(inv["invoice_id"])
        assert inv_record["status"] == "pending"


# ==============================================================================
# STAGE 5: CONTRACT-WIDE SCHEMA & SDK TESTS
# ==============================================================================

def test_contract_wide_error_registry_and_schema():
    client = TestClient(app)
    resp = client.get("/v1/errors")
    assert resp.status_code == 200
    data = resp.json()

    assert data["version"] in ("1.0.0", "2.0.0")
    errors = data["errors"]

    allowed_outcomes = {o.value for o in OperationOutcome}
    allowed_actions = {a.value for a in RecoveryAction}

    for code, defn in errors.items():
        assert "code" in defn
        assert "status_code" in defn
        assert 400 <= defn["status_code"] <= 599
        assert isinstance(defn["retryable"], bool)
        assert defn["outcome"] in allowed_outcomes
        assert isinstance(defn["state_effect"], str)
        assert defn["recovery_action"] in allowed_actions
        assert "docs_url" in defn

    # Check specific challenge and payment error codes
    assert ErrorCode.WRONG_ANSWER.value in errors
    assert ErrorCode.CHALLENGE_EXPIRED.value in errors
    assert ErrorCode.CHALLENGE_CONSUMED.value in errors
    assert ErrorCode.CHALLENGE_ALREADY_ANSWERED.value in errors
    assert ErrorCode.CHALLENGE_NOT_FOUND.value in errors
    assert ErrorCode.DUPLICATE_PAYMENT_REUSE.value in errors


def test_python_sdk_exception_mapping():
    # 1. WrongAnswerError
    payload_wrong = {
        "error": {
            "code": "WRONG_ANSWER",
            "message": "Challenge answer is incorrect.",
            "retryable": False,
            "outcome": "not_committed",
            "state_effect": "challenge_consumed",
            "recovery": {"action": "request_new_challenge"},
            "request_id": "req_sdk_01",
        }
    }
    try:
        raise_for_error_payload(400, payload_wrong)
        assert False, "Should have raised WrongAnswerError"
    except WrongAnswerError as e:
        assert e.code == "WRONG_ANSWER"
        assert e.outcome == "not_committed"
        assert e.state_effect == "challenge_consumed"
        assert e.recovery_action == "request_new_challenge"
        assert e.retryable is False

    # 2. ChallengeAlreadyAnsweredError
    payload_answered = {
        "error": {
            "code": "CHALLENGE_ALREADY_ANSWERED",
            "message": "Challenge already solved.",
            "retryable": False,
            "outcome": "committed",
            "state_effect": "none",
            "recovery": {"action": "retrieve_existing_result"},
            "request_id": "req_sdk_02",
        }
    }
    try:
        raise_for_error_payload(409, payload_answered)
        assert False, "Should have raised ChallengeAlreadyAnsweredError"
    except ChallengeAlreadyAnsweredError as e:
        assert e.code == "CHALLENGE_ALREADY_ANSWERED"
        assert e.outcome == "committed"
        assert e.recovery_action == "retrieve_existing_result"

    # 3. DuplicatePaymentReuseError
    payload_dup = {
        "error": {
            "code": "DUPLICATE_PAYMENT_REUSE",
            "message": "Signature already redeemed for different invoice.",
            "retryable": False,
            "outcome": "not_committed",
            "state_effect": "none",
            "recovery": {"action": "create_new_invoice"},
            "request_id": "req_sdk_03",
        }
    }
    try:
        raise_for_error_payload(409, payload_dup)
        assert False, "Should have raised DuplicatePaymentReuseError"
    except DuplicatePaymentReuseError as e:
        assert e.code == "DUPLICATE_PAYMENT_REUSE"
        assert e.outcome == "not_committed"
        assert e.recovery_action == "create_new_invoice"

    # 4. RpcGatewayError
    payload_rpc = {
        "error": {
            "code": "RPC_GATEWAY_ERROR",
            "message": "Solana RPC timeout.",
            "retryable": True,
            "outcome": "indeterminate",
            "state_effect": "none",
            "recovery": {"action": "poll_payment_status"},
            "retry_after_seconds": 5,
            "request_id": "req_sdk_04",
        }
    }
    try:
        raise_for_error_payload(502, payload_rpc)
        assert False, "Should have raised RpcGatewayError"
    except RpcGatewayError as e:
        assert e.code == "RPC_GATEWAY_ERROR"
        assert e.retryable is True
        assert e.outcome == "indeterminate"
        assert e.recovery_action == "poll_payment_status"
        assert e.retry_after == 5
