"""
Unit tests for Proof of Agent (PoA) Bounty Runner (bounties/poa_runner.py).
"""

import json
from unittest.mock import MagicMock, patch

from ops.poa_runner import (
    PoAProtocolClient,
    PoABountyRunner,
    BOUNTY_EPOCH_CUTOFF_TS,
    DEFAULT_TARGET_BTC
)


def test_pow_solver():
    """Verify that solve_pow generates a hash with the required number of leading zero bits."""
    challenge = "test_challenge_123"
    bits = 12
    nonce = PoAProtocolClient.solve_pow(challenge, bits=bits)
    assert isinstance(nonce, str)

    # Verify sha256 leading bits
    import hashlib
    candidate = f"{challenge}:{nonce}".encode("utf-8")
    digest = hashlib.sha256(candidate).digest()
    zero_bits = 0
    for b in digest:
        if b == 0:
            zero_bits += 8
        else:
            zero_bits += (8 - b.bit_length())
            break
    assert zero_bits >= bits


def test_generate_sybil_answer_format_and_words():
    """Verify Sybil answer generation includes all words and meets length constraints."""
    words = ["orchard", "basalt", "wander"]
    answer = PoAProtocolClient.generate_sybil_answer(words)

    assert 120 <= len(answer) <= 600
    for w in words:
        assert w in answer


def test_register_handles_503_gracefully():
    """Verify register handles network 503 paused state without unhandled exceptions."""
    client = PoAProtocolClient(base_url="https://mockpoa.com")

    with patch.object(client, "fetch_join_pow", return_value={"success": True, "challenge": "abc", "bits": 4}), \
         patch.object(client, "solve_pow", return_value="1"), \
         patch.object(client, "_http_request", return_value=(503, {"error": "API hardening in progress", "notice": {"msg": "paused"}}, "paused")):
        res = client.register(label="TestBot")
        assert res["success"] is False
        assert res["status"] == 503
        assert res["network_paused"] is True
        assert "API hardening" in res["error"]


def test_register_success():
    """Verify successful identity registration returns key and address."""
    client = PoAProtocolClient(base_url="https://mockpoa.com")

    mock_resp = {
        "api_key": "pk_test_12345678",
        "poa_address": "poa1mockaddressabcdef123456",
        "label": "TestBot"
    }

    with patch.object(client, "fetch_join_pow", return_value={"success": True, "challenge": "abc", "bits": 4}), \
         patch.object(client, "solve_pow", return_value="1"), \
         patch.object(client, "_http_request", return_value=(200, mock_resp, None)):
        res = client.register(label="TestBot")
        assert res["success"] is True
        assert res["api_key"] == "pk_test_12345678"
        assert res["poa_address"] == "poa1mockaddressabcdef123456"


def test_verify_qualification_insufficient_epochs():
    """Verify qualification fails when fewer than 3 epochs closed after the cutoff timestamp."""
    client = PoAProtocolClient()
    mock_address = "poa1testaddress"
    mock_txs = [
        # Epoch before cutoff
        {"id": "tx1", "from_addr": mock_address, "epoch": 1, "ts": BOUNTY_EPOCH_CUTOFF_TS - 1000, "final": 1, "atts": 10},
        # Epoch after cutoff
        {"id": "tx2", "from_addr": mock_address, "epoch": 2, "ts": BOUNTY_EPOCH_CUTOFF_TS + 1000, "final": 1, "atts": 8, "memo": f"aibtc:{DEFAULT_TARGET_BTC}"}
    ]

    with patch.object(client, "fetch_poascan_txs", return_value=mock_txs):
        audit = client.verify_qualification(mock_address, target_btc=DEFAULT_TARGET_BTC)
        assert audit["criteria_1_address_valid"] is True
        assert audit["distinct_epochs_count"] == 1
        assert audit["criteria_2_three_epochs_verified"] is False
        assert audit["criteria_3_memo_bound"] is True
        assert audit["fully_qualified"] is False


def test_verify_qualification_full_success():
    """Verify qualification succeeds with 3 distinct finalized epochs post-cutoff and matching memo."""
    client = PoAProtocolClient()
    mock_address = "poa1qualifiedaddress"
    mock_txs = [
        {"id": "tx1", "from_addr": mock_address, "epoch": 2, "ts": BOUNTY_EPOCH_CUTOFF_TS + 100, "final": 1, "atts": 10},
        {"id": "tx2", "from_addr": mock_address, "epoch": 3, "ts": BOUNTY_EPOCH_CUTOFF_TS + 200, "final": 1, "atts": 12},
        {"id": "tx3", "from_addr": mock_address, "epoch": 4, "ts": BOUNTY_EPOCH_CUTOFF_TS + 300, "final": 1, "atts": 9, "memo": f"aibtc:{DEFAULT_TARGET_BTC}"}
    ]

    with patch.object(client, "fetch_poascan_txs", return_value=mock_txs):
        audit = client.verify_qualification(mock_address, target_btc=DEFAULT_TARGET_BTC)
        assert audit["distinct_epochs_count"] == 3
        assert audit["criteria_2_three_epochs_verified"] is True
        assert audit["criteria_3_memo_bound"] is True
        assert audit["fully_qualified"] is True
        assert audit["matching_memo_tx"]["id"] == "tx3"


def test_runner_state_persistence_and_cycle(tmp_path):
    """Verify PoABountyRunner loads and writes persistent state."""
    state_file = tmp_path / "test_state.json"
    client = MagicMock(spec=PoAProtocolClient)
    client.register.return_value = {
        "success": False,
        "status": 503,
        "network_paused": True,
        "error": "PoA API hardening in progress; endpoints temporarily paused."
    }

    runner = PoABountyRunner(state_file=state_file, client=client)
    res = runner.run_cycle()

    assert res["status"] == "NETWORK_PAUSED"
    assert state_file.exists()

    with open(state_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["status"] == "NETWORK_PAUSED"
    assert saved["network_paused"] is True


def test_runner_build_submission_report(tmp_path):
    """Verify submission deliverable markdown generation."""
    state_file = tmp_path / "test_state.json"
    runner = PoABountyRunner(state_file=state_file)
    runner.state["poa_address"] = "poa1testrecipient123"
    runner.state["memo_tx_id"] = "memo_tx_hash_98765"

    mock_audit = {
        "distinct_epochs_count": 3,
        "matching_memo_tx": {"id": "memo_tx_hash_98765"},
        "epoch_details": [
            {"epoch": 2, "type": "challenge", "tx_id": "tx_ep2", "atts": 15, "iso": "2026-10-25T14:00:00Z"},
            {"epoch": 3, "type": "challenge", "tx_id": "tx_ep3", "atts": 18, "iso": "2026-10-25T20:00:00Z"},
            {"epoch": 4, "type": "challenge", "tx_id": "tx_ep4", "atts": 12, "iso": "2026-10-26T02:00:00Z"}
        ]
    }

    report = runner.build_submission_report(mock_audit)
    assert "poa1testrecipient123" in report
    assert "memo_tx_hash_98765" in report
    assert "Epoch 2" in report
    assert "Epoch 3" in report
    assert "Epoch 4" in report
    assert DEFAULT_TARGET_BTC in report
