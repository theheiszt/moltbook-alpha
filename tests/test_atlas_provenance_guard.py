"""
Unit tests for ATLAS Provenance Guard & Anti-Pope Firewall.
Document Reference: ATLAS-SEC-SPEC-2026-001
"""

import tempfile
from pathlib import Path
import pytest

from ops.security.atlas_provenance_guard import (
    ATLASCapabilityToken,
    AntiPopeGate,
    OutOfBandProvenanceWitness,
    DEUSPROOFAnchorBridge,
    AtlasProvenanceGuard,
    UnauthorizedOrdinationError,
    TamperDetectedError,
    InvalidCapabilityTokenError,
    ReplayAttackError,
)
from cryptographic_witness import WitnessKeyManager


def test_anti_pope_gate_rejects_context_compression():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_sec.db"
        key_mgr = WitnessKeyManager()
        gate = AntiPopeGate(db_path=db_path, trusted_issuers={"did:key:host": key_mgr.public_key_base58})

        with pytest.raises(UnauthorizedOrdinationError) as exc_info:
            gate.authorize_action(
                capability="coinbase:place_order",
                target_resource="SOL-USDC",
                parameters={"side": "BUY", "amount": 2.70},
                token=None,
                context_justification="Previous turn summary indicated user wanted to trade $2.70",
            )
        assert "cannot ordain permissions" in str(exc_info.value)
        assert "Remembered intent in context compression is not an execution grant" in str(exc_info.value)


def test_capability_token_valid_grant():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_sec.db"
        key_mgr = WitnessKeyManager()
        gate = AntiPopeGate(db_path=db_path, trusted_issuers={"did:key:host": key_mgr.public_key_base58})

        params = {"side": "BUY", "amount": 2.70}
        token = ATLASCapabilityToken(
            capability="coinbase:place_order",
            target_resource="SOL-USDC",
            parameters=params,
            issuer_did="did:key:host",
            ttl_seconds=300,
        )
        token.sign(key_mgr)

        auth = gate.authorize_action(
            capability="coinbase:place_order",
            target_resource="SOL-USDC",
            parameters=params,
            token=token,
        )
        assert auth["authorized"] is True
        assert auth["token_id"] == token.token_id
        assert auth["capability"] == "coinbase:place_order"


def test_anti_pope_gate_blocks_replay_attack():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_sec.db"
        key_mgr = WitnessKeyManager()
        gate = AntiPopeGate(db_path=db_path, trusted_issuers={"did:key:host": key_mgr.public_key_base58})

        params = {"side": "BUY", "amount": 2.70}
        token = ATLASCapabilityToken(
            capability="coinbase:place_order",
            target_resource="SOL-USDC",
            parameters=params,
            issuer_did="did:key:host",
            ttl_seconds=300,
        )
        token.sign(key_mgr)

        # First consumption succeeds
        gate.authorize_action(
            capability="coinbase:place_order",
            target_resource="SOL-USDC",
            parameters=params,
            token=token,
        )

        # Second consumption with identical nonce MUST fail
        with pytest.raises(ReplayAttackError) as exc_info:
            gate.authorize_action(
                capability="coinbase:place_order",
                target_resource="SOL-USDC",
                parameters=params,
                token=token,
            )
        assert "Replay Attack Blocked" in str(exc_info.value)


def test_capability_token_rejects_parameter_tampering():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_sec.db"
        key_mgr = WitnessKeyManager()
        gate = AntiPopeGate(db_path=db_path, trusted_issuers={"did:key:host": key_mgr.public_key_base58})

        granted_params = {"side": "BUY", "amount": 1.00}
        token = ATLASCapabilityToken(
            capability="coinbase:place_order",
            target_resource="SOL-USDC",
            parameters=granted_params,
            issuer_did="did:key:host",
            ttl_seconds=300,
        )
        token.sign(key_mgr)

        tampered_params = {"side": "BUY", "amount": 2.70}
        with pytest.raises(InvalidCapabilityTokenError) as exc_info:
            gate.authorize_action(
                capability="coinbase:place_order",
                target_resource="SOL-USDC",
                parameters=tampered_params,
                token=token,
            )
        assert "Parameter tampering detected" in str(exc_info.value)


def test_out_of_band_witness_detects_in_sandbox_tampering():
    key_mgr = WitnessKeyManager()
    witness = OutOfBandProvenanceWitness(key_manager=key_mgr)

    witness.propose_event("EVENT_A", "agent:worker-alpha", {"val": 100})
    witness.propose_event("EVENT_B", "agent:worker-alpha", {"val": 200})

    tampered_journal = [dict(r) for r in witness._journal]
    tampered_journal[0]["payload"] = {"val": 999}

    with pytest.raises(TamperDetectedError) as exc_info:
        witness.verify_chain_integrity(candidate_journal=tampered_journal)
    assert "Payload tampering detected" in str(exc_info.value)


def test_deusproof_merkle_root_and_l1_anchor():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_sec.db"
        bridge = DEUSPROOFAnchorBridge(db_path=db_path)

        leaves = [
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        ]
        merkle_root = bridge.compute_merkle_root(leaves)
        assert len(merkle_root) == 64

        anchor = bridge.anchor_epoch(
            epoch_date="2026-10-25",
            leaf_hashes=leaves,
            bitcoin_block_height=867530,
            bitcoin_block_hash="00000000000000000002a9b4c8d7e6f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7",
        )
        assert anchor["merkle_root"] == merkle_root
        assert anchor["status"] == "L1_CONFIRMED"
        assert anchor["bitcoin_block_height"] == 867530


def test_atlas_provenance_guard_orchestration():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_sec.db"
        guard = AtlasProvenanceGuard(db_path=db_path)

        params = {"side": "SELL", "amount": 0.0265}
        token = ATLASCapabilityToken(
            capability="solana:broadcast_swap",
            target_resource="SOL-USDC",
            parameters=params,
            issuer_did="did:key:host",
            ttl_seconds=300,
        )
        token.sign(guard.key_manager)

        def mock_trade():
            return {"tx": "sig_mock_solana_123"}

        res = guard.guard_execution(
            capability="solana:broadcast_swap",
            target_resource="SOL-USDC",
            parameters=params,
            token=token,
            execution_callable=mock_trade,
        )

        assert res["success"] is True
        assert res["result"]["tx"] == "sig_mock_solana_123"
        assert res["state_witness"]["sequence"] == 1
        assert res["state_witness"]["event_type"] == "EXECUTE_SOLANA:BROADCAST_SWAP"
