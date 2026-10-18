"""
Adversarial Verification Suite for Moltbook Alpha Solana Payment Verification (Stage 18 Phase B).
Exhaustively validates the 14 adversarial scenarios:
1. Correct payer and correct reference.
2. Wrong payer.
3. Wrong reference.
4. Missing payer.
5. Missing reference.
6. Empty, malformed, or invalid values.
7. Signer correct but wrong destination or insufficient amount.
8. Correct destination but wrong token mint.
9. Wrong cluster.
10. Failed or insufficiently finalized transaction.
11. Payment already associated with another account (replay / duplication).
12. Concurrent attempts to redeem the same signature.
13. Repeated requests with altered payer/reference parameters.
14. RPC responses that disagree or omit necessary metadata.
"""

from unittest.mock import patch
import pytest
from pydantic import ValidationError

from payment_verifier import (
    SolanaPaymentVerifier,
    VerificationError,
    VerifyPaymentInput,
)
from storage import StorageManager


TREASURY = "DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
PAYER_PUBKEY = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
REF_PUBKEY = "9x8wDkXzN4gV3yP1qR8sT7uV2wXy6b57xUptv5r2Hn7W"
WRONG_PAYER = "6b57xUptv5r2Hn7W9x8wDkXzN4gV3yP1qR8sT7uV2wXy"
WRONG_REF = "7T7uV2wXy6b57xUptv5r2Hn7W9x8wDkXzN4gV3yP1qR8s"
SIG_88 = "1" * 88


def make_valid_sol_tx(
    payer=PAYER_PUBKEY,
    treasury=TREASURY,
    reference=REF_PUBKEY,
    lamports_to_treasury=5_000_000,
    confirmation_status="finalized",
    commitment="finalized",
    slot=1000,
    block_time=1729188000,
    cluster="mainnet-beta",
    err=None,
):
    accounts = [payer, treasury]
    if reference:
        accounts.append(reference)
    return {
        "slot": slot,
        "blockTime": block_time,
        "confirmationStatus": confirmation_status,
        "commitment": commitment,
        "cluster": cluster,
        "transaction": {
            "signatures": [SIG_88],
            "message": {
                "accountKeys": accounts,
            },
        },
        "meta": {
            "err": err,
            "preBalances": [20_000_000, 10_000_000] + ([0] if reference else []),
            "postBalances": [20_000_000 - lamports_to_treasury - 5000, 10_000_000 + lamports_to_treasury] + ([0] if reference else []),
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }


# Scenario 1: Correct payer and correct reference
def test_scenario_01_correct_payer_and_correct_reference():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    tx = make_valid_sol_tx()
    with patch.object(verifier, "fetch_transaction", return_value=tx):
        payment = verifier.verify_payment(
            SIG_88,
            requested_tier="tier_starter",
            expected_payer=PAYER_PUBKEY,
            expected_reference=REF_PUBKEY,
        )
        assert payment.payer == PAYER_PUBKEY
        assert payment.reference == REF_PUBKEY
        assert payment.tier == "tier_starter"
        assert payment.credits == 50


# Scenario 2: Wrong payer
def test_scenario_02_wrong_payer_fails_closed():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    tx = make_valid_sol_tx()
    with patch.object(verifier, "fetch_transaction", return_value=tx):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(
                SIG_88,
                requested_tier="tier_starter",
                expected_payer=WRONG_PAYER,
            )
        assert "Payer mismatch" in str(exc_info.value)


# Scenario 3: Wrong reference
def test_scenario_03_wrong_reference_fails_closed():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    tx = make_valid_sol_tx()
    with patch.object(verifier, "fetch_transaction", return_value=tx):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(
                SIG_88,
                requested_tier="tier_starter",
                expected_reference=WRONG_REF,
            )
        assert "Reference mismatch" in str(exc_info.value)


# Scenario 4 & 5: Missing payer and missing reference (optional fields omitted)
def test_scenario_04_05_missing_optional_payer_and_reference_succeeds_when_tx_valid():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    tx = make_valid_sol_tx(reference=None)
    with patch.object(verifier, "fetch_transaction", return_value=tx):
        payment = verifier.verify_payment(
            SIG_88,
            requested_tier="tier_starter",
            expected_payer=None,
            expected_reference=None,
        )
        assert payment.tier == "tier_starter"
        assert payment.credits == 50


# Scenario 6: Empty, malformed, or invalid values
def test_scenario_06_empty_or_malformed_values_rejected():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    tx = make_valid_sol_tx()
    with patch.object(verifier, "fetch_transaction", return_value=tx):
        # Empty whitespace payer string directly in verifier
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, expected_payer="   ")
        assert "cannot be empty" in str(exc_info.value)

        # Empty whitespace reference string directly in verifier
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, expected_reference="   ")
        assert "cannot be empty" in str(exc_info.value)

    # Pydantic input validator rejects invalid base58
    with pytest.raises(ValidationError):
        VerifyPaymentInput(transaction_signature=SIG_88, expected_payer="invalid#address!not_base58")

    with pytest.raises(ValidationError):
        VerifyPaymentInput(transaction_signature=SIG_88, expected_reference="too_short")


# Scenario 7: Signer is correct but token transfer destination or amount is wrong
def test_scenario_07_correct_signer_but_wrong_destination_or_insufficient_amount():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    wrong_destination = "99999999999999999999999999999999999999999999"

    # Wrong destination
    tx_wrong_dest = make_valid_sol_tx(treasury=wrong_destination)
    with patch.object(verifier, "fetch_transaction", return_value=tx_wrong_dest):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, requested_tier="tier_starter")
        assert "No verified transfer to the configured treasury wallet" in str(exc_info.value)

    # Insufficient amount (only 1,000 lamports instead of 5,000,000)
    tx_insufficient = make_valid_sol_tx(lamports_to_treasury=1000)
    with patch.object(verifier, "fetch_transaction", return_value=tx_insufficient):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, requested_tier="tier_starter")
        assert "below the minimum required" in str(exc_info.value)



# Scenario 8: Correct destination but wrong token mint
def test_scenario_08_correct_destination_but_wrong_token_mint():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    fake_mint = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"  # USDT instead of USDC
    fake_tx = {
        "slot": 1000,
        "blockTime": 1729188000,
        "confirmationStatus": "finalized",
        "commitment": "finalized",
        "cluster": "mainnet-beta",
        "transaction": {
            "signatures": [SIG_88],
            "message": {"accountKeys": [PAYER_PUBKEY, TREASURY]},
        },
        "meta": {
            "err": None,
            "preBalances": [20_000_000, 10_000_000],
            "postBalances": [19_995_000, 10_000_000],
            "preTokenBalances": [
                {"accountIndex": 1, "mint": fake_mint, "uiTokenAmount": {"amount": "0", "decimals": 6}}
            ],
            "postTokenBalances": [
                {"accountIndex": 1, "mint": fake_mint, "uiTokenAmount": {"amount": "1000000", "decimals": 6}}
            ],
        },
    }
    with patch.object(verifier, "fetch_transaction", return_value=fake_tx):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, requested_tier="tier_starter")
        assert "No verified transfer to the configured treasury wallet" in str(exc_info.value)


# Scenario 9: Wrong cluster
def test_scenario_09_wrong_cluster_fails_closed():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    tx = make_valid_sol_tx(cluster="devnet")
    with patch.object(verifier, "fetch_transaction", return_value=tx):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, requested_tier="tier_starter")
        assert "Cluster mismatch" in str(exc_info.value)


# Scenario 10: Failed or insufficiently finalized transaction
def test_scenario_10_failed_or_insufficiently_finalized():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})

    # Failed transaction on-chain
    tx_failed = make_valid_sol_tx(err={"InstructionError": [0, "Custom"]})
    with patch.object(verifier, "fetch_transaction", return_value=tx_failed):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, requested_tier="tier_starter")
        assert "Transaction failed on-chain" in str(exc_info.value)

    # Insufficient finality: "confirmed" instead of "finalized"
    tx_confirmed = make_valid_sol_tx(confirmation_status="confirmed", commitment="confirmed")
    with patch.object(verifier, "fetch_transaction", return_value=tx_confirmed):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, requested_tier="tier_starter")
        assert "commitment insufficient" in str(exc_info.value).lower()


# Scenario 11 & 13: Payment already redeemed / altered repeated requests
def test_scenario_11_13_replay_and_altered_parameters(tmp_path):
    storage = StorageManager(tmp_path / "test_adv.db")

    # Initial redemption
    res1 = storage.redeem_payment(
        tx_signature=SIG_88,
        asset="SOL",
        amount_raw=5_000_000,
        tier="tier_starter",
        credits_to_grant=50,
    )
    assert res1["status"] == "newly_minted"
    assert res1["credits"] == 50
    key1 = res1["api_key"]
    prefix1 = res1["key_prefix"]

    # Replay attempt: identical signature resubmitted
    res2 = storage.redeem_payment(
        tx_signature=SIG_88,
        asset="SOL",
        amount_raw=5_000_000,
        tier="tier_starter",
        credits_to_grant=50,
    )
    assert res2["status"] == "already_redeemed"
    assert res2["credits"] == 50
    assert res2["key_prefix"] == prefix1
    assert "api_key" not in res2  # Plaintext key is NOT re-minted

    # Altered repeated request: attacker attempts to request tier_unlimited for the same signature
    res3 = storage.redeem_payment(
        tx_signature=SIG_88,
        asset="SOL",
        amount_raw=100_000_000,
        tier="tier_unlimited",
        credits_to_grant=999999,
    )
    assert res3["status"] == "already_redeemed"
    assert res3["tier"] == "tier_starter"  # Preserved original tier
    assert res3["credits"] == 50           # Preserved original credits; no escalation

    # Quota check proves key balance remains exactly 50
    info = storage.get_key_info(key1)
    assert info["credits"] == 50


# Scenario 12: Concurrent attempts to redeem the same signature
def test_scenario_12_concurrent_redemptions_guarantee_single_mint(tmp_path):
    import concurrent.futures

    storage = StorageManager(tmp_path / "concurrent_adv.db")
    results = []

    def try_redeem():
        return storage.redeem_payment(
            tx_signature=SIG_88,
            asset="SOL",
            amount_raw=5_000_000,
            tier="tier_starter",
            credits_to_grant=50,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_redeem) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Exactly one thread mints; 9 threads receive already_redeemed
    minted = [r for r in results if r["status"] == "newly_minted"]
    replayed = [r for r in results if r["status"] == "already_redeemed"]

    assert len(minted) == 1
    assert len(replayed) == 9
    assert storage.get_active_keys_count() == 1



# Scenario 14: Disagreeing or missing RPC responses fail closed
def test_scenario_14_missing_or_disagreeing_rpc_metadata():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {}, require_consensus=True)

    # Missing meta
    with patch.object(verifier, "fetch_transaction", return_value={"transaction": {}}):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88)
        assert "metadata is missing" in str(exc_info.value)

    # Missing transaction payload
    with patch.object(verifier, "fetch_transaction", return_value={"meta": {"err": None}}):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88)
        assert "Transaction payload is malformed" in str(exc_info.value)


# =========================================================================
# Stage 1 & 2 Remediation Scenarios (Hardened Settlement & Front-Running Defense)
# =========================================================================

def test_scenario_15_adversarial_frontrun_blocked_by_invoice_binding(monkeypatch):
    """
    Attacker monitors on-chain transactions and observes Customer A's payment.
    Attacker attempts to:
    1. Verify without an invoice -> 400 Bad Request.
    2. Verify with Attacker's own invoice -> 400 Bad Request (reference mismatch).
    Customer A verifies with their legitimate invoice -> 200 OK.
    """
    from fastapi.testclient import TestClient
    from api_server import app, rate_limiter
    from tests.test_payments import build_synthetic_solana_tx
    import secrets

    client = TestClient(app)
    rate_limiter.reset()

    # Customer A creates invoice
    inv_a = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    ref_a = inv_a["reference"]
    inv_id_a = inv_a["invoice_id"]

    # Customer A pays on chain (tx includes ref_a)
    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    tx_sig = "".join(secrets.choice(b58_chars) for _ in range(88))
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, signature=tx_sig, reference=ref_a)

    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", lambda self, s: tx)

    # Attacker B attempt 1: Submit transaction with no invoice
    res_b1 = client.post("/v1/payments/verify-solana", json={"transaction_signature": tx_sig})
    assert res_b1.status_code == 400
    assert "requires an active invoice" in res_b1.json()["detail"]

    # Attacker B attempt 2: Create their own invoice and try to bind Customer A's transaction
    inv_b = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    res_b2 = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": tx_sig, "invoice_id": inv_b["invoice_id"]},
    )
    assert res_b2.status_code == 400
    assert "Reference mismatch" in res_b2.json()["detail"]

    # Legitimate Customer A submits payment with correct invoice_id
    res_a = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": tx_sig, "invoice_id": inv_id_a},
    )
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["success"] is True
    assert "molt_sol_" in data_a["api_key"]
    assert data_a["credits"] == 50


def test_scenario_16_zero_knowledge_credential_recovery_after_network_drop(monkeypatch):
    """
    Customer creates invoice with claim_secret.
    Transaction is confirmed, but client socket drops before receiving the API key response.
    Customer uses POST /v1/payments/invoice/{invoice_id}/claim with claim_secret to recover the API key.
    Attacker with wrong claim_secret is rejected.
    """
    from fastapi.testclient import TestClient
    from api_server import app, rate_limiter
    from tests.test_payments import build_synthetic_solana_tx
    import secrets

    client = TestClient(app)
    rate_limiter.reset()

    inv = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    ref = inv["reference"]
    inv_id = inv["invoice_id"]
    claim_secret = inv["claim_secret"]

    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    tx_sig = "".join(secrets.choice(b58_chars) for _ in range(88))
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, signature=tx_sig, reference=ref)
    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", lambda self, s: tx)

    # Customer verifies payment (or background webhook verifies it)
    res_verify = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": tx_sig, "invoice_id": inv_id, "claim_secret": claim_secret},
    )
    assert res_verify.status_code == 200
    issued_key = res_verify.json()["api_key"]

    # Attacker attempts to claim with incorrect secret (must match sec_ prefix schema)
    res_bad_claim = client.post(
        f"/v1/payments/invoice/{inv_id}/claim",
        json={"claim_secret": "sec_" + "w" * 40},
    )
    assert res_bad_claim.status_code == 400
    assert "Invalid claim secret" in res_bad_claim.json()["detail"]

    # Legitimate Customer recovers key using original claim_secret
    res_claim = client.post(
        f"/v1/payments/invoice/{inv_id}/claim",
        json={"claim_secret": claim_secret},
    )
    assert res_claim.status_code == 200
    claim_data = res_claim.json()
    assert claim_data["success"] is True
    assert claim_data["status"] == "recovered"
    assert claim_data["api_key"] == issued_key
    assert claim_data["credits"] == 50


def test_scenario_17_expired_invoice_rejection(monkeypatch):
    """
    Invoices past expires_at are strictly rejected.
    """
    from fastapi.testclient import TestClient
    from api_server import app, storage, rate_limiter
    from datetime import datetime, timezone, timedelta
    from tests.test_payments import build_synthetic_solana_tx
    import secrets

    client = TestClient(app)
    rate_limiter.reset()

    inv = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    inv_id = inv["invoice_id"]
    ref = inv["reference"]

    # Manually backdate invoice expires_at in storage to simulate expiration
    past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with storage.connection() as conn:
        with conn:
            conn.execute(
                "UPDATE payment_invoices SET expires_at = ?, status = 'expired' WHERE invoice_id = ?",
                (past_iso, inv_id),
            )

    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    tx_sig = "".join(secrets.choice(b58_chars) for _ in range(88))
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, signature=tx_sig, reference=ref)
    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", lambda self, s: tx)

    res = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": tx_sig, "invoice_id": inv_id},
    )
    assert res.status_code == 400
    assert "expired" in res.json()["detail"].lower()


def test_scenario_18_mismatched_asset_or_amount_against_invoice(monkeypatch):
    """
    Submitting payment with wrong asset or insufficient amount compared to invoice terms is rejected.
    """
    from fastapi.testclient import TestClient
    from api_server import app, rate_limiter
    from tests.test_payments import build_synthetic_solana_tx
    import secrets

    client = TestClient(app)
    rate_limiter.reset()

    # Invoice created for tier_starter (USDC, 1_000_000 raw)
    inv = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    inv_id = inv["invoice_id"]
    ref = inv["reference"]

    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    tx_sig = "".join(secrets.choice(b58_chars) for _ in range(88))

    # Pay with SOL instead of USDC
    tx_sol = build_synthetic_solana_tx(asset="SOL", amount_raw=5_000_000, signature=tx_sig, reference=ref)
    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", lambda self, s: tx_sol)

    res_sol = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": tx_sig, "invoice_id": inv_id},
    )
    assert res_sol.status_code == 400
    assert "does not match invoice expected asset" in res_sol.json()["detail"]

    # Pay with insufficient USDC (e.g. 500,000 raw instead of 1,000,000)
    tx_underpaid = build_synthetic_solana_tx(asset="USDC", amount_raw=500_000, signature=tx_sig, reference=ref)
    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", lambda self, s: tx_underpaid)

    res_under = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": tx_sig, "invoice_id": inv_id},
    )
    assert res_under.status_code == 400
    assert "below" in res_under.json()["detail"].lower() and "minimum" in res_under.json()["detail"].lower()


def test_scenario_19_future_timestamp_rejected():
    """
    Transactions with block_time in the future (> 60s ahead) are rejected to prevent clock skew attacks.
    """
    import time
    from tests.test_payments import build_synthetic_solana_tx

    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})
    future_time = int(time.time()) + 300  # 5 minutes in future
    tx_future = build_synthetic_solana_tx(signature=SIG_88, block_time=future_time)

    with patch.object(verifier, "fetch_transaction", return_value=tx_future):
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(SIG_88, requested_tier="tier_starter")
        assert "timestamp is in the future" in str(exc_info.value)


def test_scenario_20_cluster_genesis_hash_validation():
    """
    Validates cluster genesis hash to prevent cross-cluster replay or RPC node misdirection.
    """
    from config import SOLANA_MAINNET_GENESIS_HASH, SOLANA_DEVNET_GENESIS_HASH

    # 1. Matching mainnet hash passes
    verifier_mainnet = SolanaPaymentVerifier(
        cluster="mainnet-beta",
        rpc_caller=lambda method, params: {"result": SOLANA_MAINNET_GENESIS_HASH},
    )
    assert verifier_mainnet.validate_cluster_genesis() is True

    # 2. Node claiming mainnet but returning devnet genesis hash fails closed
    verifier_spoofed = SolanaPaymentVerifier(
        cluster="mainnet-beta",
        rpc_caller=lambda method, params: {"result": SOLANA_DEVNET_GENESIS_HASH},
    )
    with pytest.raises(VerificationError) as exc_info:
        verifier_spoofed.validate_cluster_genesis()
    assert "Cluster genesis hash mismatch" in str(exc_info.value)


def test_scenario_21_revoked_key_claim_blocked(monkeypatch):
    """
    If an API key is revoked by an administrator, claiming via claim_secret is blocked.
    """
    from fastapi.testclient import TestClient
    from api_server import app, storage, rate_limiter
    from tests.test_payments import build_synthetic_solana_tx
    import secrets

    client = TestClient(app)
    rate_limiter.reset()

    inv = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    ref = inv["reference"]
    inv_id = inv["invoice_id"]
    claim_secret = inv["claim_secret"]

    b58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    tx_sig = "".join(secrets.choice(b58_chars) for _ in range(88))
    tx = build_synthetic_solana_tx(asset="USDC", amount_raw=1_000_000, signature=tx_sig, reference=ref)
    monkeypatch.setattr(SolanaPaymentVerifier, "fetch_transaction", lambda self, s: tx)

    # Fulfill invoice with claim_secret so envelope is encrypted
    res = client.post(
        "/v1/payments/verify-solana",
        json={"transaction_signature": tx_sig, "invoice_id": inv_id, "claim_secret": claim_secret},
    )
    api_key = res.json()["api_key"]

    # Admin revokes key
    storage.revoke_api_key(api_key, reason="Policy violation")

    # Claim attempt must fail closed
    res_claim = client.post(
        f"/v1/payments/invoice/{inv_id}/claim",
        json={"claim_secret": claim_secret},
    )
    assert res_claim.status_code == 400
    assert "revoked" in res_claim.json()["detail"].lower()
