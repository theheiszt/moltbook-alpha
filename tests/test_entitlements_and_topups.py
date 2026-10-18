"""
Comprehensive Tests for 30-Day Premium Entitlements, 90-Day Credit Top-Ups,
Earliest-Expiration Deduction (EDF), Failure Refunds, and Ledger Balance Auditing.
"""

import tempfile
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi.testclient import TestClient

from storage import StorageManager
from api_server import app, storage as api_storage


def test_premium_initialization_10k_allowance():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(Path(tmpdir) / "test.db")
        raw_key, record = storage.create_api_key(tier="premium", credits=10000, prefix_tag="molt_prem")

        assert record["tier"] == "premium"
        assert record["credits"] == 10000
        assert record["expires_at"] is not None

        # Verify entitlement record
        quota = storage.get_key_quota_details(raw_key)
        assert quota is not None
        assert quota["tier"] == "premium"
        assert quota["credits_remaining"] == 10000
        assert quota["entitlement"]["status"] == "active"
        assert quota["entitlement"]["tier"] == "premium"
        assert 29.0 <= quota["entitlement"]["days_remaining"] <= 30.0

        # Verify credit lot
        assert len(quota["credit_lots"]) == 1
        lot = quota["credit_lots"][0]
        assert lot["lot_type"] == "allowance"
        assert lot["credits_granted"] == 10000
        assert lot["credits_remaining"] == 10000
        assert lot["status"] == "active"

        # Verify ledger balance
        audit = storage.verify_ledger_balance(record["key_hash"])
        assert audit["balanced"] is True
        assert audit["expected_balance"] == 10000
        assert audit["actual_lot_balance"] == 10000


def test_premium_30_day_expiration_and_cutoff():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(Path(tmpdir) / "test.db")
        start_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        storage.set_clock(start_time)

        raw_key, record = storage.create_api_key(tier="premium", credits=10000)

        # Day 15: Halfway through, deduction succeeds
        storage.set_clock(start_time + timedelta(days=15))
        user_info, state = storage.authenticate_and_deduct(raw_key)
        assert state == "ok"
        assert user_info["credits"] == 9999

        quota = storage.get_key_quota_details(raw_key)
        assert quota["entitlement"]["status"] == "active"
        assert 14.0 <= quota["entitlement"]["days_remaining"] <= 15.1

        # Day 30 + 1 hour: Expired!
        storage.set_clock(start_time + timedelta(days=30, hours=1))
        user_info2, state2 = storage.authenticate_and_deduct(raw_key)
        assert state2 == "entitlement_expired"

        quota_expired = storage.get_key_quota_details(raw_key)
        assert quota_expired["entitlement"]["status"] == "expired"
        assert quota_expired["entitlement"]["days_remaining"] == 0.0
        # Allowance lot has expired
        assert quota_expired["credits_remaining"] == 0

        # Verify ledger balance reflects expired allowance
        audit = storage.verify_ledger_balance(record["key_hash"])
        assert audit["balanced"] is True
        assert audit["actual_lot_balance"] == 0
        assert audit["breakdown"]["expired"] == 9999

        storage.reset_clock()


def test_premium_exhaustion_before_expiration():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(Path(tmpdir) / "test.db")
        # Create key with 2 credits for test
        raw_key, _ = storage.create_api_key(tier="premium", credits=2)

        _, s1 = storage.authenticate_and_deduct(raw_key)
        assert s1 == "ok"

        _, s2 = storage.authenticate_and_deduct(raw_key)
        assert s2 == "ok"

        _, s3 = storage.authenticate_and_deduct(raw_key)
        assert s3 == "exhausted"

        key_info = storage.get_key_info(raw_key)
        assert key_info["credits"] == 0


def test_topup_90_day_shelf_life_and_survival_across_premium_expiration():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(Path(tmpdir) / "test.db")
        start_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        storage.set_clock(start_time)

        # 1. User starts with Premium (10,000 queries)
        raw_key, record = storage.create_api_key(tier="premium", credits=10000)
        k_hash = record["key_hash"]

        # 2. User buys a 500-credit topup lot (90 days)
        topup_res = storage.grant_topup(k_hash, credits=500, validity_days=90)
        assert topup_res["credits_granted"] == 500
        assert topup_res["total_credits"] == 10500

        # Total balance is 10,500
        quota = storage.get_key_quota_details(raw_key)
        assert quota["credits_remaining"] == 10500
        assert len(quota["credit_lots"]) == 2

        # 3. Advance to Day 31: Premium expires!
        storage.set_clock(start_time + timedelta(days=31))

        # Attempt to use API: rejected with entitlement_expired
        _, state = storage.authenticate_and_deduct(raw_key)
        assert state == "entitlement_expired"

        # Check quota at Day 31:
        # Allowance lot (10,000) expired, but top-up lot (500) survives!
        quota_d31 = storage.get_key_quota_details(raw_key)
        assert quota_d31["entitlement"]["status"] == "expired"
        assert quota_d31["credits_remaining"] == 500
        assert len(quota_d31["credit_lots"]) == 1
        assert quota_d31["credit_lots"][0]["lot_type"] == "topup"
        assert quota_d31["credit_lots"][0]["credits_remaining"] == 500

        # 4. On Day 35, user renews Premium!
        storage.set_clock(start_time + timedelta(days=35))
        renew_res = storage.renew_entitlement(k_hash, tier="premium", credits=10000, validity_days=30)
        assert renew_res["credits_granted"] == 10000
        # Total is now 10,000 new allowance + 500 preserved topup = 10,500
        assert renew_res["total_credits"] == 10500

        # 5. User can spend again!
        user_info, state_renewed = storage.authenticate_and_deduct(raw_key)
        assert state_renewed == "ok"
        assert user_info["credits"] == 10499

        # Verify ledger balance holds
        audit = storage.verify_ledger_balance(k_hash)
        assert audit["balanced"] is True
        assert audit["actual_lot_balance"] == 10499

        storage.reset_clock()


def test_earliest_deadline_first_deduction_order():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(Path(tmpdir) / "test.db")
        start_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        storage.set_clock(start_time)

        # Create starter key (non-expiring, 10 credits)
        raw_key, record = storage.create_api_key(tier="starter", credits=10)
        k_hash = record["key_hash"]

        # Grant Lot A: expires in 5 days (3 credits)
        lot_a = storage.grant_topup(k_hash, credits=3, validity_days=5)

        # Grant Lot B: expires in 60 days (4 credits)
        lot_b = storage.grant_topup(k_hash, credits=4, validity_days=60)

        # Total credits: 10 (non-expiring) + 3 (5d) + 4 (60d) = 17 credits
        quota = storage.get_key_quota_details(raw_key)
        assert quota["credits_remaining"] == 17

        # EDF rule: Lot A (5d) expires before Lot B (60d), which expires before non-expiring (None).
        # First 3 deductions must consume Lot A
        for i in range(3):
            info, s = storage.authenticate_and_deduct(raw_key)
            assert s == "ok"
            assert info["lot_id"] == lot_a["lot_id"]

        # 4th deduction must consume from Lot B
        info4, s4 = storage.authenticate_and_deduct(raw_key)
        assert s4 == "ok"
        assert info4["lot_id"] == lot_b["lot_id"]

        # Next 3 deductions consume remainder of Lot B (total 4 consumed from Lot B)
        for _ in range(3):
            info, s = storage.authenticate_and_deduct(raw_key)
            assert s == "ok"
            assert info["lot_id"] == lot_b["lot_id"]

        # 8th deduction must fall back to non-expiring starter lot
        info8, s8 = storage.authenticate_and_deduct(raw_key)
        assert s8 == "ok"
        assert info8["lot_id"] != lot_a["lot_id"]
        assert info8["lot_id"] != lot_b["lot_id"]

        # Verify ledger
        audit = storage.verify_ledger_balance(k_hash)
        assert audit["balanced"] is True
        assert audit["actual_lot_balance"] == 9  # 17 - 8 = 9

        storage.reset_clock()


def test_failure_refund_restores_credit_and_balances_ledger():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(Path(tmpdir) / "test.db")
        raw_key, record = storage.create_api_key(tier="pro", credits=50)
        k_hash = record["key_hash"]

        # 1. Deduct 1 credit for a request
        req_id = "req_test_12345"
        user_info, state = storage.authenticate_and_deduct(raw_key, request_id=req_id)
        assert state == "ok"
        assert user_info["credits"] == 49
        lot_id = user_info["lot_id"]

        # 2. Worker simulates failure during response generation and triggers refund
        refunded = storage.refund_credit(
            key_hash=k_hash,
            lot_id=lot_id,
            request_id=req_id,
            reason="simulated_worker_crash"
        )
        assert refunded is True

        # Balance restored to 50
        key_info = storage.get_key_info(raw_key)
        assert key_info["credits"] == 50

        # Ledger check: equation granted + refunded - deducted - expired == remaining
        audit = storage.verify_ledger_balance(k_hash)
        assert audit["balanced"] is True
        assert audit["actual_lot_balance"] == 50
        assert audit["breakdown"]["granted"] == 50
        assert audit["breakdown"]["deducted"] == 1
        assert audit["breakdown"]["refunded"] == 1
        assert audit["breakdown"]["expired"] == 0


def test_api_quota_endpoint_shows_entitlements_and_lots():
    client = TestClient(app)
    # Create Premium key
    raw_key, record = api_storage.create_api_key(tier="premium", credits=10000)

    # Inspect via API
    resp = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["tier"] == "premium"
    assert data["credits_remaining"] == 10000
    assert "entitlement" in data
    assert data["entitlement"]["status"] == "active"
    assert "credit_lots" in data
    assert len(data["credit_lots"]) >= 1


def test_concurrent_deductions_maintain_ledger_balance():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(Path(tmpdir) / "test.db")
        raw_key, record = storage.create_api_key(tier="starter", credits=30)
        k_hash = record["key_hash"]

        # 40 threads race for 30 credits
        results = []

        def worker():
            _, s = storage.authenticate_and_deduct(raw_key)
            results.append(s)

        threads = [threading.Thread(target=worker) for _ in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count("ok") == 30
        assert results.count("exhausted") == 10

        # Ledger must balance
        audit = storage.verify_ledger_balance(k_hash)
        assert audit["balanced"] is True
        assert audit["actual_lot_balance"] == 0
        assert audit["breakdown"]["deducted"] == 30


def test_payment_redemption_topup_and_renewal_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(Path(tmpdir) / "test.db")
        # Create starter key
        raw_key, record = storage.create_api_key(tier="starter", credits=10)
        k_hash = record["key_hash"]

        # 1. Invoice for topup targeting this key
        inv_record, sec, ref = storage.create_invoice(
            tier="topup",
            credits=200,
            asset="USDC",
            amount_raw=5_000_000,
            recipient="TreasuryWallet11111111111111111111111111111",
            target_key_hash=k_hash
        )
        assert inv_record["target_key_hash"] == k_hash

        # Fulfill invoice
        tx_sig = "5wTopupSig1111111111111111111111111111111111111111111111111111111111111111111111111111111111"
        res = storage.fulfill_invoice_and_redeem(
            invoice_id=inv_record["invoice_id"],
            tx_signature=tx_sig,
            asset="USDC",
            amount_raw=5_000_000,
            tier="topup",
            credits_to_grant=200,
            claim_secret=sec
        )
        assert res["status"] == "newly_minted"
        assert res["credits"] == 210  # 10 initial + 200 topup

        # Check quota details
        quota = storage.get_key_quota_details(raw_key)
        assert quota["credits_remaining"] == 210
        assert len(quota["credit_lots"]) == 2

        # 2. Replay check: second fulfillment returns already_redeemed without extra credits
        replay_res = storage.fulfill_invoice_and_redeem(
            invoice_id=inv_record["invoice_id"],
            tx_signature=tx_sig,
            asset="USDC",
            amount_raw=5_000_000,
            tier="topup",
            credits_to_grant=200,
        )
        assert replay_res["status"] == "already_redeemed"
        assert replay_res["credits"] == 210

        # Ledger remains balanced
        audit = storage.verify_ledger_balance(k_hash)
        assert audit["balanced"] is True
        assert audit["actual_lot_balance"] == 210


def test_api_topup_invoice_requires_target_api_key():
    client = TestClient(app)
    # Attempting to create a top-up invoice without a target_api_key must fail
    res = client.post(
        "/v1/payments/invoice",
        json={"target_tier": "topup_500", "asset": "USDC"},
    )
    assert res.status_code == 400
    assert "target_api_key is required" in res.json()["detail"]


def test_api_topup_end_to_end_invoice_and_fulfillment(monkeypatch):
    import secrets
    from payment_verifier import SolanaPaymentVerifier
    from tests.test_payments import build_synthetic_solana_tx

    client = TestClient(app)

    # 1. Start with a Premium key
    raw_key, record = api_storage.create_api_key(tier="premium", credits=10000)
    k_hash = record["key_hash"]

    # 2. Create invoice for topup_500
    res_inv = client.post(
        "/v1/payments/invoice",
        json={
            "target_tier": "topup_500",
            "asset": "USDC",
            "target_api_key": raw_key,
        },
    )
    assert res_inv.status_code == 200
    inv_data = res_inv.json()
    assert inv_data["target_tier"] == "topup_500"
    assert inv_data["credits"] == 500
    assert inv_data["amount_raw"] == 8_000_000
    inv_id = inv_data["invoice_id"]
    ref = inv_data["reference"]

    # 3. Simulate on-chain USDC payment of 8 USDC (8,000,000 units) with reference
    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    tx_sig = "".join(secrets.choice(b58_chars) for _ in range(88))
    synthetic_tx = build_synthetic_solana_tx(
        asset="USDC",
        amount_raw=8_000_000,
        signature=tx_sig,
        reference=ref,
    )
    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", lambda self, s: synthetic_tx)

    # 4. Verify payment
    res_verify = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": tx_sig, "invoice_id": inv_id},
    )
    assert res_verify.status_code == 200
    v_data = res_verify.json()
    assert v_data["success"] is True
    assert v_data["status"] == "newly_minted"
    assert v_data["tier"] == "topup_500"
    assert v_data["credits"] == 10500  # 10,000 allowance + 500 topup

    # 5. Verify quota details: 2 lots, total remaining = 10,500
    quota = api_storage.get_key_quota_details(raw_key)
    assert quota["credits_remaining"] == 10500
    assert len(quota["credit_lots"]) == 2
    topup_lot = [lot for lot in quota["credit_lots"] if lot["lot_type"] == "topup"][0]
    assert topup_lot["credits_granted"] == 500
    assert topup_lot["credits_remaining"] == 500

    # 6. Verify ledger balance integrity
    audit = api_storage.verify_ledger_balance(k_hash)
    assert audit["balanced"] is True
    assert audit["actual_lot_balance"] == 10500
