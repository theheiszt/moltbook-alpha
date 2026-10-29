"""
Tests for Moltbook Alpha Offline Diagnostic & Health Check Tool (ops/diagnostics/doctor.py).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from ops.diagnostics.doctor import (
    CheckResult,
    check_config_and_rpc,
    check_database_integrity,
    check_egress_guard_policy,
    check_filesystem_and_storage,
    check_python_environment,
    check_witness_key,
    run_doctor,
)


def test_check_result_serialization():
    res = CheckResult("test_check", True, "All good", {"metric": 42})
    d = res.to_dict()
    assert d["name"] == "test_check"
    assert d["status"] == "PASS"
    assert d["message"] == "All good"
    assert d["details"]["metric"] == 42

    res_fail = CheckResult("test_fail", False, "Error")
    assert res_fail.to_dict()["status"] == "FAIL"


def test_check_python_environment():
    res = check_python_environment()
    assert res.passed is True
    assert "Python" in res.message


def test_check_database_integrity():
    res = check_database_integrity()
    assert res.passed is True
    assert res.details.get("integrity") == "ok"
    assert res.details.get("journal_mode") == "WAL"
    assert res.details.get("tables_count", 0) > 0


def test_check_filesystem_and_storage():
    res = check_filesystem_and_storage()
    assert res.passed is True
    assert res.details.get("data_dir") == "writable"
    assert res.details.get("reports_dir") == "writable"
    assert res.details.get("free_space_mb", 0) > 0


def test_check_witness_key():
    res = check_witness_key()
    assert res.passed is True
    assert "wit_key_" in res.details.get("key_id", "")
    assert len(res.details.get("public_key_prefix", "")) > 0


def test_check_egress_guard_policy():
    res = check_egress_guard_policy()
    assert res.passed is True
    assert res.details.get("metadata_blocked") is True
    assert res.details.get("loopback_blocked") is True
    assert res.details.get("public_allowed") is True


def test_check_config_and_rpc():
    res = check_config_and_rpc()
    assert res.passed is True
    assert "rpc_count" in res.details
    assert res.details["blocked_endpoints"] == []


def test_check_config_and_rpc_detects_bad_endpoints():
    with patch("ops.diagnostics.doctor.load_payment_config") as mock_cfg:
        mock_cfg.return_value = {
            "solana_treasury_wallet": "BU5zBur4v96eX4A2u4dM4x5T3jY7q8L9k0",
            "rpc_endpoints": [
                "https://api.mainnet-beta.solana.com",
                "http://169.254.169.254/latest/meta-data",  # Malicious metadata endpoint
            ],
        }
        res = check_config_and_rpc()
        assert res.passed is False
        assert "RPC Config Drift" in res.message
        assert len(res.details["blocked_endpoints"]) == 1


def test_run_doctor_all_passing():
    results, healthy = run_doctor()
    assert healthy is True
    assert len(results) == 6
    names = [r.name for r in results]
    assert "python_runtime" in names
    assert "database_integrity" in names
    assert "filesystem_storage" in names
    assert "witness_key" in names
    assert "egress_guard_policy" in names
    assert "config_and_rpc" in names


def test_doctor_json_output(capsys):
    results, healthy = run_doctor()
    payload = {
        "healthy": healthy,
        "checks": [c.to_dict() for c in results],
    }
    dumped = json.dumps(payload)
    parsed = json.loads(dumped)
    assert parsed["healthy"] is True
    assert len(parsed["checks"]) == 6
