"""
Unit tests for Resilient HTTP Transport and Backoff Policy.
"""

import io
import urllib.error
import urllib.request
import pytest
import httpx

from ops.transport.resilient_client import (
    RetryPolicy,
    execute_sync,
    execute_async,
    parse_retry_after_header,
    telemetry,
    NON_RETRYABLE_4XX,
)
from moltbook_client import MoltbookClient


def setup_function():
    telemetry.reset()


def make_mock_http_error(code: int, msg: str = "Error", retry_after: str = None) -> urllib.error.HTTPError:
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="https://api.moltbook.com/test",
        code=code,
        msg=msg,
        hdrs=headers,
        fp=io.BytesIO(b'{"error": "mock_error"}'),
    )


def test_parse_retry_after_header():
    assert parse_retry_after_header("5") == 5.0
    assert parse_retry_after_header("  12.5  ") == 12.5
    assert parse_retry_after_header(None) is None
    assert parse_retry_after_header("invalid") is None


def test_never_retries_4xx_fatal_errors():
    for status_code in [400, 401, 402, 403, 404, 422, 428]:
        call_count = 0

        def failing_call():
            nonlocal call_count
            call_count += 1
            raise make_mock_http_error(status_code)

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            execute_sync(failing_call, policy=RetryPolicy(max_retries=3))

        assert exc_info.value.code == status_code
        # Invariant: Must fail immediately on attempt 1 with zero retries
        assert call_count == 1

    assert telemetry.client_errors_total == 7


def test_retries_5xx_server_errors_and_recovers():
    call_count = 0
    policy = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)

    def transient_call():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise make_mock_http_error(503, "Service Unavailable")
        return {"success": True}

    result = execute_sync(transient_call, policy=policy)
    assert result == {"success": True}
    assert call_count == 3
    assert telemetry.retries_total == 2
    assert telemetry.server_errors_total == 2


def test_retries_5xx_exhausts_retries():
    call_count = 0
    policy = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)

    def persistently_failing_call():
        nonlocal call_count
        call_count += 1
        raise make_mock_http_error(500, "Internal Server Error")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        execute_sync(persistently_failing_call, policy=policy)

    assert exc_info.value.code == 500
    assert call_count == 3
    assert telemetry.retries_total == 2


def test_handles_429_with_retry_after():
    call_count = 0
    policy = RetryPolicy(max_429_retries=2, base_delay=0.01, jitter=False)

    def rate_limited_call():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise make_mock_http_error(429, "Too Many Requests", retry_after="0.02")
        return {"status": "ok"}

    result = execute_sync(rate_limited_call, policy=policy)
    assert result == {"status": "ok"}
    assert call_count == 2
    assert telemetry.throttles_total == 1


def test_retries_network_drops():
    call_count = 0
    policy = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)

    def network_drop_call():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise urllib.error.URLError("Connection refused by peer")
        return {"connected": True}

    result = execute_sync(network_drop_call, policy=policy)
    assert result == {"connected": True}
    assert call_count == 2


@pytest.mark.anyio
async def test_async_resilient_execution():
    call_count = 0
    policy = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)

    async def async_call():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise make_mock_http_error(502, "Bad Gateway")
        return {"data": 42}

    res = await execute_async(async_call, policy=policy)
    assert res == {"data": 42}
    assert call_count == 2


def test_moltbook_client_integrates_resilience(monkeypatch):
    client = MoltbookClient(api_key="test_api_key_123")
    client.retry_policy = RetryPolicy(max_retries=3, base_delay=0.01, jitter=False)

    urlopen_calls = 0

    class MockResponse:
        def read(self):
            return b'{"agent": "moltbook_intel", "status": "active"}'
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(req, timeout=12):
        nonlocal urlopen_calls
        urlopen_calls += 1
        if urlopen_calls == 1:
            raise make_mock_http_error(502, "Bad Gateway")
        return MockResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = client._request("/test")
    assert res["status"] == "active"
    assert urlopen_calls == 2

    # Now verify 401 fails immediately on attempt 1 without retry
    urlopen_calls = 0

    def mock_urlopen_401(req, timeout=12):
        nonlocal urlopen_calls
        urlopen_calls += 1
        raise make_mock_http_error(401, "Unauthorized")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_401)

    with pytest.raises(RuntimeError) as exc_info:
        client._request("/test")

    assert "HTTP 401" in str(exc_info.value)
    assert urlopen_calls == 1
