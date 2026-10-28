"""
Tests for Payment Reconciliation Safeguards:
1. Retry of fulfilled invoice with claim_secret returns raw api_key.
2. Underpaid Solana transfer is recorded into unmatched_payments.
3. Asset mismatch Solana transfer is recorded into unmatched_payments.
4. Expired invoice with valid on-chain transfer is recorded into unmatched_payments.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient

from api_server import app, storage
from payment_verifier import VerifiedPayment


def make_unique_sig() -> str:
    # 88 chars valid base58-like string
    token = uuid.uuid4().hex + uuid.uuid4().hex + uuid.uuid4().hex
    return (token[:88]).replace("0", "a").replace("O", "b").replace("I", "c").replace("l", "d")


def test_fulfilled_invoice_retry_with_claim_secret_returns_api_key():
    client = TestClient(app)
    inv_res = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter", "asset": "USDC"})
    assert inv_res.status_code == 200
    inv = inv_res.json()
    invoice_id = inv["invoice_id"]
    claim_secret = inv["claim_secret"]

    fake_sig = make_unique_sig()
    fake_payment = VerifiedPayment(
        tx_signature=fake_sig,
        payer="Payer111111111111111111111111111111111111111",
        recipient=inv["treasury_wallet"],
        amount_raw=1_000_000,
        asset="USDC",
        tier="tier_starter",
        credits=50,
        reference=inv["reference"],
        slot=1000,
        block_time=1700000000,
        rpc_endpoint_used="mock_rpc",
    )

    with patch("payment_verifier.SolanaPaymentVerifier.verify_payment", return_value=fake_payment):
        # First verification
        v1 = client.post(
            "/v1/payments/verify-solana",
            json={
                "transaction_signature": fake_sig,
                "invoice_id": invoice_id,
                "claim_secret": claim_secret,
            },
        )
        assert v1.status_code == 200
        raw_key = v1.json().get("api_key")
        assert raw_key and raw_key.startswith("molt_")

        # Retry verification with same signature and claim_secret
        v2 = client.post(
            "/v1/payments/verify-solana",
            json={
                "transaction_signature": fake_sig,
                "invoice_id": invoice_id,
                "claim_secret": claim_secret,
            },
        )
        assert v2.status_code == 200
        assert v2.json()["success"] is True
        assert v2.json()["api_key"] == raw_key
        assert v2.json()["invoice_id"] == invoice_id


def test_underpaid_solana_transfer_recorded_in_unmatched():
    client = TestClient(app)
    inv_res = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter", "asset": "USDC"})
    assert inv_res.status_code == 200
    inv = inv_res.json()
    invoice_id = inv["invoice_id"]
    claim_secret = inv["claim_secret"]

    fake_sig = make_unique_sig()
    # Underpaid: 500_000 raw USDC instead of 1_000_000
    underpaid_payment = VerifiedPayment(
        tx_signature=fake_sig,
        payer="PayerUnderpaid1111111111111111111111111111111",
        recipient=inv["treasury_wallet"],
        amount_raw=500_000,
        asset="USDC",
        tier="tier_starter",
        credits=50,
        reference=inv["reference"],
        slot=1001,
        block_time=1700000001,
        rpc_endpoint_used="mock_rpc",
    )

    with patch("payment_verifier.SolanaPaymentVerifier.verify_payment", return_value=underpaid_payment):
        res = client.post(
            "/v1/payments/verify-solana",
            json={
                "transaction_signature": fake_sig,
                "invoice_id": invoice_id,
                "claim_secret": claim_secret,
            },
        )
        assert res.status_code == 400
        err = res.json()
        assert "unmatched ledger" in err.get("message", "")
        unm_id = err.get("details", {}).get("unmatched_id")
        assert unm_id and unm_id.startswith("unm_")

        unm_rec = storage.get_unmatched_payment(unm_id)
        assert unm_rec is not None
        assert unm_rec["status"] == "HELD"
        assert unm_rec["amount_raw"] == 500_000
        assert unm_rec["reason"] == "UNDERPAID_AMOUNT"


def test_asset_mismatch_solana_transfer_recorded_in_unmatched():
    client = TestClient(app)
    inv_res = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter", "asset": "USDC"})
    assert inv_res.status_code == 200
    inv = inv_res.json()
    invoice_id = inv["invoice_id"]
    claim_secret = inv["claim_secret"]

    fake_sig = make_unique_sig()
    mismatch_payment = VerifiedPayment(
        tx_signature=fake_sig,
        payer="PayerMismatch1111111111111111111111111111111",
        recipient=inv["treasury_wallet"],
        amount_raw=5_000_000,
        asset="SOL",
        tier="tier_starter",
        credits=50,
        reference=inv["reference"],
        slot=1002,
        block_time=1700000002,
        rpc_endpoint_used="mock_rpc",
    )

    with patch("payment_verifier.SolanaPaymentVerifier.verify_payment", return_value=mismatch_payment):
        res = client.post(
            "/v1/payments/verify-solana",
            json={
                "transaction_signature": fake_sig,
                "invoice_id": invoice_id,
                "claim_secret": claim_secret,
            },
        )
        assert res.status_code == 400
        err = res.json()
        assert "unmatched ledger" in err.get("message", "")
        unm_id = err.get("details", {}).get("unmatched_id")
        assert unm_id and unm_id.startswith("unm_")

        unm_rec = storage.get_unmatched_payment(unm_id)
        assert unm_rec is not None
        assert unm_rec["status"] == "HELD"
        assert "ASSET_MISMATCH" in unm_rec["reason"]


def test_expired_invoice_with_valid_payment_recorded_in_unmatched():
    client = TestClient(app)
    inv_res = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter", "asset": "USDC"})
    assert inv_res.status_code == 200
    inv = inv_res.json()
    invoice_id = inv["invoice_id"]
    claim_secret = inv["claim_secret"]

    # Manually expire invoice in DB
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with storage.connection() as conn:
        with conn:
            conn.execute("UPDATE payment_invoices SET status = 'expired', expires_at = ? WHERE invoice_id = ?", (past_iso, invoice_id))

    fake_sig = make_unique_sig()
    expired_payment = VerifiedPayment(
        tx_signature=fake_sig,
        payer="PayerLate111111111111111111111111111111111",
        recipient=inv["treasury_wallet"],
        amount_raw=1_000_000,
        asset="USDC",
        tier="tier_starter",
        credits=50,
        reference=inv["reference"],
        slot=1003,
        block_time=1700000003,
        rpc_endpoint_used="mock_rpc",
    )

    with patch("payment_verifier.SolanaPaymentVerifier.verify_payment", return_value=expired_payment):
        res = client.post(
            "/v1/payments/verify-solana",
            json={
                "transaction_signature": fake_sig,
                "invoice_id": invoice_id,
                "claim_secret": claim_secret,
            },
        )
        assert res.status_code == 400
        err = res.json()
        assert "unmatched ledger" in err.get("message", "")
        unm_id = err.get("details", {}).get("unmatched_id")
        assert unm_id and unm_id.startswith("unm_")

        unm_rec = storage.get_unmatched_payment(unm_id)
        assert unm_rec is not None
        assert unm_rec["status"] == "HELD"
        assert unm_rec["reason"] == "EXPIRED_INVOICE_PAID"
