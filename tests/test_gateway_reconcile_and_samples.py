import secrets
import time
from unittest.mock import patch
from fastapi.testclient import TestClient

import api_server
from payment_verifier import VerifiedPayment


client = TestClient(api_server.app)


def test_gateway_discovery_endpoints(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_GATEWAY_URL", "https://custom-edge-gateway.trycloudflare.com/")
    res1 = client.get("/v1/gateway/discovery")
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["status"] == "online"
    assert body1["transport_protocol"] == "http2"
    assert body1["self_healing_watchdog"] is True
    assert body1["active_gateway_url"] == "https://custom-edge-gateway.trycloudflare.com"
    assert body1["canonical_discovery_url"] == "https://theheiszt.github.io/moltbook-alpha/gateway.json"
    assert body1["endpoints"]["data_products"] == "https://custom-edge-gateway.trycloudflare.com/v1/data-products"
    assert body1["endpoints"]["payment_reconcile"] == "https://custom-edge-gateway.trycloudflare.com/v1/payments/reconcile"

    res2 = client.get("/gateway.json")
    assert res2.status_code == 200
    assert res2.json()["active_gateway_url"] == "https://custom-edge-gateway.trycloudflare.com"


def test_capabilities_includes_new_routes():
    res = client.get("/v1/capabilities")
    assert res.status_code == 200
    caps = res.json()
    paths = {
        ep["path"]
        for section in caps["capabilities"].values()
        for ep in section.get("endpoints", [])
    }
    assert "/v1/gateway/discovery" in paths
    assert "/v1/data-products/{product_id}/sample" in paths
    assert "/v1/payments/reconcile" in paths
    assert "/v1/payments/unmatched" in paths
    assert "/v1/payments/refund/{unmatched_id}" in paths


def test_data_product_unmetered_samples_and_witness():
    cat_res = client.get("/v1/data-products")
    assert cat_res.status_code == 200
    products = cat_res.json()["data_products"]
    assert len(products) >= 3

    for p in products:
        pid = p["product_id"]
        assert p["sample_snapshot_endpoint"] == f"/v1/data-products/{pid}/sample"

        sample_res = client.get(f"/v1/data-products/{pid}/sample")
        assert sample_res.status_code == 200
        snap = sample_res.json()
        assert snap["product_id"] == pid
        assert snap["retrieval_outcome"] == "VALUE"
        assert snap["usage_receipt"]["credits_deducted"] == 0
        assert snap["usage_receipt"]["is_sample"] is True
        assert snap["state_witness_id"].startswith("wit_")
        assert len(snap["witness_signature"]) > 20

        if pid == "moltbook-agent-intelligence-feed":
            levels = {item["evidence_level"] for item in snap["evidence_items"]}
            assert levels == {"OBSERVED_FACT", "INFERRED_CONCLUSION", "UNVERIFIED_CLAIM"}

    # Verify 404 on unknown product sample
    not_found = client.get("/v1/data-products/non-existent-product/sample")
    assert not_found.status_code == 404


def test_reconcile_orphan_deposit_and_auto_refund():
    suffix = secrets.token_hex(8)
    fake_sig = f"5ReconcileOrphanSig{suffix}" + "1" * (88 - len(f"5ReconcileOrphanSig{suffix}"))
    mock_payment = VerifiedPayment(
        tx_signature=fake_sig,
        asset="USDC",
        amount_raw=1_000_000,
        tier="tier_starter",
        credits=50,
        recipient="7B52sU8ef3M926dcxm7227312312312312312312312",
        slot=250000100,
        block_time=int(time.time()),
        payer="PayerOrphanWallet111111111111111111111111111",
        reference=None,
        rpc_endpoint_used="https://api.mainnet-beta.solana.com",
    )

    with patch("api_server.SolanaPaymentVerifier.verify_payment", return_value=mock_payment):
        # 1. Reconcile without auto-refund -> quarantines as UNLINKED_ORPHAN_DEPOSIT
        r1 = client.post("/v1/payments/reconcile", json={
            "transaction_signature": fake_sig,
            "auto_refund_unmatched": False,
        })
        assert r1.status_code == 200
        b1 = r1.json()
        assert b1["reconciliation_status"] == "QUARANTINED_UNMATCHED"
        assert b1["reason"] == "UNLINKED_ORPHAN_DEPOSIT"
        assert b1["status"] == "HELD"
        assert b1["state_witness_id"].startswith("wit_")
        assert b1["witness_signature"]
        unmatched_id = b1["unmatched_id"]

        # 2. Refund via /v1/payments/refund/{unmatched_id} and verify Ed25519 witness receipt
        r_ref = client.post(f"/v1/payments/refund/{unmatched_id}")
        assert r_ref.status_code == 200
        b_ref = r_ref.json()
        assert b_ref["status"] == "REFUNDED"
        assert b_ref["state_witness_id"].startswith("wit_")
        assert b_ref["witness_signature"]


def test_reconcile_open_invoice_fulfillment():
    # Create an open invoice
    inv_res = client.post("/v1/payments/invoice", json={
        "target_tier": "tier_starter",
        "asset": "USDC",
        "rail": "solana",
    })
    assert inv_res.status_code == 200
    inv = inv_res.json()
    invoice_id = inv["invoice_id"]
    reference = inv["reference"]

    suffix = secrets.token_hex(8)
    fake_sig = f"5ReconcileFulfillSig{suffix}" + "1" * (88 - len(f"5ReconcileFulfillSig{suffix}"))
    mock_payment = VerifiedPayment(
        tx_signature=fake_sig,
        asset="USDC",
        amount_raw=inv["amount_raw"],
        tier="tier_starter",
        credits=50,
        recipient=inv["treasury_wallet"],
        slot=250000200,
        block_time=int(time.time()),
        payer="PayerValidWallet1111111111111111111111111111",
        reference=reference,
        rpc_endpoint_used="https://api.mainnet-beta.solana.com",
    )

    with patch("api_server.SolanaPaymentVerifier.verify_payment", return_value=mock_payment):
        r1 = client.post("/v1/payments/reconcile", json={
            "transaction_signature": fake_sig,
            "invoice_id": invoice_id,
        })
        assert r1.status_code == 200
        b1 = r1.json()
        assert b1["reconciliation_status"] == "RECONCILED_AND_FULFILLED"
        assert b1["invoice_id"] == invoice_id
        assert b1["credits"] == 50
        assert b1["state_witness_id"].startswith("wit_")
        assert b1["witness_signature"]

        # Calling reconcile again on the redeemed signature returns REDEEMED idempotently
        r2 = client.post("/v1/payments/reconcile", json={
            "transaction_signature": fake_sig,
        })
        assert r2.status_code == 200
        b2 = r2.json()
        assert b2["reconciliation_status"] == "REDEEMED"
        assert b2["invoice_id"] == invoice_id
        assert b2["state_witness_id"].startswith("wit_")
