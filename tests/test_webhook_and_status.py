"""
Deterministic unit and integration tests for push-based payment webhooks
and public payment status inspection.
"""

import secrets
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from config import WEBHOOK_SECRET, CANONICAL_USDC_MINT
from payment_verifier import SolanaPaymentVerifier, RPCError
from api_server import app

TREASURY = "DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC"
OTHER_WALLET = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
SAMPLE_BASE58_SIG = "5wHu1qwLq7Xg5WpS1Gv7nJ8cK3L9bM2rT4vN6pQ8sY1xZ3aB5cD7eF9gH2jK4mN6pQ8sY1xZ3aB5cD7eF9gH2jK4"


def make_random_sig() -> str:
    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    suffix = "".join(secrets.choice(b58_chars) for _ in range(8))
    return SAMPLE_BASE58_SIG[:80] + suffix


def build_synthetic_tx(err=None, asset="USDC", amount_raw=1_000_000, recipient=TREASURY, signature=SAMPLE_BASE58_SIG):
    meta = {
        "err": err,
        "fee": 5000,
        "preBalances": [1000000000, 50000000],
        "postBalances": [995000000, 50000000],
        "preTokenBalances": [],
        "postTokenBalances": [],
    }
    account_keys = [
        {"pubkey": OTHER_WALLET, "signer": True, "writable": True},
        {"pubkey": recipient, "signer": False, "writable": True},
    ]
    if asset == "USDC":
        meta["preTokenBalances"] = [{
            "accountIndex": 1,
            "mint": CANONICAL_USDC_MINT,
            "owner": recipient,
            "uiTokenAmount": {"amount": "0", "decimals": 6, "uiAmount": 0.0},
        }]
        meta["postTokenBalances"] = [{
            "accountIndex": 1,
            "mint": CANONICAL_USDC_MINT,
            "owner": recipient,
            "uiTokenAmount": {"amount": str(amount_raw), "decimals": 6, "uiAmount": amount_raw / 1_000_000},
        }]
    return {
        "blockTime": 1700000000,
        "slot": 250000000,
        "meta": meta,
        "transaction": {
            "signatures": [signature],
            "message": {"accountKeys": account_keys, "instructions": []},
        },
    }


def test_webhook_unauthorized_without_secret():
    client = TestClient(app)
    sig = make_random_sig()
    res = client.post("/v1/payments/webhook", json={"transaction_signature": sig})
    assert res.status_code == 401
    assert "Invalid or missing X-Webhook-Secret" in res.json()["detail"]


def test_webhook_unauthorized_with_wrong_secret():
    client = TestClient(app)
    sig = make_random_sig()
    res = client.post(
        "/v1/payments/webhook",
        json={"transaction_signature": sig},
        headers={"X-Webhook-Secret": "invalid_wrong_secret"},
    )
    assert res.status_code == 401
    assert "Invalid or missing X-Webhook-Secret" in res.json()["detail"]


def test_webhook_malformed_signature():
    client = TestClient(app)
    res = client.post(
        "/v1/payments/webhook",
        json={"transaction_signature": "short_sig"},
        headers={"X-Webhook-Secret": WEBHOOK_SECRET},
    )
    assert res.status_code == 422


def test_webhook_successful_redemption_and_status_inspection(monkeypatch):
    sig = make_random_sig()
    tx = build_synthetic_tx(asset="USDC", amount_raw=1_000_000, signature=sig)

    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", MagicMock(return_value=tx))

    client = TestClient(app)

    # 1. Inspect status before redemption -> should be unredeemed
    status_before = client.get(f"/v1/payments/status/{sig}")
    assert status_before.status_code == 200
    assert status_before.json()["status"] == "pending_or_unredeemed"

    # 2. Trigger webhook redemption with valid secret
    res = client.post(
        "/v1/payments/webhook",
        json={"transaction_signature": sig, "target_tier": "tier_starter"},
        headers={"X-Webhook-Secret": WEBHOOK_SECRET},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["status"] == "newly_minted"
    assert data["credits"] == 50
    assert "api_key" in data
    assert data["api_key"].startswith("molt_sol_")

    # 3. Inspect status after redemption -> should be redeemed and NOT leak plaintext api_key
    status_after = client.get(f"/v1/payments/status/{sig}")
    assert status_after.status_code == 200
    data_after = status_after.json()
    assert data_after["success"] is True
    assert data_after["status"] == "redeemed"
    assert data_after["tier"] == "tier_starter"
    assert data_after["credits_granted"] == 50
    assert "key_prefix" in data_after
    assert "api_key" not in data_after  # Cryptographic safety: raw key is never exposed


def test_webhook_idempotency_replay(monkeypatch):
    sig = make_random_sig()
    tx = build_synthetic_tx(asset="USDC", amount_raw=1_000_000, signature=sig)

    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", MagicMock(return_value=tx))

    client = TestClient(app)

    # First webhook arrival
    res1 = client.post(
        "/v1/payments/webhook",
        json={"transaction_signature": sig, "target_tier": "tier_starter"},
        headers={"X-Webhook-Secret": WEBHOOK_SECRET},
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "newly_minted"

    # Duplicate webhook arrival
    res2 = client.post(
        "/v1/payments/webhook",
        json={"transaction_signature": sig, "target_tier": "tier_starter"},
        headers={"X-Webhook-Secret": WEBHOOK_SECRET},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["success"] is True
    assert data2["status"] == "already_redeemed"
    assert "previously redeemed" in data2["message"]
    assert data2["api_key"] is None  # Does not re-mint or re-leak key


def test_webhook_verification_failure_wrong_recipient(monkeypatch):
    sig = make_random_sig()
    tx = build_synthetic_tx(asset="USDC", amount_raw=1_000_000, recipient=OTHER_WALLET, signature=sig)

    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", MagicMock(return_value=tx))

    client = TestClient(app)
    res = client.post(
        "/v1/payments/webhook",
        json={"transaction_signature": sig},
        headers={"X-Webhook-Secret": WEBHOOK_SECRET},
    )
    assert res.status_code == 400
    assert "treasury wallet" in res.json()["detail"]



def test_webhook_rpc_timeout_fails_closed(monkeypatch):
    sig = make_random_sig()

    def mock_fetch(*args, **kwargs):
        raise RPCError("Solana RPC connection timed out across all providers")

    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", mock_fetch)

    client = TestClient(app)
    res = client.post(
        "/v1/payments/webhook",
        json={"transaction_signature": sig},
        headers={"X-Webhook-Secret": WEBHOOK_SECRET},
    )
    assert res.status_code == 502
    assert "Solana RPC communication error" in res.json()["detail"]


def test_status_endpoint_invalid_signature():
    client = TestClient(app)
    res = client.get("/v1/payments/status/not_valid_base58_too_short")
    assert res.status_code == 422
