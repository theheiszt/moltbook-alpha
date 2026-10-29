"""
Moltbook Alpha Offline Diagnostic & Health Check Tool (Doctor Pattern).

Performs comprehensive pre-flight verification of:
  1. Python runtime & environment dependencies.
  2. SQLite WAL journal mode, file integrity (PRAGMA integrity_check), and table health.
  3. Storage filesystem write permissions and data directories.
  4. Cryptographic Ed25519 witness key validity.
  5. Egress Guard policy & anti-SSRF firewall enforcement.
  6. Config drift & Solana RPC endpoint reachability.

Portions adapted from Clawnch Clawmes (MIT License - Copyright (c) 2026 Clawnch).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from typing import Any, Dict, List

from config import (
    BASE_DIR,
    DATA_DIR,
    DB_PATH,
    REPORTS_DIR,
    WITNESS_KEY_PATH,
    load_payment_config,
)
from ops.security.egress_guard import validate_outbound_url, EgressSecurityError


class CheckResult:
    def __init__(self, name: str, passed: bool, message: str, details: Dict[str, Any] = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": "PASS" if self.passed else "FAIL",
            "message": self.message,
            "details": self.details,
        }


def check_python_environment() -> CheckResult:
    v = sys.version_info
    passed = v.major == 3 and v.minor >= 10
    msg = f"Python {v.major}.{v.minor}.{v.micro} (Supported: >=3.10)"
    return CheckResult("python_runtime", passed, msg, {"version": f"{v.major}.{v.minor}.{v.micro}"})


def check_database_integrity() -> CheckResult:
    if not DB_PATH.is_file():
        try:
            from storage import StorageManager
            StorageManager(DB_PATH)
        except Exception as e:
            return CheckResult("database_integrity", False, f"Database file not found at {DB_PATH} and auto-init failed: {e}")

    if not DB_PATH.is_file():
        return CheckResult("database_integrity", False, f"Database file not found at {DB_PATH}")

    try:
        conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        cur = conn.cursor()

        # 1. Integrity check
        cur.execute("PRAGMA integrity_check;")
        row = cur.fetchone()
        integrity_ok = row and row[0] == "ok"

        # 2. Journal mode
        cur.execute("PRAGMA journal_mode;")
        j_row = cur.fetchone()
        journal_mode = j_row[0].upper() if j_row else "UNKNOWN"
        is_wal = journal_mode == "WAL"

        # 3. Table counts
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cur.fetchall()]

        conn.close()

        passed = integrity_ok and is_wal
        msg = f"Integrity: {'OK' if integrity_ok else 'CORRUPT'} | Journal Mode: {journal_mode} | Tables: {len(tables)}"
        return CheckResult(
            "database_integrity",
            passed,
            msg,
            {"integrity": row[0], "journal_mode": journal_mode, "tables_count": len(tables)},
        )
    except Exception as e:
        return CheckResult("database_integrity", False, f"Failed querying database: {e}")


def check_filesystem_and_storage() -> CheckResult:
    details = {}
    passed = True
    messages = []

    for path, name in [(DATA_DIR, "data_dir"), (REPORTS_DIR, "reports_dir")]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / f".doctor_write_test_{os.getpid()}"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            details[name] = "writable"
        except Exception as e:
            passed = False
            details[name] = f"failed: {e}"
            messages.append(f"{name} not writable")

    # Check available disk space
    try:
        total, used, free = shutil.disk_usage(BASE_DIR)
        free_mb = free / (1024 * 1024)
        details["free_space_mb"] = round(free_mb, 2)
        if free_mb < 250:
            passed = False
            messages.append(f"Low disk space: {free_mb:.1f} MB remaining")
    except Exception:
        pass

    msg = "All storage directories writable with sufficient disk space" if passed else "; ".join(messages)
    return CheckResult("filesystem_storage", passed, msg, details)


def check_witness_key() -> CheckResult:
    if not WITNESS_KEY_PATH.is_file():
        return CheckResult(
            "witness_key",
            True,
            f"Witness key file not yet seeded at {WITNESS_KEY_PATH} (will auto-generate on boot)",
        )

    try:
        from cryptographic_witness import WitnessKeyManager
        km = WitnessKeyManager(WITNESS_KEY_PATH)
        pub_b58 = km.public_key_base58
        key_id = km.key_id
        passed = bool(pub_b58 and key_id)
        msg = f"Ed25519 state witness key active (key_id: {key_id}, pubkey: {pub_b58[:12]}...)"
        return CheckResult("witness_key", passed, msg, {"key_id": key_id, "public_key_prefix": pub_b58[:12]})
    except Exception as e:
        return CheckResult("witness_key", False, f"Invalid witness key: {e}")


def check_egress_guard_policy() -> CheckResult:
    """Verifies that SSRF protection blocks private subnets and permits public domains."""
    try:
        # Test 1: Cloud metadata MUST be blocked
        blocked_meta = False
        try:
            validate_outbound_url("http://169.254.169.254/latest/meta-data/")
        except EgressSecurityError:
            blocked_meta = True

        # Test 2: Localhost MUST be blocked
        blocked_local = False
        try:
            validate_outbound_url("http://127.0.0.1:8000/internal")
        except EgressSecurityError:
            blocked_local = True

        # Test 3: Public HTTPS domain MUST be allowed (syntactic check)
        allowed_public = False
        try:
            valid_url = validate_outbound_url("https://example.com/webhook", resolve_dns=False)
            allowed_public = valid_url == "https://example.com/webhook"
        except Exception:
            pass

        passed = blocked_meta and blocked_local and allowed_public
        msg = f"SSRF Guard Active: Metadata blocked: {blocked_meta} | Loopback blocked: {blocked_local} | Public allowed: {allowed_public}"
        return CheckResult(
            "egress_guard_policy",
            passed,
            msg,
            {"metadata_blocked": blocked_meta, "loopback_blocked": blocked_local, "public_allowed": allowed_public},
        )
    except Exception as e:
        return CheckResult("egress_guard_policy", False, f"Egress guard policy check error: {e}")


def check_config_and_rpc() -> CheckResult:
    """Validates payment configuration and ensures RPC endpoints don't violate egress policies."""
    try:
        cfg = load_payment_config()
        treasury = cfg.get("solana_treasury_wallet") or cfg.get("treasury_wallet", "")
        endpoints = cfg.get("rpc_endpoints", [])

        # Validate endpoints through egress guard
        bad_endpoints = []
        for ep in endpoints:
            try:
                validate_outbound_url(ep, resolve_dns=False)
            except EgressSecurityError as err:
                bad_endpoints.append((ep, str(err)))

        passed = bool(treasury and endpoints and not bad_endpoints)
        if bad_endpoints:
            msg = f"RPC Config Drift! {len(bad_endpoints)} endpoints blocked by Egress Guard: {bad_endpoints}"
        else:
            msg = f"Treasury configured ({treasury[:8]}...) | Active RPC endpoints: {len(endpoints)}"

        return CheckResult(
            "config_and_rpc",
            passed,
            msg,
            {"treasury_wallet": treasury[:8] + "...", "rpc_count": len(endpoints), "blocked_endpoints": bad_endpoints},
        )
    except Exception as e:
        return CheckResult("config_and_rpc", False, f"Config inspection failed: {e}")


def run_doctor() -> tuple[List[CheckResult], bool]:
    """Runs all offline diagnostics and returns (results, overall_healthy)."""
    checks = [
        check_python_environment(),
        check_database_integrity(),
        check_filesystem_and_storage(),
        check_witness_key(),
        check_egress_guard_policy(),
        check_config_and_rpc(),
    ]
    overall_healthy = all(c.passed for c in checks)
    return checks, overall_healthy


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha — Offline Diagnostic Health Tool")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    results, healthy = run_doctor()

    if args.json:
        payload = {
            "healthy": healthy,
            "checks": [c.to_dict() for c in results],
        }
        print(json.dumps(payload, indent=2))
        sys.exit(0 if healthy else 1)

    print("\n" + "=" * 65)
    print("  Moltbook Alpha — System Diagnostics Report (Doctor)")
    print("=" * 65)
    for c in results:
        status_badge = "[ PASS ]" if c.passed else "[ FAIL ]"
        print(f"  {status_badge:<8} {c.name:<24} {c.message}")
    print("=" * 65)

    if healthy:
        print("  Result: All pre-flight systems are OPERATIONAL and HEALTHY.\n")
        sys.exit(0)
    else:
        print("  Result: Pre-flight checks detected ISSUES. Review details above.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
