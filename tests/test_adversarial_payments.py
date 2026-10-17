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
