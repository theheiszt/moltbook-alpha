"""
Thread-Safe Sliding Window Rate Limiter & In-Flight Request Deduplicator.
Protects the Moltbook Alpha API from RPC resource exhaustion, brute-force signature
spamming, and denial-of-service attempts.
"""

import time
import threading
from typing import Dict, List, Tuple, Callable, Any, Optional


class SlidingWindowRateLimiter:
    """
    In-memory, thread-safe sliding window rate limiter.
    Tracks timestamps per key and prunes records outside the sliding window.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._history: Dict[str, List[float]] = {}

    def is_allowed(
        self,
        identifier: str,
        limit: int,
        window_seconds: int = 60,
        current_time: Optional[float] = None
    ) -> Tuple[bool, int]:
        """
        Determines if the request is within rate limits.
        Returns:
            Tuple[bool, int]: (allowed, retry_after_seconds)
            If allowed is False, retry_after_seconds indicates when the oldest record rolls off.
        """
        now = current_time if current_time is not None else time.time()
        window_start = now - window_seconds

        with self._lock:
            timestamps = self._history.setdefault(identifier, [])

            # Prune timestamps outside the current sliding window
            self._history[identifier] = [t for t in timestamps if t > window_start]
            valid_timestamps = self._history[identifier]

            if len(valid_timestamps) >= limit:
                # Calculate remaining seconds until the oldest timestamp expires
                oldest = valid_timestamps[0]
                retry_after = max(1, int(oldest + window_seconds - now + 0.999))
                return False, retry_after

            # Allow request and record timestamp
            valid_timestamps.append(now)
            return True, 0

    def reset(self, identifier: Optional[str] = None):
        """Clears history for testing or manual administrative reset."""
        with self._lock:
            if identifier:
                self._history.pop(identifier, None)
            else:
                self._history.clear()


class InFlightDeduplicator:
    """
    Prevents duplicate concurrent in-flight RPC operations for identical keys (e.g., transaction signatures).
    Ensures that if multiple concurrent requests arrive for the exact same signature,
    only the first request executes the expensive external verification while subsequent
    concurrent requests wait on the in-flight result.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._in_flight: Dict[str, threading.Event] = {}
        self._results: Dict[str, Tuple[Optional[Any], Optional[Exception]]] = {}

    def execute(self, key: str, func: Callable[[], Any]) -> Any:
        event = None
        is_leader = False

        with self._lock:
            if key in self._in_flight:
                event = self._in_flight[key]
            else:
                event = threading.Event()
                self._in_flight[key] = event
                is_leader = True

        if is_leader:
            try:
                res = func()
                with self._lock:
                    self._results[key] = (res, None)
                return res
            except Exception as exc:
                with self._lock:
                    self._results[key] = (None, exc)
                raise exc
            finally:
                event.set()
                # Clean up after brief delay so immediate followers get the result
                with self._lock:
                    self._in_flight.pop(key, None)
                    # Keep result temporarily available for waiting followers
        else:
            # Follower waits for the leader's execution
            completed = event.wait(timeout=15.0)
            if not completed:
                raise TimeoutError(f"In-flight operation for key '{key}' timed out.")

            with self._lock:
                result, error = self._results.get(key, (None, None))

            if error is not None:
                raise error
            return result
