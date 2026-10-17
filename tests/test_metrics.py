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
    record_request("/v1/custom", "POST", 201)
    update_active_keys_gauge(7)

    text = registry.export_prometheus_text()
    assert 'moltbook_rpc_failover_hops_total{outcome="success",provider="api.mainnet-beta.solana.com"} 1' in text
    assert 'moltbook_rpc_failover_hops_total{outcome="timeout",provider="api.mainnet-beta.solana.com"} 1' in text
    assert 'moltbook_rpc_failover_hops_total{outcome="rate_limited_429",provider="solana-rpc.publicnode.com"} 1' in text
    assert 'moltbook_payments_verified_total{asset="SOL",status="newly_minted",tier="tier_starter"} 1' in text
    assert 'moltbook_webhooks_processed_total{status="auth_failed"} 1' in text
    assert 'moltbook_rate_limit_exceeded_total{endpoint="/v1/payments/verify-solana"} 1' in text
    assert 'moltbook_api_requests_total{endpoint="/v1/custom",method="POST",status_code="201"} 1' in text
    assert "moltbook_api_keys_active_total 7" in text
    assert 'moltbook_payment_verification_duration_seconds_count{asset="SOL"} 1' in text

