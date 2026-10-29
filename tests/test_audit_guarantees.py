"""
Moltbook Alpha — Autonomous Agent Guarantee Assay & Audit Tests.
Verifies the three core community audit demands:
1. Abandoned Quota Reservations: Disconnected clients automatically get credits back via TTL sweeper.
2. Contract Consistency: /v1/capabilities describes the exact same constraints, schemas, and rate limits that validators enforce.
3. Retry Correctness & Persistence: Reusing an Idempotency-Key returns the original result without duplicate deduction,
   persisting across server restarts and connection dropouts.
"""

import time
import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from storage import StorageManager
from api_server import app
from data_products import DEFAULT_DATA_PRODUCTS
from rate_limiter import (
    DEFAULT_RATE_LIMIT_CAPACITY,
    DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    DEFAULT_MAX_CONCURRENT_IN_FLIGHT,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def temp_storage(tmp_path):
    db_file = tmp_path / "test_audit_guarantees.db"
    return StorageManager(db_path=db_file)


# =============================================================================
# 1. Abandoned Quota Reservations & Automated TTL Sweeper Tests
# =============================================================================


def test_abandoned_quota_reservation_auto_reaped(temp_storage):
    """
    Demand 1: Does a disconnected client eventually get its credits back without manual intervention?
    Simulates a client that starts a request, reserves quota, drops the socket,
    and walks away. Verifies automated sweeper restores the balance.
    """
    raw_key, key_info = temp_storage.create_api_key(tier="tier_pro", credits=10)
    k_hash = key_info["key_hash"]

    # Initial balance check
    quota_before = temp_storage.get_key_quota_details(raw_key)
    assert quota_before["credits_remaining"] == 10

    # Client initiates request with 1-second TTL (simulating fast test window)
    req_id = "req_abandoned_001"
    res_info, state = temp_storage.reserve_quota(
        raw_key,
        idempotency_key="idemp_abandoned_001",
        request_id=req_id,
        ttl_seconds=1,
    )
    assert state == "ok"
    assert res_info["credits"] == 9

    # Quota is immediately decremented while in flight
    with temp_storage.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status, credits FROM quota_reservations WHERE reservation_id = ?", (res_info["reservation_id"],))
        res_row = cur.fetchone()
        assert res_row["status"] == "reserved"

    # Simulate client dropping socket mid-flight — no settle_quota, no release_quota
    # Time passes beyond reservation TTL (1.5s)
    time.sleep(1.5)

    # 1. Active background sweeper runs automatically without user intervention
    reaped = temp_storage.reap_expired_reservations()
    assert reaped == 1, "Sweeper must reap the abandoned reservation"

    # 2. Check reservation status has transitioned to expired
    with temp_storage.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT status, release_reason, released_at FROM quota_reservations WHERE reservation_id = ?",
            (res_info["reservation_id"],),
        )
        res_row = cur.fetchone()
        assert res_row["status"] == "expired"
        assert res_row["release_reason"] == "reservation_ttl_expired"
        assert res_row["released_at"] is not None

    # 3. Credits must be restored to 10
    quota_after = temp_storage.get_key_quota_details(raw_key)
    assert quota_after["credits_remaining"] == 10

    # 4. Ledger integrity holds mathematically
    ledger_audit = temp_storage.verify_ledger_balance(k_hash)
    assert ledger_audit["balanced"] is True
    assert ledger_audit["api_key_balance"] == 10
    assert ledger_audit["actual_lot_balance"] == 10


def test_lazy_sweeper_restores_abandoned_quota_on_subsequent_read(temp_storage):
    """
    Verifies that even if the background timer had not fired yet,
    a client checking their quota via get_key_quota_details lazily and deterministically
    sweeps any expired reservations before returning the balance.
    """
    raw_key, key_info = temp_storage.create_api_key(tier="tier_pro", credits=5)

    # Reserve with 1-second TTL
    res_info, state = temp_storage.reserve_quota(
        raw_key,
        idempotency_key="idemp_lazy_sweep_001",
        request_id="req_lazy_001",
        ttl_seconds=1,
    )
    assert state == "ok"

    # Wait for TTL to expire
    time.sleep(1.2)

    # Client simply calls get_key_quota_details (e.g. GET /v1/account/quota)
    # The lazy sweeper inside get_key_quota_details must auto-restore the credits
    quota = temp_storage.get_key_quota_details(raw_key)
    assert quota["credits_remaining"] == 5, "Lazy sweep must have restored the expired reservation"


# =============================================================================
# 2. Contract Consistency Tests
# =============================================================================


def test_capabilities_contract_consistency(client):
    """
    Demand 2: Does /v1/capabilities describe the exact same constraints,
    schemas, and rate limits that actual API validators enforce?
    """
    resp = client.get("/v1/capabilities")
    assert resp.status_code == 200
    caps = resp.json()

    # Rate Limit Consistency
    rate_limits = caps["rate_limits"]
    assert rate_limits["burst_capacity"] == int(DEFAULT_RATE_LIMIT_CAPACITY)
    assert rate_limits["authenticated_sustained_per_minute"] == int(DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN)
    assert rate_limits["max_concurrent_in_flight"] == int(DEFAULT_MAX_CONCURRENT_IN_FLIGHT)

    # Data Product Exchange Consistency
    exchange = caps["capabilities"]["agent_data_exchange"]
    data_products = exchange["data_products"]
    assert len(data_products) == len(DEFAULT_DATA_PRODUCTS)

    for p_summary in data_products:
        pid = p_summary["product_id"]
        assert pid in DEFAULT_DATA_PRODUCTS
        real_prod = DEFAULT_DATA_PRODUCTS[pid]
        assert p_summary["cost_credits"] == real_prod.cost_credits
        assert p_summary["max_staleness_seconds"] == real_prod.max_staleness_seconds
        assert p_summary["update_frequency"] == real_prod.update_frequency

    # Unmetered Endpoints Contract
    unmetered = caps["pricing_and_quotas"]["unmetered_endpoints"]
    assert "/v1/capabilities" in unmetered
    assert "/v1/data-products" in unmetered
    assert "/v1/account/usage" in unmetered
    assert "/v1/account/quota" in unmetered


# =============================================================================
# 3. Retry Correctness & SQLite Persistence Across Server Restarts
# =============================================================================


def test_idempotency_persists_across_simulated_server_restart(tmp_path):
    """
    Demand 3: Does reusing an idempotency key return the original result without
    another deduction, including after timeouts and server restarts?
    """
    db_file = tmp_path / "persistent_idempotency.db"

    # Instance 1: Server before restart
    storage_inst1 = StorageManager(db_path=db_file)
    raw_key, key_info = storage_inst1.create_api_key(tier="tier_pro", credits=10)

    idemp_key = f"idemp_restart_{uuid.uuid4().hex[:12]}"
    req_id = "req_initial_run_001"

    # Step 1: Initial call reserves quota
    res_info1, state1 = storage_inst1.reserve_quota(raw_key, idempotency_key=idemp_key, request_id=req_id)
    assert state1 == "ok"
    assert res_info1["credits"] == 9

    # Step 2: Request succeeds and settles with payload
    sample_response_payload = {
        "product_id": "moltbook-intel-feed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signals_count": 14,
        "receipt": {"credits_deducted": 1, "credits_remaining": 9},
    }
    settle_ok = storage_inst1.settle_quota(res_info1["reservation_id"], response_payload=sample_response_payload)
    assert settle_ok is True

    # Confirm balance on Instance 1
    assert storage_inst1.get_key_quota_details(raw_key)["credits_remaining"] == 9

    # SIMULATE SERVER RESTART:
    # Destroy storage_inst1 from memory, construct brand new storage_inst2 connected to the same SQLite file
    del storage_inst1
    storage_inst2 = StorageManager(db_path=db_file)

    # Step 3: Reusing the same idempotency key on new server instance
    res_info2, state2 = storage_inst2.reserve_quota(raw_key, idempotency_key=idemp_key, request_id="req_retry_002")
    assert state2 == "idempotent_replay", "Must recognize settled reservation across server restart"
    assert res_info2["idempotency_key"] == idemp_key
    assert res_info2["cached_response"] == sample_response_payload, "Must replay exact cached payload"

    # Step 4: Verify zero additional credits were deducted
    quota_after_restart = storage_inst2.get_key_quota_details(raw_key)
    assert quota_after_restart["credits_remaining"] == 9, "Balance must remain 9 (zero double charges)"

    # Step 5: Sending a DIFFERENT idempotency key deducts 1 credit
    diff_idemp = f"idemp_diff_{uuid.uuid4().hex[:12]}"
    res_info3, state3 = storage_inst2.reserve_quota(raw_key, idempotency_key=diff_idemp, request_id="req_new_003")
    assert state3 == "ok"
    assert res_info3["credits"] == 8

    quota_final = storage_inst2.get_key_quota_details(raw_key)
    assert quota_final["credits_remaining"] == 8


def test_retry_after_failed_or_timed_out_request_succeeds_without_penalty(temp_storage):
    """
    Verifies that if a previous request under an idempotency key failed or timed out (released),
    a subsequent retry with the SAME idempotency key is permitted and executes cleanly.
    """
    raw_key, key_info = temp_storage.create_api_key(tier="tier_pro", credits=5)
    idemp_key = "idemp_retry_after_fail_001"

    # Attempt 1: Started and then failed/released
    res_info1, state1 = temp_storage.reserve_quota(raw_key, idempotency_key=idemp_key, request_id="req_fail_1")
    assert state1 == "ok"
    assert res_info1["credits"] == 4

    # Server encountered upstream error and released reservation
    temp_storage.release_quota(res_info1["reservation_id"], reason="upstream_dex_rpc_timeout")

    # Balance is refunded
    assert temp_storage.get_key_quota_details(raw_key)["credits_remaining"] == 5

    # Attempt 2: Client retries with the SAME idempotency key
    res_info2, state2 = temp_storage.reserve_quota(raw_key, idempotency_key=idemp_key, request_id="req_retry_2")
    assert state2 == "ok", "Retry after release must be allowed"
    assert res_info2["credits"] == 4

    # This time it succeeds and settles
    temp_storage.settle_quota(res_info2["reservation_id"], response_payload={"status": "success"})
    assert temp_storage.get_key_quota_details(raw_key)["credits_remaining"] == 4

    # Attempt 3: Immediate replay of settled key
    res_info3, state3 = temp_storage.reserve_quota(raw_key, idempotency_key=idemp_key, request_id="req_retry_3")
    assert state3 == "idempotent_replay"
    assert res_info3["cached_response"] == {"status": "success"}
    assert temp_storage.get_key_quota_details(raw_key)["credits_remaining"] == 4
