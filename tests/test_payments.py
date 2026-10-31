"""
Comprehensive unit and integration tests for Solana & USDC payment verification.
Uses synthetic offline transaction fixtures and mocked RPC endpoints.
No external network calls or real blockchain funds are used.
"""

import time
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from config import CANONICAL_USDC_MINT
from payment_verifier import (
    SolanaPaymentVerifier,
    VerificationError,
    RPCError,
)
from api_server import app


TREASURY = "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx"
OTHER_WALLET = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
SAMPLE_SIGNATURE = "5wHu1qwLq7Xg5WpS1Gv7nJ8cK3L9bM2rT4vN6pQ8sY1xZ3aB5cD7eF9gH2jK4mN6pQ8sY1xZ3aB5cD7eF9gH2jK4"


def build_synthetic_solana_tx(
    err=None,
    asset="USDC",
    amount_raw=1_000_000,
    recipient=TREASURY,
    mint=CANONICAL_USDC_MINT,
    decimals=6,
    signature=SAMPLE_SIGNATURE,
    reference=None,
    block_time=None,
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
    if reference:
        account_keys.append({"pubkey": reference, "signer": False, "writable": False})

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

    if block_time is None:
        block_time = int(time.time())

    return {
        "slot": 12345678,
        "blockTime": block_time,
        "meta": meta,
        "transaction": {
            "signatures": [signature],
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
    assert result.tier in ("tier_unlimited", "tier_premium")
    assert result.credits == 10000


def test_verify_valid_usdc_premium_tier():
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=20_000_000)
    verifier = SolanaPaymentVerifier(rpc_caller=lambda method, params: {"result": tx})
    result = verifier.verify_payment(SAMPLE_SIGNATURE, requested_tier="tier_premium")

    assert result.asset == "USDC"
    assert result.amount_raw == 20_000_000
    assert result.tier == "tier_premium"
    assert result.credits == 10000



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
    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    suffix = "".join(secrets.choice(b58_chars) for _ in range(8))
    test_sig = SAMPLE_SIGNATURE[:80] + suffix  # Exactly 88 valid base58 chars
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, signature=test_sig)

    monkeypatch.setattr(
        SolanaPaymentVerifier,
        "fetch_transaction",
        MagicMock(return_value=tx),
    )

    from api_server import rate_limiter
    rate_limiter.reset()
    client = TestClient(app)
    inv = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    ref = inv["reference"]
    inv_id = inv["invoice_id"]
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, signature=test_sig, reference=ref)

    monkeypatch.setattr(
        SolanaPaymentVerifier,
        "fetch_transaction",
        MagicMock(return_value=tx),
    )

    # First redemption
    payload = {"transaction_signature": test_sig, "invoice_id": inv_id}
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
    assert "previously redeemed" in data2["message"] or "already fulfilled" in data2["message"]
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


def test_confirmed_but_not_finalized_rejected():
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    tx["confirmationStatus"] = "confirmed"

    verifier = SolanaPaymentVerifier(rpc_caller=lambda m, p: {"result": tx})
    import pytest
    with pytest.raises(VerificationError) as exc:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "confirmationStatus is 'confirmed', expected 'finalized'" in str(exc.value)

    # Test commitment field
    del tx["confirmationStatus"]
    tx["commitment"] = "confirmed"
    with pytest.raises(VerificationError) as exc2:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "commitment is 'confirmed', expected 'finalized'" in str(exc2.value)


def test_missing_commitment_evidence_rejected():
    import pytest
    # Missing slot
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    tx["slot"] = None
    verifier = SolanaPaymentVerifier(rpc_caller=lambda m, p: {"result": tx})
    with pytest.raises(VerificationError) as exc:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "invalid slot" in str(exc.value)

    # Slot <= 0
    tx["slot"] = 0
    with pytest.raises(VerificationError) as exc2:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "invalid slot" in str(exc2.value)

    # Missing blockTime
    tx["slot"] = 12345678
    tx["blockTime"] = None
    with pytest.raises(VerificationError) as exc3:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "invalid blockTime" in str(exc3.value)


def test_provider_inconsistent_status_rejected():
    import pytest
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    # meta.err is None, but meta.status has Err object
    tx["meta"]["status"] = {"Err": {"InstructionError": [0, "Custom"]}}
    verifier = SolanaPaymentVerifier(rpc_caller=lambda m, p: {"result": tx})
    with pytest.raises(VerificationError) as exc:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "Transaction failed on-chain" in str(exc.value)

    # confirmationStatus is 'processed'
    tx["meta"]["status"] = {"Ok": None}
    tx["confirmationStatus"] = "processed"
    with pytest.raises(VerificationError) as exc2:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "confirmationStatus is 'processed', expected 'finalized'" in str(exc2.value)


def test_wrong_cluster_rejected():
    import pytest
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    tx["cluster"] = "devnet"

    verifier = SolanaPaymentVerifier(rpc_caller=lambda m, p: {"result": tx})
    with pytest.raises(VerificationError) as exc:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "Cluster mismatch" in str(exc.value)

    # Endpoint configured for devnet when expecting mainnet-beta
    verifier_devnet = SolanaPaymentVerifier(rpc_endpoints=["https://api.devnet.solana.com"])
    with pytest.raises(VerificationError) as exc2:
        verifier_devnet.verify_payment(SAMPLE_SIGNATURE)
    assert "configured for devnet/testnet" in str(exc2.value)


def test_signature_mismatch_rejected():
    import pytest
    unrelated_sig = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin11111111111111111111111111111111111111111111"
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, signature=unrelated_sig)

    verifier = SolanaPaymentVerifier(rpc_caller=lambda m, p: {"result": tx})
    with pytest.raises(VerificationError) as exc:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "signature mismatch" in str(exc.value)


def test_ambiguous_rpc_timeout_followed_by_successful_retry(monkeypatch):
    import secrets
    from api_server import app, storage, rate_limiter

    rate_limiter.reset()
    client = TestClient(app)
    inv = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    ref = inv["reference"]
    inv_id = inv["invoice_id"]

    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    sig = SAMPLE_SIGNATURE[:80] + "".join(secrets.choice(b58_chars) for _ in range(8))
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, signature=sig, reference=ref)

    # 1. First attempt times out
    call_attempts = 0

    def mock_fetch(self, signature_arg):
        nonlocal call_attempts
        call_attempts += 1
        if call_attempts == 1:
            raise RPCError("504 Gateway Timeout: upstream RPC timed out")
        return tx

    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", mock_fetch)

    res1 = client.post("/v1/payments/verify-solana", json={"transaction_signature": sig, "invoice_id": inv_id})
    assert res1.status_code == 502
    assert "Solana RPC communication error" in res1.json()["detail"]

    # Verify 0 rows in storage
    assert storage.get_payment_redemption(sig) is None

    # 2. Second attempt succeeds and mints key
    res2 = client.post("/v1/payments/verify-solana", json={"transaction_signature": sig, "invoice_id": inv_id})
    assert res2.status_code == 200
    assert res2.json()["success"] is True
    assert "molt_sol_" in res2.json()["api_key"]
    assert res2.json()["credits"] == 50

    # Verify storage now contains redemption
    record = storage.get_payment_redemption(sig)
    assert record is not None
    assert record["tx_signature"] == sig


def test_process_restart_preserves_idempotency(tmp_path):
    from storage import StorageManager

    db_path = tmp_path / "restart_test.db"
    sig = SAMPLE_SIGNATURE

    # Process 1
    storage_proc1 = StorageManager(db_path)
    res1 = storage_proc1.redeem_payment(sig, "USDC", 1_000_000, "tier_starter", 50)
    assert res1["status"] == "newly_minted"
    assert res1["credits"] == 50
    assert res1["api_key"] is not None
    prefix1 = res1["key_prefix"]

    # Simulate process termination and restart (new StorageManager instance, fresh memory)
    storage_proc2 = StorageManager(db_path)
    res2 = storage_proc2.redeem_payment(sig, "USDC", 1_000_000, "tier_starter", 50)
    assert res2["status"] == "already_redeemed"
    assert res2["key_prefix"] == prefix1
    assert res2["credits"] == 50
    assert "api_key" not in res2 or res2.get("api_key") is None

    # Verify only 1 key exists in database
    assert storage_proc2.get_active_keys_count() == 1


def test_database_failure_during_redemption_fails_closed(tmp_path):
    import sqlite3
    import pytest
    from storage import StorageManager

    db_path = tmp_path / "db_fail.db"
    storage = StorageManager(db_path)

    # Force SQLite connection to read-only or lock by holding exclusive lock
    conn_blocker = sqlite3.connect(str(db_path))
    conn_blocker.execute("PRAGMA locking_mode = EXCLUSIVE;")
    conn_blocker.execute("BEGIN EXCLUSIVE;")

    # Attempt to redeem payment while DB is locked
    with pytest.raises(sqlite3.OperationalError):
        storage.redeem_payment(SAMPLE_SIGNATURE, "USDC", 1_000_000, "tier_starter", 50)

    conn_blocker.rollback()
    conn_blocker.close()

    # Verify no orphan keys were inserted
    assert storage.get_active_keys_count(max_age_seconds=0) == 0


def test_provider_disagreement_after_finalized_evidence_fails_closed():
    import pytest

    tx_valid = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    tx_error = build_synthetic_solana_tx(
        asset="USDC",
        amount_raw=1_000_000,
        err={"InstructionError": [0, "Custom"]},
    )

    endpoints = ["https://rpc-node-a.com", "https://rpc-node-b.com"]

    def mock_disagree_caller(endpoint, method, params):
        if "rpc-node-a" in endpoint:
            return {"result": tx_valid}
        # Provider B disagrees with an on-chain execution error
        return {"result": tx_error}

    verifier = SolanaPaymentVerifier(
        rpc_endpoints=endpoints,
        rpc_caller=mock_disagree_caller,
        require_consensus=True,
    )

    with pytest.raises(VerificationError) as exc:
        verifier.verify_payment(SAMPLE_SIGNATURE)
    assert "Provider disagreement" in str(exc.value)
    assert "reports execution error" in str(exc.value)

    # Test disagreement on confirmation status (Node B reports confirmed instead of finalized)
    tx_unconfirmed = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000)
    tx_unconfirmed["confirmationStatus"] = "confirmed"

    def mock_unconfirmed_caller(endpoint, method, params):
        if "rpc-node-a" in endpoint:
            return {"result": tx_valid}
        return {"result": tx_unconfirmed}

    verifier2 = SolanaPaymentVerifier(
        rpc_endpoints=endpoints,
        rpc_caller=mock_unconfirmed_caller,
        require_consensus=True,
    )

    with pytest.raises(VerificationError) as exc2:
        verifier2.verify_payment(SAMPLE_SIGNATURE)
    assert "Provider disagreement" in str(exc2.value)
    assert "not finalized" in str(exc2.value)
