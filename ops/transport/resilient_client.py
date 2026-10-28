"""
Resilient HTTP Transport & Backoff Engine for Moltbook Alpha.

Enforces strict retry semantics across outbound HTTP clients:
  1. NEVER retries 4xx client errors (400, 401, 402, 403, 404, 409, 410, 422, 428).
  2. Bounded backoff for 429 Too Many Requests (respects Retry-After header, capped at max_retry_after).
  3. Exponential backoff with full jitter for 5xx server errors (500, 502, 503, 504) and network dropouts.
  4. Provides sync and async execution bridges, telemetry tracking, and optional Egress Guard integration.

Portions adapted from Clawnch Clawmes (MIT License - Copyright (c) 2026 Clawnch).
"""

from __future__ import annotations

import asyncio
import dataclasses
import email.utils
import random
import time
import urllib.error
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar
import httpx

from ops.security.egress_guard import SafeEgressTransport, DEFAULT_MAX_RESPONSE_BYTES

T = TypeVar("T")

# Non-retryable HTTP 4xx status codes (fatal client errors)
NON_RETRYABLE_4XX: frozenset[int] = frozenset({
    400, 401, 402, 403, 404, 405, 406, 409, 410, 411, 412,
    413, 414, 415, 416, 417, 422, 428, 431, 451,
})

# Retryable HTTP 5xx status codes (transient server errors)
RETRYABLE_5XX: frozenset[int] = frozenset({500, 502, 503, 504})


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    """Configures retry behavior, exponential backoff, and 429 rate-limit handling."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 8.0
    max_429_retries: int = 2
    max_retry_after: float = 10.0
    jitter: bool = True

    def is_retryable(self, status_code: int, attempt: int) -> bool:
        """Determines if a given status code is eligible for retry on the current attempt."""
        if status_code in NON_RETRYABLE_4XX:
            return False
        if status_code == 429:
            return attempt < self.max_429_retries
        if status_code in RETRYABLE_5XX:
            return attempt < self.max_retries
        # Non-standard or unlisted status codes are not retried by default
        return False

    def compute_delay(self, status_code: int, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculates sleep duration before retry."""
        if status_code == 429:
            if retry_after is not None and retry_after > 0:
                delay = min(self.max_retry_after, retry_after)
            else:
                delay = min(self.max_retry_after, self.base_delay * 2)
            if self.jitter:
                delay += random.uniform(0.05, 0.25)
            return min(self.max_retry_after, delay)

        # Exponential backoff: base * 2^(attempt - 1)
        base = min(self.max_delay, self.base_delay * (2 ** max(0, attempt - 1)))
        if self.jitter:
            delay = random.uniform(0.5 * base, base)
        else:
            delay = base
        return delay


class TransportTelemetry:
    """Thread-safe statistics counter for transport activity."""
    def __init__(self):
        self.retries_total: int = 0
        self.throttles_total: int = 0
        self.client_errors_total: int = 0
        self.server_errors_total: int = 0

    def record_retry(self, status_code: Optional[int]) -> None:
        self.retries_total += 1
        if status_code == 429:
            self.throttles_total += 1
        elif status_code and status_code >= 500:
            self.server_errors_total += 1

    def record_fatal_client_error(self) -> None:
        self.client_errors_total += 1

    def reset(self) -> None:
        self.retries_total = 0
        self.throttles_total = 0
        self.client_errors_total = 0
        self.server_errors_total = 0


telemetry = TransportTelemetry()


def parse_retry_after_header(val: Optional[str]) -> Optional[float]:
    """Parses Retry-After header as integer seconds or HTTP-date string."""
    if not val or not val.strip():
        return None
    cleaned = val.strip()
    try:
        return float(cleaned)
    except ValueError:
        pass
    try:
        target_time = email.utils.parsedate_to_datetime(cleaned)
        return max(0.0, target_time.timestamp() - time.time())
    except Exception:
        return None


def extract_status_and_retry_after(exc: Exception) -> tuple[Optional[int], Optional[float]]:
    """Extracts HTTP status code and Retry-After duration from common Python HTTP exceptions."""
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        retry_after = parse_retry_after_header(exc.headers.get("Retry-After") if exc.headers else None)
        return code, retry_after
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        retry_after = parse_retry_after_header(exc.response.headers.get("Retry-After"))
        return code, retry_after
    # Network or timeout errors have no HTTP status code
    return None, None


def execute_sync(
    fn: Callable[[], T],
    *,
    policy: Optional[RetryPolicy] = None,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
) -> T:
    """
    Executes a synchronous request callable with retry and backoff semantics.
    """
    pol = policy or RetryPolicy()
    attempt = 0

    while True:
        try:
            return fn()
        except Exception as exc:
            attempt += 1
            status_code, retry_after = extract_status_and_retry_after(exc)

            if status_code is not None:
                if not pol.is_retryable(status_code, attempt):
                    if status_code in NON_RETRYABLE_4XX:
                        telemetry.record_fatal_client_error()
                    raise exc
            else:
                # Connection or network-level exception
                is_network_drop = isinstance(
                    exc,
                    (
                        urllib.error.URLError,
                        httpx.TransportError,
                        ConnectionError,
                        TimeoutError,
                        OSError,
                    ),
                )
                if not is_network_drop or attempt >= pol.max_retries:
                    raise exc

            # Calculate delay
            delay = pol.compute_delay(status_code or 500, attempt, retry_after)
            telemetry.record_retry(status_code)
            if on_retry:
                on_retry(attempt, exc, delay)

            time.sleep(delay)


async def execute_async(
    coro_fn: Callable[[], Awaitable[T]],
    *,
    policy: Optional[RetryPolicy] = None,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None,
) -> T:
    """
    Executes an asynchronous coroutine factory with retry and backoff semantics.
    """
    pol = policy or RetryPolicy()
    attempt = 0

    while True:
        try:
            return await coro_fn()
        except Exception as exc:
            attempt += 1
            status_code, retry_after = extract_status_and_retry_after(exc)

            if status_code is not None:
                if not pol.is_retryable(status_code, attempt):
                    if status_code in NON_RETRYABLE_4XX:
                        telemetry.record_fatal_client_error()
                    raise exc
            else:
                is_network_drop = isinstance(
                    exc,
                    (
                        httpx.TransportError,
                        ConnectionError,
                        TimeoutError,
                        OSError,
                    ),
                )
                if not is_network_drop or attempt >= pol.max_retries:
                    raise exc

            delay = pol.compute_delay(status_code or 500, attempt, retry_after)
            telemetry.record_retry(status_code)
            if on_retry:
                on_retry(attempt, exc, delay)

            await asyncio.sleep(delay)


class ResilientHttpClient:
    """
    Resilient synchronous HTTP client with strict 4xx non-retry and backoff policies.
    """
    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        policy: Optional[RetryPolicy] = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ):
        self.policy = policy or RetryPolicy()
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._client = httpx.Client(timeout=timeout_seconds, follow_redirects=False)

    def request(
        self,
        method: str,
        url: str,
        *,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        def _call() -> httpx.Response:
            resp = self._client.request(
                method=method,
                url=url,
                json=json,
                headers=headers,
                params=params,
            )
            # Raise for status so execute_sync catches 4xx/5xx codes
            resp.raise_for_status()
            return resp

        return execute_sync(_call, policy=self.policy)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ResilientHttpClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
