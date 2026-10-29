"""
Machine-Readable Step-Up Authorization Nonce Store (ConfirmStore) for Moltbook Alpha.

Provides single-use cryptographic confirmation nonces for high-consequence,
financially consequential, or destructive actions (such as on-chain refund dispatches).

Guarantees:
  1. Cryptographic nonces generated using secrets.token_urlsafe(32).
  2. Bounded TTL (default 300 seconds / 5 minutes).
  3. Action & parameter fingerprinting: H(action || principal_id || canonical_payload)
     ensuring nonces cannot be substituted for different parameters or actors.
  4. Single-use atomic consumption: prevents replay or double-execution attacks.
  5. Machine-readable challenge/response mapping into standard error contracts (HTTP 428 / 410).

Portions adapted from Clawnch Clawmes (MIT License - Copyright (c) 2026 Clawnch).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple


class ConfirmationChallenge:
    """Represents an active confirmation challenge holding operation intent."""

    def __init__(
        self,
        nonce: str,
        action: str,
        principal_id: str,
        fingerprint: str,
        expires_at: float,
        consequence_summary: Dict[str, Any],
    ):
        self.nonce = nonce
        self.action = action
        self.principal_id = principal_id
        self.fingerprint = fingerprint
        self.issued_at = time.time()
        self.expires_at = expires_at
        self.consequence_summary = consequence_summary

    def is_expired(self, now: Optional[float] = None) -> bool:
        current = now if now is not None else time.time()
        return current > self.expires_at


class ConfirmStore:
    """Thread-safe in-memory store for single-use confirmation nonces."""

    def __init__(self, default_ttl_seconds: float = 300.0, strict_mode: bool = True):
        self.default_ttl_seconds = default_ttl_seconds
        self._challenges: Dict[str, ConfirmationChallenge] = {}
        self._lock = threading.Lock()
        self.strict_mode: bool = strict_mode

    @staticmethod
    def compute_fingerprint(action: str, principal_id: str, params: Dict[str, Any]) -> str:
        """Computes deterministic canonical hash of operation parameters."""
        canonical_params = json.dumps(params, sort_keys=True, separators=(",", ":"))
        raw = f"{action}:{principal_id}:{canonical_params}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def issue(
        self,
        action: str,
        principal_id: str,
        params: Dict[str, Any],
        consequence_summary: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[float] = None,
    ) -> ConfirmationChallenge:
        """Issues a new single-use confirmation challenge."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        now = time.time()
        expires_at = now + ttl

        fingerprint = self.compute_fingerprint(action, principal_id, params)
        nonce = f"conf_{secrets.token_urlsafe(32)}"

        challenge = ConfirmationChallenge(
            nonce=nonce,
            action=action,
            principal_id=principal_id,
            fingerprint=fingerprint,
            expires_at=expires_at,
            consequence_summary=consequence_summary or {},
        )

        with self._lock:
            # Purge expired challenges during issue
            expired_keys = [k for k, v in self._challenges.items() if v.is_expired(now)]
            for k in expired_keys:
                del self._challenges[k]

            self._challenges[nonce] = challenge

        return challenge

    def verify_and_consume(
        self,
        nonce: str,
        action: str,
        principal_id: str,
        params: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Atomically verifies and burns a confirmation challenge.

        Returns:
          (True, "OK") if verified and consumed.
          (False, reason_message) on failure (invalid, expired, consumed, or fingerprint mismatch).
        """
        now = time.time()
        expected_fp = self.compute_fingerprint(action, principal_id, params)

        with self._lock:
            challenge = self._challenges.get(nonce)
            if not challenge:
                return False, "Confirmation nonce does not exist or was already consumed."

            if challenge.is_expired(now):
                del self._challenges[nonce]
                return False, "Confirmation nonce has expired."

            if challenge.action != action:
                return False, f"Confirmation nonce was issued for '{challenge.action}', not '{action}'."

            if challenge.fingerprint != expected_fp:
                return False, "Confirmation nonce parameter fingerprint mismatch (parameters modified)."

            # Atomically consume the nonce
            del self._challenges[nonce]
            return True, "OK"

    def clear(self) -> None:
        """Clears all challenges from the store."""
        with self._lock:
            self._challenges.clear()


# Module-level singleton
confirm_store = ConfirmStore()
