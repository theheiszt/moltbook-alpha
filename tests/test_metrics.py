"""
Unit and Integration Tests for Prometheus / OpenTelemetry Metrics System.
Verifies MetricsRegistry thread-safety, text exposition format, latency histograms,
RPC failover hop distributions, active keys gauge, and the /metrics endpoint.
"""

import pytest
from starlette.testclient import TestClient

from api_server import app
from metrics import (
    MetricsRegistry,
    registry,
    record_payment,
    record_verification_latency,
    record_rpc_hop,
    record_webhook,
    record_rate_limit,
    record_request,
    update_active_keys_gauge,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Resets global registry before and after every test."""
    registry.reset()
    yield
    registry.reset()


def test_metrics_registry_counter():
    reg = MetricsRegistry()
    reg.register("test_counter", "A test counter", "counter")
    reg.counter_inc("test_counter", {"status": "ok"}, value=1.0)
    reg.counter_inc("test_counter", {"status": "ok"}, value=2.5)
    reg.counter_inc("test_counter", {"status": "error"}, value=1.0)

    out = reg.export_prometheus_text()
    assert "# HELP test_counter A test counter" in out
    assert "# TYPE test_counter counter" in out
    assert 'test_counter{status="ok"} 3.5' in out
    assert 'test_counter{status="error"} 1' in out


def test_metrics_registry_gauge():
    reg = MetricsRegistry()
    reg.register("test_gauge", "A test gauge", "gauge")
    reg.gauge_set("test_gauge", value=42.0)
    out = reg.export_prometheus_text()
    assert "# HELP test_gauge A test gauge" in out
    assert "# TYPE test_gauge gauge" in out
    assert "test_gauge 42" in out

    reg.gauge_set("test_gauge", value=17.0)
    out2 = reg.export_prometheus_text()
    assert "test_gauge 17" in out2


def test_metrics_registry_histogram_buckets():
    reg = MetricsRegistry()
    reg.register("test_latency", "Latency in seconds", "histogram")
    # Custom buckets
    buckets = (0.1, 0.5, 1.0)
    reg.histogram_observe("test_latency", 0.05, {"asset": "SOL"}, buckets=buckets)
    reg.histogram_observe("test_latency", 0.3, {"asset": "SOL"}, buckets=buckets)
    reg.histogram_observe("test_latency", 0.8, {"asset": "SOL"}, buckets=buckets)
    reg.histogram_observe("test_latency", 2.0, {"asset": "SOL"}, buckets=buckets)

    out = reg.export_prometheus_text()
    assert "# HELP test_latency Latency in seconds" in out
    assert "# TYPE test_latency histogram" in out
    # 0.05 <= 0.1 -> count 1
    assert 'test_latency_bucket{asset="SOL",le="0.1"} 1' in out
    # 0.05, 0.3 <= 0.5 -> count 2
    assert 'test_latency_bucket{asset="SOL",le="0.5"} 2' in out
    # 0.05, 0.3, 0.8 <= 1.0 -> count 3
    assert 'test_latency_bucket{asset="SOL",le="1"} 3' in out
    # All 4 in +Inf
    assert 'test_latency_bucket{asset="SOL",le="+Inf"} 4' in out
    assert 'test_latency_count{asset="SOL"} 4' in out
    # Sum: 0.05 + 0.3 + 0.8 + 2.0 = 3.15
    assert 'test_latency_sum{asset="SOL"} 3.150000' in out


def test_metrics_endpoint_response_format():
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "version=0.0.4" in resp.headers["content-type"]

    body = resp.text
    assert "# HELP moltbook_payments_verified_total" in body
    assert "# HELP moltbook_payment_verification_duration_seconds" in body
    assert "# HELP moltbook_rpc_failover_hops_total" in body
    assert "# HELP moltbook_webhooks_processed_total" in body
    assert "# HELP moltbook_rate_limit_exceeded_total" in body
    assert "# HELP moltbook_api_keys_active_total" in body
    assert "# HELP moltbook_api_requests_total" in body


def test_metrics_middleware_tracks_requests():
    client = TestClient(app)
    # Trigger requests
    resp1 = client.get("/v1/health")
    assert resp1.status_code == 200
    resp2 = client.get("/v1/payments/config")
    assert resp2.status_code == 200

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    body = metrics_resp.text

    assert 'moltbook_api_requests_total{endpoint="/v1/health",method="GET",status_code="200"}' in body
    assert 'moltbook_api_requests_total{endpoint="/v1/payments/config",method="GET",status_code="200"}' in body


def test_convenience_functions_and_rpc_hops():
    record_rpc_hop("https://api.mainnet-beta.solana.com", "success")
    record_rpc_hop("https://api.mainnet-beta.solana.com", "timeout")
    record_rpc_hop("https://solana-rpc.publicnode.com", "rate_limited_429")
    record_verification_latency("SOL", 0.125)
    record_payment("SOL", "tier_starter", "newly_minted")
    record_webhook("auth_failed")
    record_rate_limit("/v1/payments/verify-solana")
    record_request("/v1/payments/config", "GET", 200)
    record_request("/v1/custom", "POST", 201)  # unknown route -> clamped to unmatched_route
    update_active_keys_gauge(7)

    text = registry.export_prometheus_text()
    assert 'moltbook_rpc_failover_hops_total{outcome="success",provider="api.mainnet-beta.solana.com"} 1' in text
    assert 'moltbook_rpc_failover_hops_total{outcome="timeout",provider="api.mainnet-beta.solana.com"} 1' in text
    assert 'moltbook_rpc_failover_hops_total{outcome="rate_limited_429",provider="solana-rpc.publicnode.com"} 1' in text
    assert 'moltbook_payments_verified_total{asset="SOL",status="newly_minted",tier="tier_starter"} 1' in text
    assert 'moltbook_webhooks_processed_total{status="auth_failed"} 1' in text
    assert 'moltbook_rate_limit_exceeded_total{endpoint="/v1/payments/verify-solana"} 1' in text
    assert 'moltbook_api_requests_total{endpoint="/v1/payments/config",method="GET",status_code="200"} 1' in text
    assert 'moltbook_api_requests_total{endpoint="unmatched_route",method="POST",status_code="201"} 1' in text
    assert "moltbook_api_keys_active_total 7" in text
    assert 'moltbook_payment_verification_duration_seconds_count{asset="SOL"} 1' in text


def test_empty_registry_and_zero_values():
    reg = MetricsRegistry()
    assert reg.export_prometheus_text() == "\n"

    reg.register("zero_counter", "Counter at zero", "counter")
    reg.register("zero_gauge", "Gauge at zero", "gauge")
    reg.register("zero_hist", "Hist at zero", "histogram")

    reg.counter_inc("zero_counter", {"status": "ok"}, value=0.0)
    reg.gauge_set("zero_gauge", value=0.0)
    reg.histogram_observe("zero_hist", 0.0, buckets=(0.1, 1.0))

    out = reg.export_prometheus_text()
    assert 'zero_counter{status="ok"} 0' in out
    assert "zero_gauge 0" in out
    assert 'zero_hist_bucket{le="0.1"} 1' in out
    assert 'zero_hist_bucket{le="1"} 1' in out
    assert 'zero_hist_bucket{le="+Inf"} 1' in out
    assert "zero_hist_sum 0.000000" in out
    assert "zero_hist_count 1" in out


def test_label_and_help_text_escaping():
    reg = MetricsRegistry()
    reg.register("escaped_metric", 'Help with "quotes", \\backslashes\\, and \nnewlines', "counter")
    reg.counter_inc(
        "escaped_metric",
        {"label_with_quote": 'value"with"quotes', "label_with_newline": "val\nnewline", "label_slash": "val\\slash"},
        value=5.0,
    )
    out = reg.export_prometheus_text()
    assert r'# HELP escaped_metric Help with "quotes", \\backslashes\\, and \nnewlines' in out
    assert r'label_with_quote="value\"with\"quotes"' in out
    assert r'label_with_newline="val\nnewline"' in out
    assert r'label_slash="val\\slash"' in out
    assert " 5" in out


def test_cardinality_bounds_and_input_sanitization():
    # Asset clamping
    record_payment("DOGECOIN", "tier_starter", "newly_minted")
    # Tier clamping
    record_payment("SOL", "unconfigured_tier_hacker", "newly_minted")
    # Status clamping
    record_payment("SOL", "tier_starter", "arbitrary_status_injection")
    # Provider URL sanitization with port, credentials, path, query
    record_rpc_hop("https://user:password@rpc.helius.xyz:8899/v1/?api-key=secret", "success")
    # Provider with excessive length
    record_rpc_hop("https://" + "a" * 100 + ".com", "error")
    # Endpoint normalization
    record_rate_limit("/attacker/probing/for/paths/12345")
    # Invalid method and status code
    record_request("/random/404/path", "PATCH_EXPLOIT", 999)

    out = registry.export_prometheus_text()
    # Clamped asset
    assert 'moltbook_payments_verified_total{asset="UNKNOWN",status="newly_minted",tier="tier_starter"} 1' in out
    # Clamped tier
    assert 'moltbook_payments_verified_total{asset="SOL",status="newly_minted",tier="unknown"} 1' in out
    # Clamped status
    assert 'moltbook_payments_verified_total{asset="SOL",status="unknown",tier="tier_starter"} 1' in out
    # Sanitized host (no credentials, port, path, query, secrets)
    assert 'provider="rpc.helius.xyz"' in out
    assert "secret" not in out
    assert "8899" not in out
    # Excessive length clamped
    assert 'provider="unknown_provider"' in out
    # Clamped rate limit endpoint
    assert 'moltbook_rate_limit_exceeded_total{endpoint="unmatched_route"} 1' in out
    # Clamped request endpoint, method, status_code
    assert 'moltbook_api_requests_total{endpoint="unmatched_route",method="UNKNOWN",status_code="unknown"} 1' in out


def test_concurrent_scraping_and_mutation_thread_safety():
    import threading

    reg = MetricsRegistry()
    reg.register("concurrent_counter", "Concurrent counter", "counter")
    reg.register("concurrent_hist", "Concurrent histogram", "histogram")

    num_threads = 16
    increments_per_thread = 250
    exceptions = []

    def worker(tid: int):
        try:
            for _ in range(increments_per_thread):
                reg.counter_inc("concurrent_counter", {"worker": f"w_{tid % 4}"}, value=1.0)
                reg.histogram_observe("concurrent_hist", 0.05, {"worker": f"w_{tid % 4}"})
                # Periodic concurrent read / scrape simulation
                _ = reg.export_prometheus_text()
        except Exception as e:
            exceptions.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not exceptions, f"Exceptions occurred during concurrent metrics execution: {exceptions}"

    final_text = reg.export_prometheus_text()
    expected_total = num_threads * increments_per_thread
    assert "concurrent_hist_count" in final_text
    # All 4 workers combined sum to expected_total
    total_obs = sum(
        v["count"] for v in reg._histograms.values()
    )
    assert total_obs == expected_total


def test_storage_active_keys_count_ttl_caching(tmp_path):
    from storage import StorageManager

    db_file = tmp_path / "test_ttl.db"
    storage = StorageManager(db_file)

    # Initially 0
    assert storage.get_active_keys_count() == 0

    # Create 3 keys
    storage.create_api_key("tier_starter", 50)
    storage.create_api_key("tier_pro", 300)
    raw3, rec3 = storage.create_api_key("tier_unlimited", 999999)

    # First call updates cache
    assert storage.get_active_keys_count() == 3

    # Direct DB mutation without going through StorageManager cache invalidation
    with storage.connection() as conn:
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE key_hash = ?", (rec3["key_hash"],))
        conn.commit()

    # Cached value is returned within TTL (15s)
    assert storage.get_active_keys_count(max_age_seconds=15.0) == 3

    # Forcing refresh or expiration returns fresh value (2)
    assert storage.get_active_keys_count(max_age_seconds=0.0) == 2


def test_metrics_endpoint_bearer_token_protection(monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "prod_super_secret_metrics_token")

    client = TestClient(app)

    # 1. Without auth header -> 401 Unauthorized
    resp_no_auth = client.get("/metrics")
    assert resp_no_auth.status_code == 401
    assert "Unauthorized" in resp_no_auth.json()["detail"]

    # 2. With wrong auth header -> 401 Unauthorized
    resp_wrong_auth = client.get("/metrics", headers={"Authorization": "Bearer wrong_token"})
    assert resp_wrong_auth.status_code == 401

    # 3. With malformed auth schemes and values -> 401 Unauthorized
    malformed_headers = [
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer "},
        {"Authorization": "Token prod_super_secret_metrics_token"},
        {"Authorization": ""},
        {"Authorization": "Bearer prod_super_secret_metrics_token_extra"},
        {"Authorization": "bearer prod_super_secret_metrics_token"},
    ]
    for h in malformed_headers:
        resp = client.get("/metrics", headers=h)
        assert resp.status_code == 401, f"Expected 401 for header {h}, got {resp.status_code}"
        assert resp.headers.get("WWW-Authenticate") == "Bearer"

    # 4. With correct auth header -> 200 OK with Prometheus exposition
    resp_valid = client.get("/metrics", headers={"Authorization": "Bearer prod_super_secret_metrics_token"})
    assert resp_valid.status_code == 200
    assert "# HELP" in resp_valid.text


def test_metrics_endpoint_public_when_token_unset(monkeypatch):
    # When METRICS_BEARER_TOKEN is unset or empty, endpoint serves metrics without auth
    monkeypatch.delenv("METRICS_BEARER_TOKEN", raising=False)

    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "# HELP" in resp.text
