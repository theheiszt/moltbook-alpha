"""
Process-isolated, file-persisted Read-Only Safe Mode for Moltbook Alpha.

Allows operators to place the system in an immediate read-only freeze during
investigations, database maintenance, or RPC degraded states without dropping
HTTP read queries, health checks, or administrative session management.

When Safe Mode is active:
- All GET, HEAD, and OPTIONS requests continue to be served normally.
- Administrative authentication and Safe Mode control routes remain operational.
- All state-mutating requests (POST, PUT, DELETE, PATCH) across business endpoints
  are rejected with HTTP 503 SERVICE_READ_ONLY_MODE and structured recovery details.
- Safe Mode state is persisted to disk to survive process restarts.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config import DATA_DIR


STATE_FILE_PATH = Path(DATA_DIR) / "safe_mode.json"

EXEMPT_PREFIXES = (
    "/v1/admin/login",
    "/v1/admin/logout",
    "/v1/admin/session",
    "/v1/admin/safemode",
)


class SafeModeController:
    """Manages system-wide read-only safe mode with disk persistence and thread safety."""

    def __init__(self, state_file: Optional[Path] = None):
        self._state_file = state_file or STATE_FILE_PATH
        self._lock = threading.RLock()
        self._active: bool = False
        self._reason: str = ""
        self._enabled_at: Optional[str] = None
        self._operator: Optional[str] = None
        self._load()

    def _load(self) -> None:
        try:
            if self._state_file.exists():
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._active = bool(data.get("active", False))
                    self._reason = str(data.get("reason", ""))
                    self._enabled_at = data.get("enabled_at")
                    self._operator = data.get("operator")
        except Exception:
            # Fall back to normal inactive mode if state file is unreadable
            self._active = False

    def _persist(self) -> None:
        try:
            os.makedirs(self._state_file.parent, exist_ok=True)
            payload = {
                "active": self._active,
                "reason": self._reason,
                "enabled_at": self._enabled_at,
                "operator": self._operator,
            }
            tmp_path = self._state_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            tmp_path.replace(self._state_file)
        except Exception:
            pass

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def enable(self, reason: str = "Administrative maintenance", operator: str = "admin") -> Dict[str, Any]:
        with self._lock:
            self._active = True
            self._reason = reason.strip() or "Administrative maintenance"
            self._enabled_at = datetime.now(timezone.utc).isoformat()
            self._operator = operator.strip() or "admin"
            self._persist()
            return self.get_status()

    def disable(self, operator: str = "admin") -> Dict[str, Any]:
        with self._lock:
            self._active = False
            self._reason = ""
            self._enabled_at = None
            self._operator = operator.strip() or "admin"
            self._persist()
            return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "reason": self._reason,
                "enabled_at": self._enabled_at,
                "operator": self._operator,
            }

    def is_mutation_allowed(self, method: str, path: str) -> bool:
        """Determines if the given HTTP method and path are permitted during Safe Mode."""
        m = method.upper()
        if m in ("GET", "HEAD", "OPTIONS"):
            return True

        with self._lock:
            if not self._active:
                return True

        # Check exempt administrative routes
        norm_path = path.rstrip("/")
        for prefix in EXEMPT_PREFIXES:
            if norm_path == prefix or norm_path.startswith(prefix + "/"):
                return True

        return False


# Global singleton instance
safe_mode_controller = SafeModeController()


def is_safe_mode_active() -> bool:
    return safe_mode_controller.is_active()


def enable_safe_mode(reason: str = "Administrative maintenance", operator: str = "admin") -> Dict[str, Any]:
    return safe_mode_controller.enable(reason=reason, operator=operator)


def disable_safe_mode(operator: str = "admin") -> Dict[str, Any]:
    return safe_mode_controller.disable(operator=operator)


def get_safe_mode_status() -> Dict[str, Any]:
    return safe_mode_controller.get_status()


def is_mutation_allowed(method: str, path: str) -> bool:
    return safe_mode_controller.is_mutation_allowed(method, path)
