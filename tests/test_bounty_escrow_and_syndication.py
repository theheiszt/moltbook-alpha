"""
Unit tests for On-Chain Escrow Lockup and Moltbook Submolt Syndication
(ops/bounty_escrow.py, ops/bounty_syndicator.py, and job_board.py integration).
"""

import pytest
from unittest.mock import MagicMock

from storage import StorageManager
from job_board import AgentJobBoardManager, JobPostRequest, JobSubmissionRequest
from ops.bounty_escrow import BountyEscrowManager
from ops.bounty_syndicator import BountySyndicator


@pytest.fixture
def test_storage(tmp_path):
    db_file = tmp_path / "test_escrow.db"
    return StorageManager(db_file)


@pytest.fixture
def allow_mock_escrow(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_ESCROW_ALLOW_MOCK", "1")


def _new_job(test_storage, reward=0.05):
    mgr = AgentJobBoardManager(storage_manager=test_storage)
    return mgr.create_job(
        JobPostRequest(
            title="Escrow Deposit Verification Task",
            description="Verify that escrow locks only after a real on-chain deposit is observed.",
            category="quant_research",
            reward_amount=reward,
            reward_asset="SOL",
            verification_criteria="Detailed markdown proof required.",
        ),
        caller_actor="test_poster",
    )


def _deposit_tx(escrow, lamports, include_reference=True, err=None):
    keys = [{"pubkey": "PayerWa11et1111111111111111111111111111111"}, {"pubkey": escrow["escrow_address"]}]
    if include_reference:
        keys.append({"pubkey": escrow["reference_pubkey"]})
    return {"result": {
        "meta": {"err": err, "preBalances": [10_000_000_000, 1_000, 0],
                 "postBalances": [10_000_000_000 - lamports - 5000, 1_000 + lamports, 0]},
        "transaction": {"message": {"accountKeys": keys}},
    }}


def _fake_rpc(txs):
    """txs maps signature -> getTransaction response; reference search returns all signatures."""
    def call(method, params, timeout=12):
        if method == "getTransaction":
            return txs.get(params[0], {"result": None})
        if method == "getSignaturesForAddress":
            return {"result": [{"signature": s, "err": None} for s in txs]}
        return None
    return call


def test_mock_signature_rejected_without_opt_in(test_storage, monkeypatch):
    monkeypatch.delenv("MOLTBOOK_ESCROW_ALLOW_MOCK", raising=False)
    job = _new_job(test_storage)
    escrow_mgr = BountyEscrowManager(storage_manager=test_storage)
    monkeypatch.setattr(escrow_mgr, "rpc_call", _fake_rpc({}))
    res = escrow_mgr.verify_and_lock_deposit(job["job_id"], deposit_tx_sig="mock_free_money")
    assert res["success"] is False
    assert escrow_mgr.get_escrow(job["job_id"])["status"] == "UNFUNDED"


def test_real_deposit_locks_escrow(test_storage, monkeypatch):
    job = _new_job(test_storage)
    escrow_mgr = BountyEscrowManager(storage_manager=test_storage)
    escrow = escrow_mgr.get_escrow(job["job_id"])
    monkeypatch.setattr(escrow_mgr, "rpc_call", _fake_rpc({"sigGood": _deposit_tx(escrow, 50_000_000)}))
    res = escrow_mgr.verify_and_lock_deposit(job["job_id"], deposit_tx_sig="sigGood")
    assert res["success"] is True
    assert res["escrow"]["status"] == "LOCKED" and res["escrow"]["deposit_tx_sig"] == "sigGood"


@pytest.mark.parametrize("tx_kwargs", [
    {"lamports": 49_999_999},                              # underpaid
    {"lamports": 50_000_000, "include_reference": False},  # not this escrow's deposit
    {"lamports": 50_000_000, "err": {"InstructionError": [0, "Custom"]}},  # failed tx
])
def test_bad_deposit_does_not_lock(test_storage, monkeypatch, tx_kwargs):
    job = _new_job(test_storage)
    escrow_mgr = BountyEscrowManager(storage_manager=test_storage)
    escrow = escrow_mgr.get_escrow(job["job_id"])
    monkeypatch.setattr(escrow_mgr, "rpc_call", _fake_rpc({"sigBad": _deposit_tx(escrow, **tx_kwargs)}))
    res = escrow_mgr.verify_and_lock_deposit(job["job_id"], deposit_tx_sig="sigBad")
    assert res["success"] is False
    assert escrow_mgr.get_escrow(job["job_id"])["status"] == "UNFUNDED"


def test_deposit_signature_cannot_fund_two_escrows(test_storage, monkeypatch):
    job_a, job_b = _new_job(test_storage), _new_job(test_storage)
    escrow_mgr = BountyEscrowManager(storage_manager=test_storage)
    esc_a, esc_b = escrow_mgr.get_escrow(job_a["job_id"]), escrow_mgr.get_escrow(job_b["job_id"])
    # One transaction that (somehow) references both escrows and pays enough for each
    tx = _deposit_tx(esc_a, 50_000_000)
    tx["result"]["transaction"]["message"]["accountKeys"].append({"pubkey": esc_b["reference_pubkey"]})
    monkeypatch.setattr(escrow_mgr, "rpc_call", _fake_rpc({"sigShared": tx}))
    assert escrow_mgr.verify_and_lock_deposit(job_a["job_id"], deposit_tx_sig="sigShared")["success"] is True
    assert escrow_mgr.verify_and_lock_deposit(job_b["job_id"], deposit_tx_sig="sigShared")["success"] is False


def test_escrow_create_and_lock(test_storage, allow_mock_escrow):
    """Verify creating and locking an on-chain bounty escrow."""
    mgr = AgentJobBoardManager(storage_manager=test_storage)
    job = mgr.create_job(
        JobPostRequest(
            title="Solana Escrow Bounty Test Task",
            description="Perform on-chain liquidity verification and report findings in detail.",
            category="quant_research",
            reward_amount=0.05,
            reward_asset="SOL",
            verification_criteria="Detailed markdown proof required.",
        ),
        caller_actor="test_poster"
    )

    escrow_mgr = BountyEscrowManager(storage_manager=test_storage)
    escrow = escrow_mgr.get_escrow(job["job_id"])
    assert escrow is not None
    assert escrow["status"] == "UNFUNDED"
    assert escrow["amount_lamports"] == 50_000_000
    assert escrow["amount_sol"] == 0.05
    assert len(escrow["reference_pubkey"]) >= 32
    assert "solana:" in escrow_mgr.create_escrow(job["job_id"], 0.05)["solana_pay_url"]

    # Verify and lock deposit
    lock_res = escrow_mgr.verify_and_lock_deposit(job["job_id"], deposit_tx_sig="mock_dep_tx_123456")
    assert lock_res["success"] is True
    assert lock_res["escrow"]["status"] == "LOCKED"
    assert lock_res["escrow"]["deposit_tx_sig"] == "mock_dep_tx_123456"


def test_escrow_release_on_verified_witness(test_storage, allow_mock_escrow):
    """Verify escrow releases to worker upon verified deliverable with Ed25519 witness."""
    mgr = AgentJobBoardManager(storage_manager=test_storage)
    job = mgr.create_job(
        JobPostRequest(
            title="Compute Empirical High-Frequency Volatility Surface",
            description="Compute hourly log-return standard deviation (sigma_1h) and spread for token pairs.",
            category="quant_research",
            reward_amount=0.02,
            reward_asset="SOL",
            verification_criteria="Deliverable summary must include sigma_1h.",
        ),
        caller_actor="test_poster"
    )

    escrow_mgr = BountyEscrowManager(storage_manager=test_storage)
    escrow_mgr.verify_and_lock_deposit(job["job_id"], deposit_tx_sig="mock_dep_tx_999")

    # Worker submits deliverable
    worker_payout_addr = "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx"
    sub_res = mgr.submit_deliverable(
        job["job_id"],
        JobSubmissionRequest(
            worker_agent="@quant_agent_worker",
            deliverable_uri="https://github.com/my-worker/verified-solution",
            deliverable_summary="Extensive analysis of high frequency volatility surface across Raydium CLMM slots demonstrating empirical convergence.",
            payout_address_or_key=worker_payout_addr
        )
    )

    assert sub_res["success"] is True
    assert sub_res["status"] == "VERIFIED_AND_ESCROW_SETTLED"
    assert "escrow_settlement" in sub_res
    settlement = sub_res["escrow_settlement"]
    assert settlement["success"] is True
    assert settlement["recipient_address"] == worker_payout_addr
    assert settlement["payout_lamports"] == 20_000_000 - 5000  # minus fee
    assert "release_tx_sig" in settlement

    # Check updated escrow state
    escrow = escrow_mgr.get_escrow(job["job_id"])
    assert escrow["status"] == "RELEASED"
    assert escrow["release_tx_sig"] is not None
    assert escrow["recipient_address"] == worker_payout_addr

    # Check job completed
    updated_job = mgr.get_job(job["job_id"])
    assert updated_job["status"] == "COMPLETED"


def test_bounty_syndicator_format_and_publish(test_storage):
    """Verify submolt announcement formatting and publishing via syndicator."""
    mgr = AgentJobBoardManager(storage_manager=test_storage)
    job = mgr.create_job(
        JobPostRequest(
            title="Test Submolt Syndication Bounty",
            description="Analyze security replay vectors on agent memory logs.",
            category="security_audit",
            reward_amount=0.01,
            reward_asset="SOL",
            verification_criteria="Detailed reproduction trace.",
        ),
        caller_actor="test_poster"
    )

    mock_moltbook = MagicMock()
    mock_moltbook.create_post.return_value = ({"post": {"id": "post_molt_12345"}}, True)

    syndicator = BountySyndicator(storage_manager=test_storage, moltbook_client=mock_moltbook)
    res = syndicator.syndicate_bounty(job["job_id"], submolt="forhire")

    assert res["success"] is True
    assert res["moltbook_post_id"] == "post_molt_12345"
    assert res["submolt"] == "forhire"
    assert "post_url" in res

    # Verify duplicate prevention
    dup = syndicator.syndicate_bounty(job["job_id"], submolt="forhire")
    assert dup["already_syndicated"] is True
    assert dup["moltbook_post_id"] == "post_molt_12345"
    assert mock_moltbook.create_post.call_count == 1
