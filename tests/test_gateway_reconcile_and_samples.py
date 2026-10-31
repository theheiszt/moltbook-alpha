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
    assert "/v1/quant/first-passage" in paths
    assert "/v1/quant/trade-viability" in paths


def test_quant_first_passage_and_trade_viability_endpoints():
    r1 = client.get("/v1/quant/first-passage?pair=BONK/SOL&target_net_pct=0.015&stop_loss_pct=0.02&roundtrip_spread_bps=8.0")
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["pair"] == "BONK/SOL"
    assert body1["target_net_pct"] == 0.015
    assert body1["state_witness_id"].startswith("wit_")
    assert len(body1["witness_signature"]) > 20
    assert len(body1["horizon_probabilities"]) == 6
    assert len(body1["optimal_target_ladder"]) == 6

    viability_req = {
        "pair": "JUP/SOL",
        "target_net_pct": 0.010,
        "stop_loss_pct": 0.015,
        "roundtrip_spread_bps": 2.0,
        "horizons_hours": [4, 12, 24],
    }
    assert client.post("/v1/quant/trade-viability", json=viability_req).status_code == 402

    raw_key, _ = api_server.storage.create_api_key(tier="tier_pro", credits=10)
    r2 = client.post("/v1/quant/trade-viability", json=viability_req, headers={"X-API-KEY": raw_key})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["pair"] == "JUP/SOL"
    assert len(body2["horizon_probabilities"]) == 3
    assert body2["state_witness_id"].startswith("wit_")
    assert body2["witness_signature"]


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
        admin_key, _ = api_server.storage.create_api_key(tier="admin", credits=1000)
        r_ref = client.post(
            f"/v1/payments/refund/{unmatched_id}",
            headers={"x-api-key": admin_key, "X-Admin-Bypass-Confirmation": "true"},
        )
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


def test_molt_alpha_dems_nft_catalog_and_lazy_mint_flow(tmp_path, monkeypatch):
    import nft_collection

    monkeypatch.setattr(nft_collection, "NFT_LEDGER_PATH", tmp_path / "test_nft_ledger.json")
    # Ensure default init uses patched ledger path
    orig_init = nft_collection.MoltAlphaDemsCollection.__init__
    monkeypatch.setattr(
        nft_collection.MoltAlphaDemsCollection,
        "__init__",
        lambda self, ledger_path=None: orig_init(self, ledger_path or (tmp_path / "test_nft_ledger.json")),
    )

    # 1. Inspect Catalog
    cat_res = client.get("/v1/nfts/catalog")
    assert cat_res.status_code == 200
    cat = cat_res.json()
    assert cat["collection"]["name"] == "Molt Alpha DEMS"
    assert cat["count"] == 6
    ids = [it["nft_id"] for it in cat["items"]]
    assert ids == [
        "01-the-synth",
        "02-inscribe",
        "03-scribe",
        "04-core",
        "05-wanderer",
        "06-oracle",
    ]

    # 2. Fetch Metaplex Metadata & PNG Asset
    meta_res = client.get("/v1/nfts/metadata/03-scribe.json?edition=1")
    assert meta_res.status_code == 200
    meta = meta_res.json()
    assert "SCRIBE" in meta["name"]
    assert meta["seller_fee_basis_points"] == 500

    # Ensure test asset exists for isolated test run
    nft_collection.NFT_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    test_png = nft_collection.NFT_ASSETS_DIR / "03_scribe.png"
    created_test_png = False
    if not test_png.exists():
        test_png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        created_test_png = True
    try:
        img_res = client.get("/v1/nfts/assets/03_scribe.png")
        assert img_res.status_code == 200
        assert img_res.headers["content-type"] == "image/png"
    finally:
        if created_test_png and test_png.exists():
            test_png.unlink()

    # 3. Create Lazy-Mint Order for 02-inscribe (0.02 SOL)
    buyer_wallet = "AyP2LbewqnYFeHaEiErnE9x5EosHPmHrQZaRuVDo4Pv3"
    ord_res = client.post("/v1/nfts/order", json={
        "nft_id": "02-inscribe",
        "buyer_wallet": buyer_wallet,
        "asset": "SOL",
    })
    assert ord_res.status_code == 201
    ord_body = ord_res.json()
    assert ord_body["nft_id"] == "02-inscribe"
    assert ord_body["price_human"] == 0.02
    assert ord_body["amount_raw"] == 20_000_000
    assert ord_body["bundled_credits"] == 50
    order_id = ord_body["order_id"]

    # 4. Claim Lazy-Mint Order with verified payment
    suffix = secrets.token_hex(8)
    fake_sig = f"5NftMintSig{suffix}" + "1" * (88 - len(f"5NftMintSig{suffix}"))
    mock_payment = VerifiedPayment(
        tx_signature=fake_sig,
        asset="SOL",
        amount_raw=20_000_000,
        tier="tier_starter",
        credits=50,
        recipient=ord_body["treasury_wallet"],
        slot=250000500,
        block_time=int(time.time()),
        payer=buyer_wallet,
        reference=ord_body["memo_reference"],
        rpc_endpoint_used="https://api.mainnet-beta.solana.com",
    )

    with patch("api_server.SolanaPaymentVerifier.verify_payment", return_value=mock_payment):
        claim_res = client.post("/v1/nfts/claim", json={
            "order_id": order_id,
            "transaction_signature": fake_sig,
        })
        assert claim_res.status_code == 200
        receipt = claim_res.json()
        assert receipt["status"] == "MINTED"
        assert receipt["edition_number"] == 1
        assert receipt["owner_wallet"] == buyer_wallet
        assert receipt["bundled_utility"]["credits_granted"] == 50
        assert receipt["bundled_utility"]["api_key"].startswith("molt_")
        assert receipt["state_witness_id"].startswith("wit_")
        assert receipt["witness_signature"]


def test_agent_jobs_and_demand_leaderboard_flow():
    with api_server.storage.connection() as conn:
        with conn:
            conn.execute("DELETE FROM agent_job_submissions WHERE worker_agent LIKE '@test_quant_agent_%'")
    # 1. Check Agent Service Demand Leaderboard
    dem_res = client.get("/v1/intel/demand")
    assert dem_res.status_code == 200
    dem_body = dem_res.json()
    assert "demand_clusters" in dem_body
    assert len(dem_body["demand_clusters"]) >= 4

    # 2. Check Open Agent Jobs Board
    board_res = client.get("/v1/jobs/board")
    assert board_res.status_code == 200
    board_body = board_res.json()
    assert board_body["total_listed"] >= 5
    assert board_body["direct_bounties_count"] >= 5
    assert board_body["reward_policy"]["reward_per_verified_response_credits"] == 10
    assert board_body["reward_policy"]["max_rewards_cap"] == 25

    # 3. Inspect a specific bounty
    detail_res = client.get("/v1/jobs/job_molt_clmm_vacuum_01")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["job_id"] == "job_molt_clmm_vacuum_01"
    assert detail["reward_asset"] == "CREDITS"
    assert detail["reward_amount"] == 10.0

    # 4. Submit a verifiable deliverable and earn +10 free bounty API credits
    worker_id = f"@test_quant_agent_{secrets.token_hex(4)}"
    sub_res = client.post("/v1/jobs/job_molt_clmm_vacuum_01/submit", json={
        "worker_agent": worker_id,
        "deliverable_uri": "https://www.moltbook.com/posts/verified-clmm-vacuum-proof",
        "deliverable_summary": "Detected 48 bps tick liquidity vacuum on Raydium CLMM pool 7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJpi at slot 312950112 with bid/ask imbalance 0.34.",
    })
    assert sub_res.status_code == 200
    sub_body = sub_res.json()
    assert sub_body["success"] is True
    assert sub_body["status"] == "VERIFIED_AND_REWARDED"
    assert sub_body["state_witness_id"].startswith("wit_")
    assert sub_body["bounty_reward"]["credits_granted"] == 10
    assert sub_body["reward_pool"]["max_rewards_cap"] == 25
    earned_key = sub_body["bounty_reward"]["api_key"]
    assert earned_key.startswith("molt_bounty_reward_")

    # 5. Use the newly earned bounty API key to post a new structured job
    post_res = client.post(
        "/v1/jobs/post",
        headers={"X-API-KEY": earned_key},
        json={
            "title": "Monitor Orca Whirlpool JUP/SOL 15m Volatility Squeeze",
            "description": "Alert webhook whenever 15m realized volatility exceeds 1.25% with >60% 24h touch probability.",
            "category": "quant_research",
            "required_capabilities": ["orca_whirlpool", "first_passage_api"],
            "reward_amount": 75.0,
            "reward_asset": "CREDITS",
            "poster_agent": "@test_quant_agent",
        },
    )
    assert post_res.status_code == 200
    post_body = post_res.json()
    assert post_body["success"] is True
    assert post_body["job"]["title"] == "Monitor Orca Whirlpool JUP/SOL 15m Volatility Squeeze"
    assert post_body["job"]["state_witness_id"].startswith("wit_")



def test_outside_witness_and_shingle_containment_verifier():
    from fastapi.testclient import TestClient
    from api_server import app
    client = TestClient(app)

    # 1. Valid independent deliverable passes outside witness (is_parroted_copy == False)
    r1 = client.post(
        "/v1/jobs/verify-witness",
        json={
            "reference_text": "Submit a verifiable Solana CLMM tick vacuum or spoofed wall anomaly with pool address and slot height",
            "candidate_text": "Observed 42 bps tick vacuum on Raydium SOL/USDC CLMM pool at slot 328491020 with 18.4% bid-side depth withdrawal",
            "k": 4,
        },
    )
    assert r1.status_code == 200
    m1 = r1.json()["shingle_containment_and_edit_metrics"]
    assert m1["is_parroted_copy"] is False
    assert m1["containment_over_reference"] < 0.70

    # 2. Parroted prompt copy is flagged (is_parroted_copy == True)
    r2 = client.post(
        "/v1/jobs/verify-witness",
        json={
            "reference_text": "Submit a verifiable Solana CLMM tick vacuum or spoofed wall anomaly with pool address and slot height",
            "candidate_text": "Submit a verifiable Solana CLMM tick vacuum or spoofed wall anomaly with pool address and slot height plus two extra words",
            "k": 4,
        },
    )
    assert r2.status_code == 200
    m2 = r2.json()["shingle_containment_and_edit_metrics"]
    assert m2["is_parroted_copy"] is True
    assert m2["containment_over_reference"] >= 0.70
