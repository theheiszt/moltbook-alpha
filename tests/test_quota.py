"""
Tests for Account Quota Inspection, Bearer Token Authentication, and Subsystem Diagnostics.
"""

from pathlib import Path
from fastapi.testclient import TestClient
from api_server import app, storage


def test_quota_endpoint_requires_auth():
    client = TestClient(app)
    response = client.get("/v1/account/quota")
    assert response.status_code == 401
    data = response.json()
    assert data["detail"]["error"] == "Authentication Required"
    assert "remedy" in data["detail"]
    assert data["detail"]["remedy"]["action"] == "obtain_key"
    assert "WWW-Authenticate" in response.headers


def test_quota_endpoint_rejects_invalid_key():
    client = TestClient(app)
    response = client.get("/v1/account/quota", headers={"X-API-KEY": "molt_invalid_fake_key_12345"})
    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["error"] == "Invalid API Key"


def test_quota_endpoint_rejects_revoked_key():
    client = TestClient(app)
    raw_key, record = storage.create_api_key(tier="starter", credits=50, prefix_tag="molt_quota_rev")
    storage.revoke_key(record["key_prefix"])

    response = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["error"] == "API Key Revoked"


def test_quota_endpoint_returns_balance_without_deducting():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_pro", credits=300, prefix_tag="molt_pro_quota")

    # Call quota inspection 3 times
    for _ in range(3):
        resp = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["tier"] == "tier_pro"
        assert data["credits_remaining"] == 300
        assert data["is_active"] is True
        assert data["low_credit_warning"] is False

    # Verify storage balance was not decremented
    key_info = storage.get_key_info(raw_key)
    assert key_info["credits"] == 300


def test_quota_endpoint_supports_bearer_token():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=50, prefix_tag="molt_bearer")

    resp = client.get("/v1/account/quota", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["credits_remaining"] == 50


def test_quota_endpoint_low_credit_remedy():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=3, prefix_tag="molt_low")

    resp = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
    assert resp.status_code == 200
    data = resp.json()
    assert data["low_credit_warning"] is True
    assert "remedy" in data
    assert data["remedy"]["action"] == "top_up"
    assert "treasury_wallet" in data["remedy"]
    assert "pricing_tiers" in data["remedy"]


def test_briefing_supports_bearer_token(tmp_path: Path):
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_starter", credits=10, prefix_tag="molt_bearer_brief")

    resp = client.get("/v1/briefing/latest", headers={"Authorization": f"Bearer {raw_key}"})
    assert resp.status_code in (200, 404)
    # Credit was deducted via Bearer auth
    key_info = storage.get_key_info(raw_key)
    assert key_info["credits"] == 9


def test_health_endpoint_subsystems_diagnostics():
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "moltbook-alpha-api"
    assert data["database"] == "healthy"
    assert "subsystems" in data
    assert data["subsystems"]["database"]["status"] == "ok"
    assert data["subsystems"]["database"]["journal_mode"] == "WAL"
    assert data["subsystems"]["payments"]["status"] == "ok"
    assert "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx" in data["subsystems"]["payments"]["treasury_wallet"]
    assert data["subsystems"]["rpc_pool"]["cluster"] == "mainnet-beta"
    assert data["subsystems"]["rpc_pool"]["endpoints_configured"] >= 1


def test_atomic_quota_reservation_and_settlement(tmp_path):
    from storage import StorageManager

    db_path = tmp_path / "quota_res.db"
    sm = StorageManager(db_path)
    raw_key, record = sm.create_api_key(tier="starter", credits=10, prefix_tag="molt_res_test")

    # 1. Atomic reservation checks and reserves 1 credit
    res, state = sm.reserve_quota(raw_key, request_id="req_test_001")
    assert state == "ok"
    assert res is not None
    assert res["reservation_id"].startswith("res_")
    assert res["credits"] == 9  # Active remaining balance decremented under reservation

    # 2. Settle reservation
    cached_resp = {"success": True, "briefing": "Intelligence report content"}
    settled = sm.settle_quota(res["reservation_id"], response_payload=cached_resp)
    assert settled is True

    # 3. Ledger balances mathematically
    bal = sm.verify_ledger_balance(record["key_hash"])
    assert bal["balanced"] is True
    assert bal["actual_lot_balance"] == 9


def test_quota_reservation_release_on_error(tmp_path):
    from storage import StorageManager

    db_path = tmp_path / "quota_rel.db"
    sm = StorageManager(db_path)
    raw_key, record = sm.create_api_key(tier="starter", credits=5, prefix_tag="molt_rel_test")

    # Reserve 1 credit
    res, state = sm.reserve_quota(raw_key, request_id="req_fail_001")
    assert state == "ok"
    assert res["credits"] == 4

    # Simulate downstream execution failure -> release quota
    released = sm.release_quota(res["reservation_id"], reason="upstream_handler_timeout")
    assert released is True

    # Credit is restored back to active lot and API key
    key_info = sm.get_key_info(raw_key)
    assert key_info["credits"] == 5

    # Ledger audit trail records refund and balances
    bal = sm.verify_ledger_balance(record["key_hash"])
    assert bal["balanced"] is True
    assert bal["actual_lot_balance"] == 5
    assert bal["breakdown"]["refunded"] == 1


def test_quota_reservation_idempotency_replay(tmp_path):
    from storage import StorageManager

    db_path = tmp_path / "quota_idemp.db"
    sm = StorageManager(db_path)
    raw_key, _ = sm.create_api_key(tier="starter", credits=10, prefix_tag="molt_idemp_test")

    idemp_key = "idemp_unique_abc_123"

    # Call 1: Reserve & Settle
    res1, state1 = sm.reserve_quota(raw_key, idempotency_key=idemp_key, request_id="req_call1")
    assert state1 == "ok"
    cached_payload = {"success": True, "data": "first_result"}
    sm.settle_quota(res1["reservation_id"], response_payload=cached_payload)

    # Call 2: Same idempotency key replays cached response without burning additional credits
    res2, state2 = sm.reserve_quota(raw_key, idempotency_key=idemp_key, request_id="req_call2")
    assert state2 == "idempotent_replay"
    assert res2["cached_response"] == cached_payload

    # Balance is still 9 (only 1 credit was consumed)
    key_info = sm.get_key_info(raw_key)
    assert key_info["credits"] == 9


def test_quota_threshold_warning_crossing_and_deduplication(tmp_path):
    from storage import StorageManager

    db_path = tmp_path / "quota_thresh.db"
    sm = StorageManager(db_path)
    # 10 credits total: 50% = 5 remaining, 80% = 2 remaining, 90% = 1 remaining, 95% = 0 remaining
    raw_key, _ = sm.create_api_key(tier="starter", credits=10, prefix_tag="molt_thresh")

    # Deduct 5 credits (reaching 50% consumption)
    for _ in range(5):
        sm.authenticate_and_deduct(raw_key)

    details = sm.get_key_quota_details(raw_key)
    assert details["usage"]["percent_consumed"] == 50.0
    assert details["usage"]["warning_threshold_crossed"] == 0.50
    assert len(details["usage"]["active_alerts"]) == 1

    # Deduct 3 more credits (reaching 80% consumption)
    for _ in range(3):
        sm.authenticate_and_deduct(raw_key)

    details = sm.get_key_quota_details(raw_key)
    assert details["usage"]["percent_consumed"] == 80.0
    assert details["usage"]["warning_threshold_crossed"] == 0.80
    assert len(details["usage"]["active_alerts"]) == 2  # 0.50 and 0.80

    # Ensure no duplicate alerts for 0.80 are created on the next deduction
    sm.authenticate_and_deduct(raw_key)  # 9 credits consumed -> 90%
    details = sm.get_key_quota_details(raw_key)
    assert details["usage"]["warning_threshold_crossed"] == 0.90
    assert len(details["usage"]["active_alerts"]) == 3  # 0.50, 0.80, 0.90 (no duplicates)


def test_account_quota_enriched_usage_and_rate_limit_state():
    client = TestClient(app)
    raw_key, _ = storage.create_api_key(tier="tier_pro", credits=300, prefix_tag="molt_enriched")

    resp = client.get("/v1/account/quota", headers={"X-API-KEY": raw_key})
    assert resp.status_code == 200
    data = resp.json()

    # Enriched usage metadata
    assert "usage" in data
    assert data["usage"]["quota_limit"] >= 300
    assert data["usage"]["remaining"] == 300
    assert data["usage"]["percent_consumed"] == 0.0
    assert data["usage"]["configured_thresholds"] == [0.50, 0.80, 0.90, 0.95]

    # Enriched rate limit state
    assert "rate_limit_state" in data
    assert data["rate_limit_state"]["sustained_limit_per_min"] == 60
    assert data["rate_limit_state"]["burst_capacity"] == 5
    assert data["rate_limit_state"]["max_concurrent"] == 5
    assert data["rate_limit_state"]["remaining_tokens"] <= 5.0
