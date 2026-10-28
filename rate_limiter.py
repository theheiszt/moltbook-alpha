"""
Moltbook Alpha Multi-Tier Rate Limiting, Concurrency Limiting & Deduplication.
Protects the API against high-frequency agent loops, burst exhaustion, concurrent
quota overspend, and denial-of-service attempts.

Rate Limiting Model:
- Algorithm: Token Bucket with SQLite WAL distributed coordination and thread-safe in-memory fallback.
- Burst Capacity (B): 5 tokens (allows an instantaneous burst of up to 5 requests in a 1-second window).
- Sustained Refill Rate (R): 60 requests/minute = 1.0 token/second.
- Interaction: An idle client has up to 5 tokens ready to spend immediately. Once the burst is consumed,
  further requests are strictly bounded by the sustained refill rate of 1 request per second.
  The per-second burst is an independent ceiling, preventing high-frequency loops while permitting
  responsive interactive agent bursts.
- Concurrency Limit: Maximum 5 concurrent in-flight requests per API key.
- Timeout Guard: 30-second request execution timeout.
"""

import math
import secrets
import threading
import time
from typing import Dict, List, Tuple, Callable, Any, Optional


class TokenBucketRateLimiter:
    """
    Token Bucket Rate Limiter supporting burst capacity and sustained refill rate.
    Coordinates across worker processes via SQLite WAL transactions when storage is provided,
    with an in-memory fast-path fallback.
    """

    def __init__(
        self,
        default_capacity: float = 5.0,
        default_refill_per_min: float = 60.0,
        storage: Optional[Any] = None,
        storage_manager: Optional[Any] = None,
        fail_open: bool = True,
    ):
        self.default_capacity = float(default_capacity)
        self.default_refill_rate = float(default_refill_per_min) / 60.0  # tokens per second
        self.storage = storage_manager if storage_manager is not None else storage
        self.fail_open = fail_open
        self._lock = threading.Lock()
        self._memory_buckets: Dict[str, Tuple[float, float]] = {}  # key -> (tokens, last_refill)

    def is_allowed(
        self,
        key: str,
        capacity: Optional[float] = None,
        refill_per_min: Optional[float] = None,
        cost: float = 1.0,
        current_time: Optional[float] = None,
        now: Optional[float] = None,
        fail_open: Optional[bool] = None,
    ) -> Tuple[bool, int, float]:
        """
        Determines if a request with `cost` tokens is allowed.
        Returns:
            Tuple[bool, int, float]: (allowed, retry_after_seconds, remaining_tokens)
        """
        cap = float(capacity) if capacity is not None else self.default_capacity
        refill = (float(refill_per_min) / 60.0) if refill_per_min is not None else self.default_refill_rate
        effective_now = current_time if current_time is not None else (now if now is not None else time.time())
        should_fail_open = fail_open if fail_open is not None else self.fail_open

        # Database-backed shared coordination (cross-process / multi-worker)
        if self.storage is not None:
            try:
                with self.storage.connection() as conn:
                    with conn:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT tokens, last_refill FROM rate_limit_tokens WHERE key = ?",
                            (key,)
                        )
                        row = cur.fetchone()
                        if row:
                            prev_tokens = float(row["tokens"])
                            last_refill = float(row["last_refill"])
                            elapsed = max(0.0, effective_now - last_refill)
                            current_tokens = min(cap, prev_tokens + (elapsed * refill))
                        else:
                            current_tokens = cap

                        if current_tokens >= cost:
                            new_tokens = current_tokens - cost
                            cur.execute(
                                """
                                INSERT INTO rate_limit_tokens (key, tokens, last_refill)
                                VALUES (?, ?, ?)
                                ON CONFLICT(key) DO UPDATE SET tokens = excluded.tokens, last_refill = excluded.last_refill
                                """,
                                (key, new_tokens, effective_now)
                            )
                            return True, 0, new_tokens
                        else:
                            needed = cost - current_tokens
                            retry_after = max(1, math.ceil(needed / refill)) if refill > 0 else 60
                            cur.execute(
                                """
                                INSERT INTO rate_limit_tokens (key, tokens, last_refill)
                                VALUES (?, ?, ?)
                                ON CONFLICT(key) DO UPDATE SET tokens = excluded.tokens, last_refill = excluded.last_refill
                                """,
                                (key, current_tokens, effective_now)
                            )
                            return False, retry_after, current_tokens
            except Exception:
                if should_fail_open:
                    return True, 0, cap
                else:
                    return False, 1, 0.0

        # Thread-safe in-memory path
        with self._lock:
            prev_tokens, last_refill = self._memory_buckets.get(key, (cap, effective_now))
            elapsed = max(0.0, effective_now - last_refill)
            current_tokens = min(cap, prev_tokens + (elapsed * refill))

            if current_tokens >= cost:
                new_tokens = current_tokens - cost
                self._memory_buckets[key] = (new_tokens, effective_now)
                return True, 0, new_tokens
            else:
                needed = cost - current_tokens
                retry_after = max(1, math.ceil(needed / refill)) if refill > 0 else 60
                self._memory_buckets[key] = (current_tokens, effective_now)
                return False, retry_after, current_tokens

    def get_remaining(self, key: str, capacity: Optional[float] = None, refill_per_min: Optional[float] = None, current_time: Optional[float] = None) -> float:
        """Returns the current available tokens without deducting."""
        cap = float(capacity) if capacity is not None else self.default_capacity
        refill = (float(refill_per_min) / 60.0) if refill_per_min is not None else self.default_refill_rate
        now = current_time if current_time is not None else time.time()

        if self.storage is not None:
            try:
                with self.storage.connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT tokens, last_refill FROM rate_limit_tokens WHERE key = ?", (key,))
                    row = cur.fetchone()
                    if row:
                        elapsed = max(0.0, now - float(row["last_refill"]))
                        return min(cap, float(row["tokens"]) + (elapsed * refill))
                    return cap
            except Exception:
                pass

        with self._lock:
            prev_tokens, last_refill = self._memory_buckets.get(key, (cap, now))
            elapsed = max(0.0, now - last_refill)
            return min(cap, prev_tokens + (elapsed * refill))

    def reset(self, key: Optional[str] = None):
        """Clears rate limit state for a key or all keys."""
        with self._lock:
            if key:
                self._memory_buckets.pop(key, None)
            else:
                self._memory_buckets.clear()

        if self.storage is not None:
            try:
                with self.storage.connection() as conn:
                    with conn:
                        if key:
                            conn.execute("DELETE FROM rate_limit_tokens WHERE key = ?", (key,))
                        else:
                            conn.execute("DELETE FROM rate_limit_tokens")
            except Exception:
                pass


class ConcurrencyLimiter:
    """
    Limits concurrent in-flight requests per API key or agent identity.
    Enforces maximum concurrent execution slots (default: 5) to prevent
    burst resource starvation and worker pool exhaustion.
    """

    def __init__(
        self,
        default_max_concurrent: int = 5,
        storage: Optional[Any] = None,
        storage_manager: Optional[Any] = None,
    ):
        self.default_max_concurrent = default_max_concurrent
        self.storage = storage_manager if storage_manager is not None else storage
        self._lock = threading.Lock()
        self._in_flight: Dict[str, Dict[str, float]] = {}  # key -> {slot_id: expires_at}

    def acquire(
        self,
        key: str,
        max_concurrent: Optional[int] = None,
        ttl_seconds: float = 60.0,
        current_time: Optional[float] = None,
    ) -> Tuple[bool, Optional[str], int]:
        """
        Attempts to acquire a concurrency execution slot for `key`.
        Returns:
            Tuple[bool, Optional[str], int]: (acquired, slot_id, current_in_flight_count)
        """
        limit = max_concurrent if max_concurrent is not None else self.default_max_concurrent
        now = current_time if current_time is not None else time.time()
        expires_at = now + ttl_seconds
        slot_id = f"slot_{secrets.token_hex(8)}"

        if self.storage is not None:
            try:
                with self.storage.connection() as conn:
                    with conn:
                        cur = conn.cursor()
                        # Reap expired slots
                        cur.execute("DELETE FROM rate_limit_concurrency WHERE expires_at < ?", (now,))
                        cur.execute("SELECT COUNT(*) as count FROM rate_limit_concurrency WHERE key = ?", (key,))
                        active_count = cur.fetchone()["count"]
                        if active_count >= limit:
                            return False, None, active_count

                        cur.execute(
                            "INSERT INTO rate_limit_concurrency (slot_id, key, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                            (slot_id, key, now, expires_at)
                        )
                        return True, slot_id, active_count + 1
            except Exception:
                pass

        # In-memory tracking
        with self._lock:
            slots = self._in_flight.setdefault(key, {})
            # Reap expired slots
            expired = [sid for sid, exp in slots.items() if exp < now]
            for sid in expired:
                slots.pop(sid, None)

            if len(slots) >= limit:
                return False, None, len(slots)

            slots[slot_id] = expires_at
            return True, slot_id, len(slots)

    def release(self, slot_id: Optional[str], key: Optional[str] = None):
        """Releases an in-flight concurrency slot."""
        if not slot_id:
            return

        if self.storage is not None:
            try:
                with self.storage.connection() as conn:
                    with conn:
                        conn.execute("DELETE FROM rate_limit_concurrency WHERE slot_id = ?", (slot_id,))
            except Exception:
                pass

        with self._lock:
            if key and key in self._in_flight:
                self._in_flight[key].pop(slot_id, None)
            else:
                for _, slots in self._in_flight.items():
                    if slot_id in slots:
                        slots.pop(slot_id, None)
                        break

    def get_in_flight(self, key: str, current_time: Optional[float] = None) -> int:
        """Returns the current number of in-flight requests for `key`."""
        now = current_time if current_time is not None else time.time()
        if self.storage is not None:
            try:
                with self.storage.connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT COUNT(*) as count FROM rate_limit_concurrency WHERE key = ? AND expires_at >= ?",
                        (key, now)
                    )
                    return cur.fetchone()["count"]
            except Exception:
                pass

        with self._lock:
            slots = self._in_flight.get(key, {})
            return sum(1 for exp in slots.values() if exp >= now)

    def reset(self, key: Optional[str] = None):
        """Clears concurrency slots."""
        with self._lock:
            if key:
                self._in_flight.pop(key, None)
            else:
                self._in_flight.clear()

        if self.storage is not None:
            try:
                with self.storage.connection() as conn:
                    with conn:
                        if key:
                            conn.execute("DELETE FROM rate_limit_concurrency WHERE key = ?", (key,))
                        else:
                            conn.execute("DELETE FROM rate_limit_concurrency")
            except Exception:
                pass


class SlidingWindowRateLimiter:
    """
    In-memory, thread-safe sliding window rate limiter.
    Maintained for backwards-compatibility with existing unit tests and legacy callers.
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
        now = current_time if current_time is not None else time.time()
        window_start = now - window_seconds

        with self._lock:
            timestamps = self._history.setdefault(identifier, [])
            self._history[identifier] = [t for t in timestamps if t > window_start]
            valid_timestamps = self._history[identifier]

            if len(valid_timestamps) >= limit:
                oldest = valid_timestamps[0]
                retry_after = max(1, int(oldest + window_seconds - now + 0.999))
                return False, retry_after

            valid_timestamps.append(now)
            return True, 0

    def reset(self, identifier: Optional[str] = None):
        with self._lock:
            if identifier:
                self._history.pop(identifier, None)
            else:
                self._history.clear()


class InFlightDeduplicator:
    """
    Prevents duplicate concurrent in-flight operations for identical keys (e.g. transaction signatures).
    Ensures that if multiple concurrent requests arrive for the exact same signature,
    only the first request executes while subsequent concurrent requests wait on the in-flight result.
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
                with self._lock:
                    self._in_flight.pop(key, None)
        else:
            completed = event.wait(timeout=15.0)
            if not completed:
                raise TimeoutError(f"In-flight operation for key '{key}' timed out.")

            with self._lock:
                result, error = self._results.get(key, (None, None))

            if error is not None:
                raise error
            return result
