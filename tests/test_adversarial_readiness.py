import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api_server import app, storage, concurrency_limiter
from rate_limiter import TokenBucketRateLimiter, ConcurrencyLimiter
from storage import StorageManager


def test_adversarial_multi_instance_shared_sqlite_rate_limiting():
    """
    Verifies that multiple independent limiter instances coordinating through
    the same SQLite WAL database enforce authoritative limits across workers.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "shared_rate_limits.db"
        sm = StorageManager(db_path)

        # Worker 1 and Worker 2 each instantiate their own limiter pointing to shared DB
        limiter_worker_1 = TokenBucketRateLimiter(storage=sm, default_capacity=5, default_refill_per_min=60)
        limiter_worker_2 = TokenBucketRateLimiter(storage=sm, default_capacity=5, default_refill_per_min=60)

        rate_key = "key:agent_adversarial_1"
        fixed_now = 100000.0

        # Worker 1 consumes 3 tokens
        for _ in range(3):
            allowed, _, _ = limiter_worker_1.is_allowed(rate_key, capacity=5, refill_per_min=60, current_time=fixed_now)
            assert allowed is True

        # Worker 2 consumes 2 tokens (total 5 = capacity)
        for _ in range(2):
            allowed, _, _ = limiter_worker_2.is_allowed(rate_key, capacity=5, refill_per_min=60, current_time=fixed_now)
            assert allowed is True

        # 6th request from Worker 1 MUST be rejected (burst capacity exhausted)
        allowed, retry_after, rem = limiter_worker_1.is_allowed(rate_key, capacity=5, refill_per_min=60, current_time=fixed_now)
        assert allowed is False
        assert retry_after >= 1
        assert rem == 0.0

        # 6th request from Worker 2 MUST also be rejected
        allowed2, retry_after2, rem2 = limiter_worker_2.is_allowed(rate_key, capacity=5, refill_per_min=60, current_time=fixed_now)
        assert allowed2 is False
        assert retry_after2 >= 1
        assert rem2 == 0.0

        # Independent key "key:agent_adversarial_2" on Worker 2 must NOT be throttled
        independent_key = "key:agent_adversarial_2"
        allowed_indep, _, _ = limiter_worker_2.is_allowed(independent_key, capacity=5, refill_per_min=60, current_time=fixed_now)
        assert allowed_indep is True


def test_token_bucket_mathematics_refill_and_cap():
    """
    Confirms token bucket starts at capacity, refills at documented 60/min (1/s),
    and strictly never exceeds the configured capacity ceiling.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "math_test.db"
        sm = StorageManager(db_path)
        limiter = TokenBucketRateLimiter(storage=sm, default_capacity=5, default_refill_per_min=60)

        rate_key = "key:math_test"
        t0 = 200000.0

        # 1. Exhaust all 5 tokens
        for i in range(5):
            allowed, retry_after, remaining = limiter.is_allowed(rate_key, capacity=5, refill_per_min=60, current_time=t0)
            assert allowed is True

        # Immediate next request fails
        allowed, retry_after, remaining = limiter.is_allowed(rate_key, capacity=5, refill_per_min=60, current_time=t0)
        assert allowed is False
        assert retry_after == 1
        assert remaining == 0.0

        # 2. Advance by exactly 1.0 second -> exactly 1 token refilled (60/min = 1.0/s)
        t1 = t0 + 1.0
        allowed, _, remaining = limiter.is_allowed(rate_key, capacity=5, refill_per_min=60, current_time=t1)
        assert allowed is True
        # Immediately subsequent request at t1 fails
        allowed, _, _ = limiter.is_allowed(rate_key, capacity=5, refill_per_min=60, current_time=t1)
        assert allowed is False

        # 3. Advance by 1,000,000 seconds (idle for weeks) -> tokens must NEVER exceed 5.0
        t_future = t1 + 1000000.0
        tokens_available = limiter.get_remaining(rate_key, capacity=5, refill_per_min=60, current_time=t_future)
        assert tokens_available == 5.0


def test_concurrency_limiter_shared_sqlite_and_expiry():
    """
    Confirms ConcurrencyLimiter enforces max 5 concurrent requests across workers,
    and automatically reaps orphaned/timed-out execution slots.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "concurrency_test.db"
        sm = StorageManager(db_path)

        c1 = ConcurrencyLimiter(storage=sm, default_max_concurrent=5)
        c2 = ConcurrencyLimiter(storage=sm, default_max_concurrent=5)

        rate_key = "key:concurrency_test"
        now = 300000.0

        # Worker 1 acquires 3 slots
        s1, slot1, _ = c1.acquire(rate_key, max_concurrent=5, ttl_seconds=10.0, current_time=now)
        s2, slot2, _ = c1.acquire(rate_key, max_concurrent=5, ttl_seconds=10.0, current_time=now)
        s3, slot3, _ = c1.acquire(rate_key, max_concurrent=5, ttl_seconds=10.0, current_time=now)
        assert s1 and s2 and s3

        # Worker 2 acquires 2 slots (total 5)
        s4, slot4, _ = c2.acquire(rate_key, max_concurrent=5, ttl_seconds=10.0, current_time=now)
        s5, slot5, _ = c2.acquire(rate_key, max_concurrent=5, ttl_seconds=10.0, current_time=now)
        assert s4 and s5

        # 6th acquire from Worker 1 is rejected
        s6, slot6, count = c1.acquire(rate_key, max_concurrent=5, ttl_seconds=10.0, current_time=now)
        assert s6 is False
        assert slot6 is None
        assert count == 5

        # Release 1 slot from Worker 1 -> Worker 2 can acquire
        c1.release(slot1, rate_key)
        s7, slot7, count7 = c2.acquire(rate_key, max_concurrent=5, ttl_seconds=10.0, current_time=now)
        assert s7 is True
        assert count7 == 5

        # Advance past 10s TTL without releasing -> orphaned slots are reaped on next acquire
        now_later = now + 15.0
        s8, slot8, count8 = c1.acquire(rate_key, max_concurrent=5, ttl_seconds=10.0, current_time=now_later)
        assert s8 is True
        assert count8 == 1  # All prior slots expired


def test_adversarial_competition_for_last_credit():
    """
    Many simultaneous threads competing for the very last available credit.
    Ensures that exactly 1 request succeeds, all others receive 'exhausted',
    and remaining balance never drops below zero.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "last_credit.db"
        sm = StorageManager(db_path)

        raw_key, key_info = sm.create_api_key(tier="tier_starter", credits=1)
        k_hash = key_info["key_hash"]

        results = []
        errors = []

        def racer():
            try:
                res, st = sm.reserve_quota(raw_key)
                results.append(st)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=racer) for _ in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert results.count("ok") == 1
        assert results.count("exhausted") == 24

        details = sm.get_key_quota_details(raw_key)
        assert details["credits_remaining"] == 0

        v = sm.verify_ledger_balance(k_hash)
        assert v["balanced"] is True
        assert v["breakdown"]["granted"] == 1
        assert v["breakdown"]["deducted"] == 1
        assert v["actual_lot_balance"] == 0
        assert v["api_key_balance"] == 0


def test_adversarial_edf_multi_lot_ordering():
    """
    Multiple active credit lots with different expiration dates.
    Confirms Earliest Deadline First (EDF) consumption order and rollover.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "edf_lots.db"
        sm = StorageManager(db_path)

        raw_key, key_info = sm.create_api_key(tier="tier_pro", credits=0)
        k_hash = key_info["key_hash"]

        # Lot A: 2 credits, expires in 2 days
        sm.grant_topup(k_hash, credits=2, validity_days=2)
        # Lot B: 3 credits, expires in 10 days
        sm.grant_topup(k_hash, credits=3, validity_days=10)

        # 1st reservation -> Lot A
        res1, st1 = sm.reserve_quota(raw_key)
        assert st1 == "ok"
        lot_a_id = res1["lot_id"]
        sm.settle_quota(res1["reservation_id"])

        # 2nd reservation -> Lot A
        res2, st2 = sm.reserve_quota(raw_key)
        assert st2 == "ok"
        assert res2["lot_id"] == lot_a_id
        sm.settle_quota(res2["reservation_id"])

        # 3rd reservation -> Lot A is exhausted, automatically rolls over to Lot B!
        res3, st3 = sm.reserve_quota(raw_key)
        assert st3 == "ok"
        assert res3["lot_id"] != lot_a_id
        sm.settle_quota(res3["reservation_id"])

        details = sm.get_key_quota_details(raw_key)
        assert details["credits_remaining"] == 2  # 5 granted - 3 settled

        v = sm.verify_ledger_balance(k_hash)
        assert v["balanced"] is True
        assert v["breakdown"]["granted"] == 5
        assert v["breakdown"]["deducted"] == 3


def test_adversarial_reservation_lifecycle_reaper_and_idempotent_settle():
    """
    Tests failure after reservation, worker crash, reservation reaping,
    and verifies that duplicate settle/refund or late completion cannot double-credit.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "reaper_lifecycle.db"
        sm = StorageManager(db_path)

        raw_key, key_info = sm.create_api_key(tier="tier_starter", credits=5)
        k_hash = key_info["key_hash"]

        # 1. Failure after reservation -> explicit release restores credit
        res1, st1 = sm.reserve_quota(raw_key)
        assert st1 == "ok"
        assert sm.get_key_quota_details(raw_key)["credits_remaining"] == 4
        # Release
        released = sm.release_quota(res1["reservation_id"], reason="endpoint_failed")
        assert released is True
        assert sm.get_key_quota_details(raw_key)["credits_remaining"] == 5
        # Duplicate release attempt MUST fail (no double refund)
        released_dup = sm.release_quota(res1["reservation_id"])
        assert released_dup is False
        assert sm.get_key_quota_details(raw_key)["credits_remaining"] == 5

        # 2. Worker termination between reserve and settle -> orphaned reservation reaped
        res2, st2 = sm.reserve_quota(raw_key, ttl_seconds=60)
        assert st2 == "ok"
        assert sm.get_key_quota_details(raw_key)["credits_remaining"] == 4

        # Advance clock past TTL (61 seconds)
        sm.advance_clock(timedelta(seconds=61))

        # Reaper runs
        reaped_count = sm.reap_expired_reservations()
        assert reaped_count == 1
        assert sm.get_key_quota_details(raw_key)["credits_remaining"] == 5

        # Worker wakes up late and tries to settle -> MUST fail safely
        settle_late = sm.settle_quota(res2["reservation_id"])
        assert settle_late is False

        # Duplicate reap attempt -> 0 reaped
        assert sm.reap_expired_reservations() == 0

        # Ledger remains mathematically balanced
        v = sm.verify_ledger_balance(k_hash)
        assert v["balanced"] is True
        assert v["actual_lot_balance"] == 5
        assert v["api_key_balance"] == 5


def test_adversarial_concurrent_idempotency_double_spend():
    """
    Adversarial test: simultaneous requests with identical idempotency key.
    Guarantees:
    - Only 1 operation executes and reserves quota.
    - Concurrent requests receive 'in_flight'.
    - Exactly 1 credit is deducted (no double-spend).
    - Subsequent replay receives 'idempotent_replay' and cached response.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "idemp_test.db"
        sm = StorageManager(db_path)

        raw_key, key_info = sm.create_api_key(tier="tier_starter", credits=10)
        k_hash = key_info["key_hash"]
        shared_idemp = "idemp_race_test_123"

        states = []
        reservations = []

        def worker():
            res, st = sm.reserve_quota(raw_key, idempotency_key=shared_idemp)
            states.append(st)
            if st == "ok":
                reservations.append(res)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert states.count("ok") == 1
        assert states.count("in_flight") == 9
        assert len(reservations) == 1

        # Exactly 1 credit deducted
        details = sm.get_key_quota_details(raw_key)
        assert details["credits_remaining"] == 9

        # Settle the reservation with a response payload
        cached_payload = {"briefing": "alpha intelligence signal verified"}
        settle_ok = sm.settle_quota(reservations[0]["reservation_id"], response_payload=cached_payload)
        assert settle_ok is True

        # Now, client retries with the same idempotency key (lost response retry)
        replay_res, replay_st = sm.reserve_quota(raw_key, idempotency_key=shared_idemp)
        assert replay_st == "idempotent_replay"
        assert replay_res["cached_response"] == cached_payload

        # Still exactly 9 credits remaining (0 credits burned on replay)
        details_after = sm.get_key_quota_details(raw_key)
        assert details_after["credits_remaining"] == 9

        # Ledger verified
        v = sm.verify_ledger_balance(k_hash)
        assert v["balanced"] is True
        assert v["breakdown"]["deducted"] == 1


def test_adversarial_idempotency_cross_user_isolation():
    """
    Ensures that cached responses and in-flight reservations cannot be replayed across API keys.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "isolation_test.db"
        sm = StorageManager(db_path)

        raw_key_1, info_1 = sm.create_api_key(tier="tier_starter", credits=10)
        raw_key_2, info_2 = sm.create_api_key(tier="tier_starter", credits=10)

        shared_idemp = "shared_idemp_key_cross_agent"

        # User 1 reserves and settles
        res1, st1 = sm.reserve_quota(raw_key_1, idempotency_key=shared_idemp)
        assert st1 == "ok"
        sm.settle_quota(res1["reservation_id"], response_payload={"user": 1})

        # User 2 uses identical idempotency key -> MUST NOT replay User 1's payload
        res2, st2 = sm.reserve_quota(raw_key_2, idempotency_key=shared_idemp)
        assert st2 == "ok"  # User 2 gets a fresh reservation
        assert res2["reservation_id"] != res1["reservation_id"]
        assert res2["key_hash"] == info_2["key_hash"]


def test_adversarial_timeout_and_504_slot_and_quota_recovery():
    """
    Verifies that on 504 Request Timeout:
    1. Middleware returns HTTP 504 with REQUEST_TIMEOUT.
    2. Reserved quota credit is restored immediately.
    3. Concurrency slot is released immediately.
    """
    client = TestClient(app, raise_server_exceptions=False)
    raw_key, key_info = storage.create_api_key(tier="tier_starter", credits=10, prefix_tag="molt_timeout_test")
    k_hash = key_info["key_hash"]
    rate_key = f"key:{k_hash}"

    # Before request: in_flight is 0, credits is 10
    assert concurrency_limiter.get_in_flight(rate_key) == 0
    assert storage.get_key_quota_details(raw_key)["credits_remaining"] == 10

    # Simulate timeout by patching asyncio.wait_for to raise asyncio.TimeoutError
    import asyncio
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
        resp = client.get("/v1/briefing/latest", headers={"X-API-KEY": raw_key})
        assert resp.status_code == 504
        data = resp.json()
        assert data["code"] == "REQUEST_TIMEOUT"
        assert data["retryable"] is True

    # Confirm concurrency slot is 0 (released)
    assert concurrency_limiter.get_in_flight(rate_key) == 0

    # Confirm credit was not burnt (remains 10)
    details = storage.get_key_quota_details(raw_key)
    assert details["credits_remaining"] == 10

    # Ledger remains balanced
    v = storage.verify_ledger_balance(k_hash)
    assert v["balanced"] is True


def test_deterministic_stress_loop_agent_quota_and_burst_exhaustion():
    """
    Simulates an autonomous agent in a fast loop attempting requests against
    an account with limited credits (15 credits).
    Measures and asserts:
    - Initial burst allows 5 requests.
    - Subsequent requests hit 429 (rate limit).
    - As tokens refill, queries execute and consume credits.
    - Once credits reach 0, requests fail with 402 (credits exhausted).
    - Total deducted credits matches successful requests.
    - Rate limit rejections (429) do NOT deduct credits.
    """
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "agent_stress.db"
        sm = StorageManager(db_path)
        limiter = TokenBucketRateLimiter(storage=sm, default_capacity=5, default_refill_per_min=60)

        raw_key, key_info = sm.create_api_key(tier="tier_starter", credits=15)
        k_hash = key_info["key_hash"]
        rate_key = f"key:{k_hash}"

        current_sim_time = 500000.0

        attempted = 0
        success = 0
        rate_limited_429 = 0
        exhausted_402 = 0

        # Run 50 simulated loop iterations
        for i in range(50):
            attempted += 1
            # Step 1: Check rate limiter
            allowed, retry_after, _ = limiter.is_allowed(
                rate_key,
                capacity=5,
                refill_per_min=60,
                current_time=current_sim_time,
            )
            if not allowed:
                rate_limited_429 += 1
                # Agent backs off and advances simulation time by retry_after seconds
                current_sim_time += retry_after
                continue

            # Step 2: Rate limit passed, reserve quota
            res, state = sm.reserve_quota(raw_key)
            if state == "exhausted":
                exhausted_402 += 1
            elif state == "ok":
                success += 1
                sm.settle_quota(res["reservation_id"])
            else:
                pytest.fail(f"Unexpected reservation state: {state}")

            # Advance small step
            current_sim_time += 0.1

        assert attempted == success + rate_limited_429 + exhausted_402
        assert success == 15  # Exactly the 15 available credits
        assert exhausted_402 > 0  # Reached after 15 queries exhausted
        assert rate_limited_429 > 0  # Hit rate limit bursts along the way

        # Verify rate limit rejections did NOT consume any credits
        details = sm.get_key_quota_details(raw_key)
        assert details["credits_remaining"] == 0

        v = sm.verify_ledger_balance(k_hash)
        assert v["balanced"] is True
        assert v["breakdown"]["granted"] == 15
        assert v["breakdown"]["deducted"] == 15
