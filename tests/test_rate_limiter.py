"""
Tests for SlidingWindowRateLimiter, InFlightDeduplicator, and API Rate Limiting Middleware.
"""

import time
import threading
from unittest.mock import patch
from fastapi.testclient import TestClient

from rate_limiter import SlidingWindowRateLimiter, InFlightDeduplicator
from api_server import app, rate_limiter


def test_sliding_window_allows_within_limit():
    limiter = SlidingWindowRateLimiter()
    # Limit: 3 requests per 60 seconds
    for _ in range(3):
        allowed, retry_after = limiter.is_allowed("test_client", limit=3, window_seconds=60, current_time=100.0)
        assert allowed is True
        assert retry_after == 0


def test_sliding_window_blocks_over_limit_with_retry_after():
    limiter = SlidingWindowRateLimiter()
    # Send 3 requests at t=100.0
    for _ in range(3):
        limiter.is_allowed("test_client", limit=3, window_seconds=60, current_time=100.0)

    # 4th request at t=105.0 should be blocked
    allowed, retry_after = limiter.is_allowed("test_client", limit=3, window_seconds=60, current_time=105.0)
    assert allowed is False
    # Oldest timestamp is 100.0, expires at 160.0. Current time 105.0 -> retry_after ~ 55s
    assert retry_after == 55


def test_sliding_window_slides_and_allows_after_expiry():
    limiter = SlidingWindowRateLimiter()
    # 2 requests at t=100.0
    limiter.is_allowed("test_client", limit=2, window_seconds=10, current_time=100.0)
    limiter.is_allowed("test_client", limit=2, window_seconds=10, current_time=102.0)

    # Blocked at t=105.0
    allowed, _ = limiter.is_allowed("test_client", limit=2, window_seconds=10, current_time=105.0)
    assert allowed is False

    # At t=111.0, the first request (t=100.0) has rolled out of the 10-second window
    allowed, retry_after = limiter.is_allowed("test_client", limit=2, window_seconds=10, current_time=111.0)
    assert allowed is True
    assert retry_after == 0


def test_sliding_window_ip_isolation():
    limiter = SlidingWindowRateLimiter()
    # Exhaust client A
    for _ in range(2):
        limiter.is_allowed("client_a", limit=2, window_seconds=60, current_time=100.0)

    assert limiter.is_allowed("client_a", limit=2, window_seconds=60, current_time=100.0)[0] is False
    # Client B is completely unhindered
    assert limiter.is_allowed("client_b", limit=2, window_seconds=60, current_time=100.0)[0] is True


def test_in_flight_deduplicator_single_execution():
    dedup = InFlightDeduplicator()
    call_count = 0
    barrier = threading.Barrier(5)

    def expensive_call():
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)
        return "verified_result"

    results = []

    def worker():
        barrier.wait()
        res = dedup.execute("sig_12345", expensive_call)
        results.append(res)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count == 1
    assert len(results) == 5
    assert all(r == "verified_result" for r in results)


def test_in_flight_deduplicator_propagates_exception():
    dedup = InFlightDeduplicator()
    barrier = threading.Barrier(3)

    def failing_call():
        time.sleep(0.02)
        raise ValueError("Invalid on-chain payload")

    errors = []

    def worker():
        barrier.wait()
        try:
            dedup.execute("sig_fail", failing_call)
        except ValueError as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 3
    assert all("Invalid on-chain payload" in e for e in errors)


def test_api_verify_solana_rate_limiting_triggers_429():
    client = TestClient(app)
    rate_limiter.reset()

    # Rate limit for verify-solana is 10/min per IP
    test_sig = "5abcde" * 15  # 90 chars valid base58 length
    inv = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    payload = {"transaction_signature": test_sig, "invoice_id": inv["invoice_id"]}

    with patch("api_server.SolanaPaymentVerifier.verify_payment") as mock_verify:
        from payment_verifier import VerifiedPayment
        mock_verify.return_value = VerifiedPayment(
            tx_signature=test_sig,
            asset="USDC",
            amount_raw=1_000_000,
            tier="tier_starter",
            credits=50,
            recipient="BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx",
        )

        headers = {"x-forwarded-for": "198.51.100.42"}
        # Send 10 allowed requests
        for _ in range(10):
            resp = client.post("/v1/payments/verify-solana", json=payload, headers=headers)
            assert resp.status_code == 200

        # 11th request must be rejected with 429 Too Many Requests
        blocked_resp = client.post("/v1/payments/verify-solana", json=payload, headers=headers)
        assert blocked_resp.status_code == 429
        assert "Retry-After" in blocked_resp.headers
        assert "Too many payment verification requests" in blocked_resp.json()["detail"]

        # A different IP address is NOT blocked
        different_ip_resp = client.post(
            "/v1/payments/verify-solana",
            json=payload,
            headers={"x-forwarded-for": "203.0.113.88"},
        )
        assert different_ip_resp.status_code == 200


def test_token_bucket_burst_allowance_and_sustained_refill(tmp_path):
    from rate_limiter import TokenBucketRateLimiter
    from storage import StorageManager

    db_path = tmp_path / "tb_test.db"
    sm = StorageManager(db_path)
    limiter = TokenBucketRateLimiter(storage_manager=sm)

    # 1. Burst allowance: 5 tokens allowed immediately at t=100.0
    for i in range(5):
        allowed, retry_after, remaining = limiter.is_allowed(
            "key:burst_test",
            capacity=5,
            refill_per_min=60,  # 1.0 token / sec
            cost=1.0,
            now=100.0,
        )
        assert allowed is True
        assert retry_after == 0
        assert remaining == (4.0 - i)

    # 2. 6th request at t=100.0 must be rejected
    allowed, retry_after, remaining = limiter.is_allowed(
        "key:burst_test",
        capacity=5,
        refill_per_min=60,
        cost=1.0,
        now=100.0,
    )
    assert allowed is False
    assert retry_after == 1  # 1.0 token needed at 1.0 token/sec refill
    assert remaining == 0.0

    # 3. Refill: at t=102.5 (2.5 seconds later), 2.5 tokens refilled
    allowed, retry_after, remaining = limiter.is_allowed(
        "key:burst_test",
        capacity=5,
        refill_per_min=60,
        cost=1.0,
        now=102.5,
    )
    assert allowed is True
    assert retry_after == 0
    assert remaining >= 1.0


def test_token_bucket_multi_instance_coordination(tmp_path):
    from rate_limiter import TokenBucketRateLimiter
    from storage import StorageManager

    db_path = tmp_path / "tb_multi.db"
    # Create two independent instances sharing the same database file
    sm1 = StorageManager(db_path)
    sm2 = StorageManager(db_path)
    node1 = TokenBucketRateLimiter(storage_manager=sm1)
    node2 = TokenBucketRateLimiter(storage_manager=sm2)

    # Node 1 consumes 3 tokens
    for _ in range(3):
        allowed, _, _ = node1.is_allowed("key:shared_agent", capacity=5, refill_per_min=60, now=10.0)
        assert allowed is True

    # Node 2 sees only 2 tokens left and consumes 2
    for _ in range(2):
        allowed, _, _ = node2.is_allowed("key:shared_agent", capacity=5, refill_per_min=60, now=10.0)
        assert allowed is True

    # Node 1 is now blocked because Node 2 exhausted the shared bucket
    allowed, retry_after, _ = node1.is_allowed("key:shared_agent", capacity=5, refill_per_min=60, now=10.0)
    assert allowed is False
    assert retry_after >= 1


def test_token_bucket_fail_open_and_closed():
    from rate_limiter import TokenBucketRateLimiter
    from unittest.mock import MagicMock

    mock_sm = MagicMock()
    mock_sm.connection.side_effect = RuntimeError("Database unreachable")

    # Fail open allows traffic
    limiter_open = TokenBucketRateLimiter(storage_manager=mock_sm, fail_open=True)
    allowed, retry_after, remaining = limiter_open.is_allowed("key:failing", capacity=5, refill_per_min=60)
    assert allowed is True
    assert retry_after == 0

    # Fail closed blocks traffic safely
    limiter_closed = TokenBucketRateLimiter(storage_manager=mock_sm, fail_open=False)
    allowed, retry_after, remaining = limiter_closed.is_allowed("key:failing", capacity=5, refill_per_min=60)
    assert allowed is False
    assert retry_after == 1


def test_concurrency_limiter_slots_and_cleanup(tmp_path):
    from rate_limiter import ConcurrencyLimiter
    from storage import StorageManager

    db_path = tmp_path / "conc_test.db"
    sm = StorageManager(db_path)
    limiter = ConcurrencyLimiter(storage_manager=sm)

    slots = []
    # Acquire up to 5 concurrent slots
    for _ in range(5):
        acquired, slot_id, count = limiter.acquire("key:conc_agent", max_concurrent=5)
        assert acquired is True
        slots.append(slot_id)
        assert count <= 5

    # 6th request fails concurrency check
    acquired, slot_id, count = limiter.acquire("key:conc_agent", max_concurrent=5)
    assert acquired is False
    assert slot_id is None
    assert count == 5

    # Release one slot
    limiter.release(slots[0], "key:conc_agent")

    # Now 6th request can acquire
    acquired, new_slot, count = limiter.acquire("key:conc_agent", max_concurrent=5)
    assert acquired is True
    assert count == 5


def test_api_rate_limit_and_timeout_headers(tmp_path):
    from api_server import app, storage, token_bucket_limiter
    client = TestClient(app)
    token_bucket_limiter.reset()

    raw_key, _ = storage.create_api_key(tier="starter", credits=100, prefix_tag="molt_tb_test")

    # First request succeeds and returns standard rate limit headers
    resp = client.get("/v1/briefing/latest", headers={"X-API-KEY": raw_key})
    assert resp.status_code in (200, 404)
    assert "X-RateLimit-Limit" in resp.headers
    assert resp.headers["X-RateLimit-Limit"] == "60"
    assert "X-RateLimit-Remaining" in resp.headers

    # Simulate token bucket exhaustion
    rate_key = f"key:{storage.hash_key(raw_key)}"
    # Drain remaining tokens
    for _ in range(10):
        token_bucket_limiter.is_allowed(rate_key, capacity=5, refill_per_min=60)

    # Next request should be rejected with 429 and machine readable payload
    blocked = client.get("/v1/briefing/latest", headers={"X-API-KEY": raw_key})
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After") is not None
    body = blocked.json()
    assert "error" in body
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["retryable"] is True
    assert body["error"]["retry_after_seconds"] >= 1
