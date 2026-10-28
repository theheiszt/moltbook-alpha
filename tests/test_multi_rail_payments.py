"""
Tests for Pillar 2: Multi-Rail Payment Settlement Expansion.
Validates Nano Zero-Fee Leg, Devnet Testing Toggle, RECEIVED_UNMATCHED State,
and Automated Solana Refund Dispatcher.
"""

import secrets
from fastapi.testclient import TestClient
from api_server import app
from storage import StorageManager
from config import DB_PATH
from payment_verifier import SolanaRefundDispatcher


def test_payments_config_multi_rail_discovery():
    client = TestClient(app)
    res = client.get("/v1/payments/config")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "solana" in data["accepted_rails"]
    assert "nano" in data["accepted_rails"]
    assert data["nano_treasury_address"].startswith("nano_")
    assert "tier_micro" in data["pricing_tiers"]
    assert data["pricing_tiers"]["tier_micro"]["usd"] == 0.25
    assert data["pricing_tiers"]["tier_micro"]["credits"] == 15
    assert "mainnet-beta" in data["supported_clusters"]
    assert "devnet" in data["supported_clusters"]


def test_nano_invoice_creation():
    client = TestClient(app)
    res = client.post("/v1/payments/invoice", json={
        "target_tier": "tier_micro",
        "rail": "nano",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["rail"] == "nano"
    assert data["asset"] == "XNO"
    assert data["credits"] == 15
    assert data["merchant_address"].startswith("nano_")
    assert "instructions" in data
    assert "raw" in data["instructions"]
    assert data["verify_endpoint"] == "POST /v1/payments/verify-nano"


def test_nano_settlement_verification_success_and_witness():
    client = TestClient(app)
    # Create invoice
    inv_res = client.post("/v1/payments/invoice", json={
        "target_tier": "tier_micro",
        "rail": "nano",
    })
    assert inv_res.status_code == 200
    inv = inv_res.json()

    # Verify settlement with mock ledger hash (64 hex characters)
    block_hash = secrets.token_hex(32)
    ver_res = client.post("/v1/payments/verify-nano", json={
        "block_hash": block_hash,
        "invoice_id": inv["invoice_id"],
        "claim_secret": inv["claim_secret"],
    })
    assert ver_res.status_code == 200
    ver = ver_res.json()
    assert ver["success"] is True
    assert ver["rail"] == "nano"
    assert ver["credits"] == 15
    assert ver["tier"] == "tier_micro"
    assert ver["api_key"].startswith("molt_")
    assert ver.get("state_witness_id") is not None


def test_nano_settlement_idempotency_and_claim():
    client = TestClient(app)
    # Create invoice
    inv_res = client.post("/v1/payments/invoice", json={
        "target_tier": "tier_micro",
        "rail": "nano",
    })
    inv = inv_res.json()
    block_hash = secrets.token_hex(32)

    # First verification
    ver_res1 = client.post("/v1/payments/verify-nano", json={
        "block_hash": block_hash,
        "invoice_id": inv["invoice_id"],
        "claim_secret": inv["claim_secret"],
    })
    assert ver_res1.status_code == 200
    key1 = ver_res1.json()["api_key"]

    # Replay with same claim_secret returns existing key
    ver_res2 = client.post("/v1/payments/verify-nano", json={
        "block_hash": block_hash,
        "invoice_id": inv["invoice_id"],
        "claim_secret": inv["claim_secret"],
    })
    assert ver_res2.status_code == 200
    assert ver_res2.json()["api_key"] == key1


def test_nano_settlement_invalid_block_hash():
    client = TestClient(app)
    inv_res = client.post("/v1/payments/invoice", json={
        "target_tier": "tier_micro",
        "rail": "nano",
    })
    inv = inv_res.json()

    # Invalid block hash format (not 64 hex characters)
    res = client.post("/v1/payments/verify-nano", json={
        "block_hash": "invalid_hash",
        "invoice_id": inv["invoice_id"],
        "claim_secret": inv["claim_secret"],
    })
    assert res.status_code == 422


def test_devnet_solana_invoice_creation():
    client = TestClient(app)
    res = client.post("/v1/payments/invoice", json={
        "target_tier": "tier_starter",
        "rail": "solana",
        "cluster": "devnet",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["cluster"] == "devnet"


def test_unmatched_payment_storage_lifecycle(tmp_path):
    storage = StorageManager(tmp_path / "test_unmatched.db")
    sig = "test_unm_" + ("c" * 60)
    payer = "4Nd1mBQtrMJVYVfKf2PJy9NZWsWB8d5Kgatq7xPyBdp5"

    rec = storage.record_unmatched_payment(
        rail="solana",
        tx_signature=sig,
        payer_wallet=payer,
        asset="SOL",
        amount_raw=20_000_000,
        expected_amount_raw=25_000_000,
        reason="UNDERPAYMENT",
    )
    assert rec["status"] == "HELD"
    assert rec["amount_raw"] == 20_000_000

    # Retrieve
    fetched = storage.get_unmatched_payment(rec["unmatched_id"])
    assert fetched is not None
    assert fetched["payer_wallet"] == payer

    # List HELD
    held = storage.list_unmatched_payments(status="HELD")
    assert len(held) == 1

    # Mark refunded
    ok = storage.mark_unmatched_refunded(rec["unmatched_id"], "ref_tx_test123", 19_995_000)
    assert ok is True

    updated = storage.get_unmatched_payment(rec["unmatched_id"])
    assert updated["status"] == "REFUNDED"
    assert updated["refund_tx_sig"] == "ref_tx_test123"


def test_automated_refund_dispatcher_api():
    client = TestClient(app)
    sm = StorageManager(DB_PATH)

    sig = "unm_sig_" + ("d" * 60)
    payer = "4Nd1mBQtrMJVYVfKf2PJy9NZWsWB8d5Kgatq7xPyBdp5"
    unm = sm.record_unmatched_payment(
        rail="solana",
        tx_signature=sig,
        payer_wallet=payer,
        asset="SOL",
        amount_raw=50_000_000,
        expected_amount_raw=60_000_000,
        reason="UNDERPAYMENT",
    )
    unm_id = unm["unmatched_id"]

    # List endpoint
    list_res = client.get("/v1/payments/unmatched?status_filter=HELD")
    assert list_res.status_code == 200
    assert any(p["unmatched_id"] == unm_id for p in list_res.json()["unmatched_payments"])

    # Trigger refund
    ref_res = client.post(f"/v1/payments/refund/{unm_id}")
    assert ref_res.status_code == 200
    ref_data = ref_res.json()
    assert ref_data["success"] is True
    assert ref_data["status"] == "REFUNDED"
    assert ref_data["payer_wallet"] == payer
    assert ref_data["refund_amount_raw"] == 50_000_000 - 5000  # 5,000 lamports standard fee deducted
    assert ref_data["fee_deducted_raw"] == 5000
    assert ref_data["refund_tx_sig"].startswith("ref_tx_")

    # Double refund rejected
    ref_res2 = client.post(f"/v1/payments/refund/{unm_id}")
    assert ref_res2.status_code == 400


def test_solana_refund_dispatcher_unit():
    dispatcher = SolanaRefundDispatcher(treasury_wallet="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx")

    # SOL fee deduction (5000 lamports)
    sol_refund = dispatcher.calculate_refund_amount("SOL", 100_000)
    assert sol_refund == 95_000

    # USDC zero deduction
    usdc_refund = dispatcher.calculate_refund_amount("USDC", 5_000_000)
    assert usdc_refund == 5_000_000

    # Nano / XNO zero deduction
    xno_refund = dispatcher.calculate_refund_amount("XNO", 250_000)
    assert xno_refund == 250_000
