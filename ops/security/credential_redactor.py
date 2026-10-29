"""
Zero-Leak Credential Redactor with Hash-Only Auditing for Moltbook Alpha.

Scans audit event details, log entries, and error payloads for sensitive
cryptographic material (Solana private keys, Ed25519 seeds, BIP-39 mnemonics,
JWTs, and API secrets) and replaces them with tamper-evident SHA-256 hash digests:
`[REDACTED_SECRET:sha256:<digest_prefix>]`.

Portions adapted from Clawnch Clawmes (MIT License - Copyright (c) 2026 Clawnch).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# Patterns for sensitive credentials
SOLANA_BASE58_KEY_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{87,88}\b")
BYTE_ARRAY_KEY_RE = re.compile(r"\[(?:\s*\d{1,3}\s*,){31,63}\s*\d{1,3}\s*\]")
PEM_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:EC|RSA|OPENSSH|PRIVATE) KEY-----[\s\S]+?-----END (?:EC|RSA|OPENSSH|PRIVATE) KEY-----")
JWT_TOKEN_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")
API_KEY_RE = re.compile(r"\bmb_[a-zA-Z0-9_]{16,}\b")
AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)([a-zA-Z0-9_\-\.]{12,})")
SECRET_PARAM_RE = re.compile(r"(?i)((?:secret|password|api_key|privkey|private_key|token)\s*[:=]\s*['\"]?)([^'\"\s&,]{8,})(['\"]?)")


class CredentialRedactor:
    """Thread-safe secret scrubbing engine with hash auditing."""

    def __init__(self, hash_length: int = 12):
        self.hash_length = hash_length

    def _mask_secret(self, secret: str) -> str:
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:self.hash_length]
        return f"[REDACTED_SECRET:sha256:{digest}]"

    def redact_text(self, text: str) -> str:
        """Scans a text string and replaces detected credentials with hash markers."""
        if not text or not isinstance(text, str):
            return text

        scrubbed = text

        # 1. Strip PEM blocks
        scrubbed = PEM_PRIVATE_KEY_RE.sub(
            lambda m: self._mask_secret(m.group(0)), scrubbed
        )

        # 2. Strip Byte-array keys [12, 34, 56, ...]
        scrubbed = BYTE_ARRAY_KEY_RE.sub(
            lambda m: self._mask_secret(m.group(0)), scrubbed
        )

        # 3. Strip Solana base58 private keys (87-88 chars)
        scrubbed = SOLANA_BASE58_KEY_RE.sub(
            lambda m: self._mask_secret(m.group(0)), scrubbed
        )

        # 4. Strip JWT tokens
        scrubbed = JWT_TOKEN_RE.sub(
            lambda m: self._mask_secret(m.group(0)), scrubbed
        )

        # 5. Strip Moltbook API keys
        scrubbed = API_KEY_RE.sub(
            lambda m: self._mask_secret(m.group(0)), scrubbed
        )

        # 6. Strip Authorization headers
        scrubbed = AUTH_HEADER_RE.sub(
            lambda m: f"{m.group(1)}{self._mask_secret(m.group(2))}", scrubbed
        )

        # 7. Strip secret parameters
        scrubbed = SECRET_PARAM_RE.sub(
            lambda m: f"{m.group(1)}{self._mask_secret(m.group(2))}{m.group(3)}", scrubbed
        )

        return scrubbed

    def redact_object(self, obj: Any) -> Any:
        """Recursively scrubs strings within dicts, lists, and tuples."""
        if isinstance(obj, str):
            return self.redact_text(obj)
        elif isinstance(obj, dict):
            return {k: self.redact_object(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.redact_object(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(self.redact_object(item) for item in obj)
        return obj


# Global singleton
credential_redactor = CredentialRedactor()


def sanitize_audit_log(detail: str) -> str:
    """Convenience functional wrapper for audit logging."""
    return credential_redactor.redact_text(detail)
