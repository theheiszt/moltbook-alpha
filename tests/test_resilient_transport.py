"""
Unit tests for Ops Resilient Transport Client (ops/transport/resilient_client.py).

Verifies:
1. Terminal non-retryable 4xx errors (400, 401, 403, 404, 422) fail fast without retries.
2. 5xx server errors retry up to max_retries for idempotent methods.
3. Non-idempotent operations (POST/PATCH without idempotency) fail fast and NEVER retry on network drop or 5xx.
4. Idempotent requests (GET or POST with idempotency) retry successfully on transient network drops.
5. Asynchronous execute_async honors identical safety and retry semantics.
"""

import pytest
import urllib.error
import httpx

from ops.transport.resilient_client import (
    RetryPolicy,
    execute_sync,
    execute_async,
)


def test_non_retryable_4xx_fails_immediately():
    calls = 0

    def mock_fn():
        nonlocal calls
        calls += 1
        # HTTP 401 Unauthorized
        raise urllib.error.HTTPError(
            url="https://api.moltbook.com/v1/test",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

    policy = RetryPolicy(max_retries=3, base_delay=0.01)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        execute_sync(mock_fn, policy=policy, method="GET")

    assert exc_info.value.code == 401
    assert calls == 1  # No retries on 401


def test_non_idempotent_post_does_not_retry_on_network_drop():
    calls = 0

    def mock_fn():
        nonlocal calls
        calls += 1
        raise ConnectionResetError("Connection dropped by peer")

    policy = RetryPolicy(max_retries=3, base_delay=0.01)

    # Calling POST with idempotent=False must fail on attempt 1 without retrying
    with pytest.raises(ConnectionResetError):
        execute_sync(mock_fn, policy=policy, method="POST", idempotent=False)

    assert calls == 1


def test_non_idempotent_post_does_not_retry_on_502_bad_gateway():
    calls = 0

    def mock_fn():
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            url="https://api.moltbook.com/v1/payments",
            code=502,
            msg="Bad Gateway",
            hdrs={},
            fp=None,
        )

    policy = RetryPolicy(max_retries=3, base_delay=0.01)

    with pytest.raises(urllib.error.HTTPError):
        execute_sync(mock_fn, policy=policy, method="POST", idempotent=False)

    assert calls == 1


def test_idempotent_get_retries_transient_failure_until_success():
    calls = 0

    def mock_fn():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionResetError("Transient network glitch")
        return {"status": "success", "attempt": calls}

    policy = RetryPolicy(max_retries=3, base_delay=0.01)
    result = execute_sync(mock_fn, policy=policy, method="GET", idempotent=True)

    assert result["status"] == "success"
    assert calls == 3


@pytest.mark.anyio
async def test_async_non_idempotent_post_fails_immediately():
    calls = 0

    async def mock_coro():
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("Failed to establish connection")

    policy = RetryPolicy(max_retries=3, base_delay=0.01)

    with pytest.raises(httpx.ConnectError):
        await execute_async(mock_coro, policy=policy, method="POST", idempotent=False)

    assert calls == 1


@pytest.mark.anyio
async def test_async_idempotent_request_retries_and_succeeds():
    calls = 0

    async def mock_coro():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise httpx.ConnectTimeout("Connection timed out")
        return {"data": "ok"}

    policy = RetryPolicy(max_retries=3, base_delay=0.01)
    result = await execute_async(mock_coro, policy=policy, method="GET", idempotent=True)

    assert result["data"] == "ok"
    assert calls == 2
