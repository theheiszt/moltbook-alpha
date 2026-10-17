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
    payload = {"transaction_signature": test_sig, "target_tier": "tier_starter"}

    with patch("api_server.SolanaPaymentVerifier.verify_payment") as mock_verify:
        from payment_verifier import VerifiedPayment
        mock_verify.return_value = VerifiedPayment(
            tx_signature=test_sig,
            asset="USDC",
            amount_raw=1_000_000,
            tier="tier_starter",
            credits=50,
            recipient="DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC",
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
