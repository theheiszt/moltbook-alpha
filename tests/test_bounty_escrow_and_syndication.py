"""
Unit tests for On-Chain Escrow Lockup and Moltbook Submolt Syndication
(ops/bounty_escrow.py, ops/bounty_syndicator.py, and job_board.py integration).
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from storage import StorageManager
from job_board import AgentJobBoardManager, JobPostRequest, JobSubmissionRequest
from ops.bounty_escrow import BountyEscrowManager
from ops.bounty_syndicator import BountySyndicator


@pytest.fixture
def test_storage(tmp_path):
    db_file = tmp_path / "test_escrow.db"
    return StorageManager(db_file)


def test_escrow_create_and_lock(test_storage):
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


def test_escrow_release_on_verified_witness(test_storage):
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
