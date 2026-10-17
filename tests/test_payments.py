"""
Comprehensive unit and integration tests for Solana & USDC payment verification.
Uses synthetic offline transaction fixtures and mocked RPC endpoints.
No external network calls or real blockchain funds are used.
"""

from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from config import CANONICAL_USDC_MINT
from payment_verifier import (
    SolanaPaymentVerifier,
    VerificationError,
    RPCError,
)
from api_server import app


TREASURY = "DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC"
OTHER_WALLET = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
SAMPLE_SIGNATURE = "5wHu1qwLq7Xg5WpS1Gv7nJ8cK3L9bM2rT4vN6pQ8sY1xZ3aB5cD7eF9gH2jK4mN6pQ8sY1xZ3aB5cD7eF9gH2jK4"


def build_synthetic_solana_tx(
    err=None,
    asset="USDC",
    amount_raw=1_000_000,
    recipient=TREASURY,
    mint=CANONICAL_USDC_MINT,
    decimals=6,
):
    """Generates synthetic Solana JSON-parsed transaction response."""
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

    instructions = []

    if asset == "USDC":
        meta["preTokenBalances"] = [
            {
                "accountIndex": 1,
                "mint": mint,
                "owner": recipient,
                "uiTokenAmount": {
                    "amount": "0",
                    "decimals": decimals,
                    "uiAmount": 0.0,
                },
            }
        ]
        meta["postTokenBalances"] = [
            {
                "accountIndex": 1,
                "mint": mint,
                "owner": recipient,
                "uiTokenAmount": {
                    "amount": str(amount_raw),
                    "decimals": decimals,
                    "uiAmount": amount_raw / (10 ** decimals),
                },
            }
        ]
    elif asset == "SOL":
        meta["preBalances"] = [1000000000, 50000000]
        meta["postBalances"] = [1000000000 - amount_raw - 5000, 50000000 + amount_raw]
        instructions.append({
            "program": "system",
            "parsed": {
                "type": "transfer",
                "info": {
                    "source": OTHER_WALLET,
                    "destination": recipient,
                    "lamports": amount_raw,
                },
            },
        })

    return {
        "slot": 12345678,
        "blockTime": 1700000000,
        "meta": meta,
        "transaction": {
            "signatures": [SAMPLE_SIGNATURE],
            "message": {
                "accountKeys": account_keys,
                "instructions": instructions,
            },
        },
    }


def test_verify_valid_usdc_starter_tier():
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})
    result = verifier.verify_payment(SAMPLE_SIGNATURE)

    assert result.asset == "USDC"
    assert result.amount_raw == 1_000_000
    assert result.tier == "tier_starter"
    assert result.credits == 50
    assert result.recipient == TREASURY


def test_verify_valid_usdc_pro_tier():
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=5_000_000)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})
    result = verifier.verify_payment(SAMPLE_SIGNATURE)

    assert result.asset == "USDC"
    assert result.amount_raw == 5_000_000
    assert result.tier == "tier_pro"
    assert result.credits == 300


def test_verify_valid_usdc_unlimited_tier():
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=20_000_000)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})
    result = verifier.verify_payment(SAMPLE_SIGNATURE)

    assert result.asset == "USDC"
    assert result.amount_raw == 20_000_000
    assert result.tier == "tier_unlimited"
    assert result.credits == 999999


def test_verify_valid_native_sol():
    tx = build_synthetic_solana_tx(asset="SOL", amount_raw=5_000_000)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})
    result = verifier.verify_payment(SAMPLE_SIGNATURE)

    assert result.asset == "SOL"
    assert result.amount_raw == 5_000_000
    assert result.tier == "tier_starter"
    assert result.credits == 50


def test_wrong_recipient_rejected():
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=5_000_000, recipient=OTHER_WALLET)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})

    try:
        verifier.verify_payment(SAMPLE_SIGNATURE)
        assert False, "Expected VerificationError for wrong recipient"
    except VerificationError as e:
        assert "No verified transfer to the configured treasury wallet" in str(e)


def test_insufficient_amount_rejected():
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=500)  # Only $0.0005
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})

    try:
        verifier.verify_payment(SAMPLE_SIGNATURE)
        assert False, "Expected VerificationError for insufficient amount"
    except VerificationError as e:
        assert "below the minimum required" in str(e)


def test_failed_transaction_rejected():
    tx = build_synthetic_solana_tx(err={"InstructionError": [0, "Custom"]}, amount_raw=5_000_000)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})

    try:
        verifier.verify_payment(SAMPLE_SIGNATURE)
        assert False, "Expected VerificationError for failed tx"
    except VerificationError as e:
        assert "Transaction failed on-chain" in str(e)


def test_unconfirmed_or_missing_transaction_rejected():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": None})

    try:
        verifier.verify_payment(SAMPLE_SIGNATURE)
        assert False, "Expected VerificationError for missing tx"
    except VerificationError as e:
        assert "Transaction not found or not yet finalized" in str(e)


def test_wrong_token_mint_rejected():
    fake_mint = "FakeTokenMint11111111111111111111111111111111"
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=5_000_000, mint=fake_mint)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})

    try:
        verifier.verify_payment(SAMPLE_SIGNATURE)
        assert False, "Expected VerificationError for wrong mint"
    except VerificationError as e:
        assert "No verified transfer to the configured treasury wallet" in str(e)


def test_client_cannot_request_unearned_higher_tier():
    # User sends $1 (tier_starter), but asks for tier_unlimited ($20)
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})
    result = verifier.verify_payment(SAMPLE_SIGNATURE, requested_tier="tier_unlimited")

    # Server must only grant starter tier!
    assert result.tier == "tier_starter"
    assert result.credits == 50


def test_rpc_failure_fails_closed():
    def failing_rpc(method, params):
        raise RPCError("Connection timed out")

    verifier = SolanaPaymentVerifier(rpc_caller=failing_rpc)
    try:
        verifier.verify_payment(SAMPLE_SIGNATURE)
        assert False, "Expected RPCError to be raised"
    except RPCError as e:
        assert "timed out" in str(e)


def test_api_verify_endpoint_idempotency_and_replay(monkeypatch):
    import secrets
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    suffix = "".join(secrets.choice(b58_chars) for _ in range(8))
    test_sig = SAMPLE_SIGNATURE[:80] + suffix  # Exactly 88 valid base58 chars

    monkeypatch.setattr(
        SolanaPaymentVerifier,
        "fetch_transaction",
        MagicMock(return_value=tx),
    )

    client = TestClient(app)

    # First redemption
    payload = {"transaction_signature": test_sig, "target_tier": "tier_starter"}
    res1 = client.post("/v1/payments/verify-solana", json=payload)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["success"] is True
    assert "api_key" in data1
    assert data1["credits"] == 50

    # Second redemption with exact same signature
    res2 = client.post("/v1/payments/verify-solana", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["success"] is True
    assert "previously redeemed" in data2["message"]
    # Does not return new raw key or extra credits
    assert data2["credits"] == 50
    assert "api_key" not in data2 or data2.get("api_key") is None


def test_api_verify_invalid_signature_format():
    client = TestClient(app)
    # Too short
    res = client.post("/v1/payments/verify-solana", json={"transaction_signature": "short_sig"})
    assert res.status_code == 422


def test_verified_payment_contains_integrity_invariants():
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})
    result = verifier.verify_payment(SAMPLE_SIGNATURE)

    assert result.commitment == "finalized"
    assert result.cluster == "mainnet-beta"
    assert result.verified_at_utc is not None
    assert result.recipient == TREASURY
    assert result.asset == "USDC"
    assert result.amount_raw == 1_000_000
    assert result.tier == "tier_starter"
    assert result.credits == 50


def test_wrong_decimals_rejected():
    # Canonical USDC is 6 decimals; an attacker creating fake SPL token with 9 decimals must be rejected
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, decimals=9)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})

    try:
        verifier.verify_payment(SAMPLE_SIGNATURE)
        assert False, "Expected VerificationError for wrong decimals"
    except VerificationError as e:
        assert "No verified transfer to the configured treasury wallet found" in str(e)


def test_missing_or_corrupt_metadata_rejected():
    # Missing meta
    tx_no_meta = {"slot": 12345, "transaction": {}}
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx_no_meta})

    try:
        verifier.verify_payment(SAMPLE_SIGNATURE)
        assert False, "Expected VerificationError for missing meta"
    except VerificationError as e:
        assert "Transaction metadata is missing" in str(e)


def test_concurrent_in_flight_deduplication():
    import threading
    from rate_limiter import InFlightDeduplicator

    dedup = InFlightDeduplicator()
    call_count = 0
    lock = threading.Lock()

    def slow_verify():
        nonlocal call_count
        import time
        with lock:
            call_count += 1
        time.sleep(0.05)
        return "verified_result"

    results = []

    def task():
        r = dedup.execute("concurrent_sig_test", slow_verify)
        results.append(r)

    threads = [threading.Thread(target=task) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count == 1
    assert len(results) == 8
    assert all(r == "verified_result" for r in results)


def test_transport_retries_vs_payment_metrics_accounting(monkeypatch):
    from metrics import registry

    registry.reset()
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    endpoints = ["https://primary-429.solana.com", "https://backup-ok.solana.com"]

    def mock_rpc_caller(endpoint, method, params):
        if "primary-429" in endpoint:
            raise RPCError("429 Too Many Requests")
        return {"result": tx}

    verifier = SolanaPaymentVerifier(rpc_endpoints=endpoints, rpc_caller=mock_rpc_caller)
    verified = verifier.verify_payment(SAMPLE_SIGNATURE, "tier_starter")
    assert verified.asset == "USDC"

    text = registry.export_prometheus_text()
    # Exactly 2 RPC hops recorded (1 failed 429, 1 success)
    assert 'moltbook_rpc_failover_hops_total{outcome="rate_limited_429",provider="primary-429.solana.com"} 1' in text
    assert 'moltbook_rpc_failover_hops_total{outcome="success",provider="backup-ok.solana.com"} 1' in text
    # Latency histogram recorded exactly 1 observation
    assert 'moltbook_payment_verification_duration_seconds_count{asset="USDC"} 1' in text
