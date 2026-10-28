"""
Zero-dependency, thread-safe Prometheus & OpenTelemetry-compatible metrics exporter
for Moltbook Alpha API.

Tracks payment verification latencies, multi-RPC failover hop distributions,
webhook throughput, rate limit breaches, and active key counts.
"""

import threading
import urllib.parse
from typing import Dict, Tuple, List, Optional, Sequence, Any


DEFAULT_LATENCY_BUCKETS: Sequence[float] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# Bounded label allowlists to strictly prevent cardinality explosion
ALLOWED_ASSETS = {"SOL", "USDC", "UNKNOWN"}
ALLOWED_TIERS = {"tier_starter", "tier_pro", "tier_unlimited", "trial", "unknown"}
ALLOWED_PAYMENT_STATUSES = {"newly_minted", "already_redeemed", "failed", "rpc_error", "unknown"}
ALLOWED_WEBHOOK_STATUSES = {"newly_minted", "already_redeemed", "auth_failed", "verification_failed", "rpc_error", "unknown"}
ALLOWED_RPC_OUTCOMES = {"success", "rate_limited_429", "timeout", "error", "unknown"}
ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "UNKNOWN"}
KNOWN_NORMALIZED_ENDPOINTS = {
    "/",
    "/dashboard",
    "/metrics",
    "/v1/metrics/dashboard",
    "/v1/metrics/funnel",
    "/v1/admin/login",
    "/v1/admin/change-password",
    "/v1/admin/logout",
    "/v1/admin/session",
    "/v1/health",
    "/v1/payments/config",
    "/v1/payments/verify-solana",
    "/v1/payments/webhook",
    "/v1/payments/status/:signature",
    "/v1/keys/generate-demo",
    "/v1/briefing/latest",
    "/v1/account/quota",
    "unmatched_route",
}


def sanitize_label_value(val: Any) -> str:
    """Escapes backslashes, double-quotes, and newlines in Prometheus label values."""
    s = str(val)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def sanitize_help_text(text: str) -> str:
    """Escapes backslashes and newlines in Prometheus HELP strings."""
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def sanitize_provider_host(provider: str) -> str:
    """
    Extracts and strictly sanitizes hostname from RPC URL to prevent label cardinality attacks.
    Removes port numbers, authentication credentials, queries, and path components.
    """
    if not provider:
        return "unknown_provider"
    p = provider.strip()
    if not (p.startswith("http://") or p.startswith("https://")):
        p = "https://" + p
    try:
        parsed = urllib.parse.urlparse(p)
        host = parsed.hostname or "unknown_provider"
    except Exception:
        host = "unknown_provider"
    # Keep only safe hostname characters (alphanumeric, dot, dash)
    clean_host = "".join(c for c in host.lower() if c.isalnum() or c in ".-")
    if not clean_host or len(clean_host) > 64:
        return "unknown_provider"
    return clean_host


class MetricsRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        # Counters: (name, tuple_of_sorted_label_pairs) -> float
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # Gauges: (name, tuple_of_sorted_label_pairs) -> float
        self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # Histograms: (name, tuple_of_sorted_label_pairs) -> { "bucket_counts": dict, "sum": float, "count": int, "buckets": list }
        self._histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Dict] = {}
        # Metadata: name -> (help_text, metric_type)
        self._meta: Dict[str, Tuple[str, str]] = {}

    def register(self, name: str, help_text: str, metric_type: str):
        with self._lock:
            self._meta[name] = (help_text, metric_type)

    def counter_inc(self, name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0):
        if value < 0:
            raise ValueError(f"Counter increments must be non-negative, received {value}")
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def gauge_set(self, name: str, labels: Optional[Dict[str, str]] = None, value: float = 0.0):
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    def histogram_observe(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        buckets: Sequence[float] = DEFAULT_LATENCY_BUCKETS,
    ):
        key = self._make_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                bucket_counts = {b: 0 for b in sorted(buckets)}
                bucket_counts[float("inf")] = 0
                self._histograms[key] = {
                    "bucket_counts": bucket_counts,
                    "sum": 0.0,
                    "count": 0,
                    "buckets": sorted(buckets),
                }

            hist = self._histograms[key]
            hist["sum"] += float(value)
            hist["count"] += 1
            for b in hist["buckets"]:
                if value <= b:
                    hist["bucket_counts"][b] += 1
            hist["bucket_counts"][float("inf")] += 1

    @staticmethod
    def _make_key(name: str, labels: Optional[Dict[str, str]]) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
        if not labels:
            return name, ()
        sorted_pairs = tuple(sorted((str(k), str(v)) for k, v in labels.items()))
        return name, sorted_pairs

    @staticmethod
    def _format_labels(pairs: Tuple[Tuple[str, str], ...], extra: Optional[Dict[str, str]] = None) -> str:
        d = dict(pairs)
        if extra:
            d.update(extra)
        if not d:
            return ""
        items = []
        for k in sorted(d.keys()):
            val = sanitize_label_value(d[k])
            items.append(f'{k}="{val}"')
        return "{" + ",".join(items) + "}"

    def export_prometheus_text(self) -> str:
        """
        Exports all recorded metrics in the official Prometheus text exposition format (0.0.4).
        Takes a point-in-time snapshot under lock, then renders text without holding lock.
        """
        with self._lock:
            counters_snap = dict(self._counters)
            gauges_snap = dict(self._gauges)
            meta_snap = dict(self._meta)
            histograms_snap = {
                k: {
                    "bucket_counts": dict(v["bucket_counts"]),
                    "sum": v["sum"],
                    "count": v["count"],
                    "buckets": list(v["buckets"]),
                }
                for k, v in self._histograms.items()
            }

        # If nothing is registered or recorded, return empty exposition
        if not (counters_snap or gauges_snap or histograms_snap or meta_snap):
            return "\n"

        lines: List[str] = []
        all_names = sorted(set(
            [k[0] for k in counters_snap] +
            [k[0] for k in gauges_snap] +
            [k[0] for k in histograms_snap] +
            list(meta_snap.keys())
        ))

        for name in all_names:
            help_text, metric_type = meta_snap.get(name, ("Moltbook API metric", "untyped"))
            lines.append(f"# HELP {name} {sanitize_help_text(help_text)}")
            lines.append(f"# TYPE {name} {metric_type}")

            has_samples = False

            if metric_type == "counter":
                for (m_name, pairs), val in sorted(counters_snap.items()):
                    if m_name == name:
                        lbls = self._format_labels(pairs)
                        lines.append(f"{name}{lbls} {val:g}")
                        has_samples = True

            elif metric_type == "gauge":
                for (m_name, pairs), val in sorted(gauges_snap.items()):
                    if m_name == name:
                        lbls = self._format_labels(pairs)
                        lines.append(f"{name}{lbls} {val:g}")
                        has_samples = True

            elif metric_type == "histogram":
                for (m_name, pairs), hist in sorted(histograms_snap.items()):
                    if m_name == name:
                        has_samples = True
                        for b in hist["buckets"]:
                            cum_count = hist["bucket_counts"][b]
                            lbls = self._format_labels(pairs, extra={"le": f"{b:g}"})
                            lines.append(f"{name}_bucket{lbls} {cum_count}")
                        inf_lbls = self._format_labels(pairs, extra={"le": "+Inf"})
                        lines.append(f"{name}_bucket{inf_lbls} {hist['count']}")
                        lbls_sum_count = self._format_labels(pairs)
                        lines.append(f"{name}_sum{lbls_sum_count} {hist['sum']:.6f}")
                        lines.append(f"{name}_count{lbls_sum_count} {hist['count']}")

            # Only append section separator if samples were rendered
            if has_samples:
                lines.append("")
            else:
                lines.append("")

        return "\n".join(lines).strip() + "\n"

    def reset(self):
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# Global Metrics Registry Singleton
registry = MetricsRegistry()

# Register core application metrics
registry.register(
    "moltbook_payments_verified_total",
    "Total count of verified payment transactions by asset, tier, and outcome status.",
    "counter",
)
registry.register(
    "moltbook_payment_verification_duration_seconds",
    "Duration of on-chain payment verification in seconds.",
    "histogram",
)
registry.register(
    "moltbook_rpc_failover_hops_total",
    "Total RPC calls made during payment verification by provider endpoint and outcome.",
    "counter",
)
registry.register(
    "moltbook_webhooks_processed_total",
    "Total push webhook notifications processed by status.",
    "counter",
)
registry.register(
    "moltbook_rate_limit_exceeded_total",
    "Total rate limit rejections by endpoint.",
    "counter",
)
registry.register(
    "moltbook_api_keys_active_total",
    "Current total active API keys stored in SQLite.",
    "gauge",
)
registry.register(
    "moltbook_api_requests_total",
    "Total HTTP requests handled by endpoint, method, and status code.",
    "counter",
)


# Convenience Instrumentation Functions with Cardinality Bounds
def record_payment(asset: str, tier: str, status: str):
    clean_asset = asset.upper().strip() if asset else "UNKNOWN"
    if clean_asset not in ALLOWED_ASSETS:
        clean_asset = "UNKNOWN"

    clean_tier = tier.strip() if tier else "unknown"
    if clean_tier not in ALLOWED_TIERS:
        clean_tier = "unknown"

    clean_status = status.strip() if status else "unknown"
    if clean_status not in ALLOWED_PAYMENT_STATUSES:
        clean_status = "unknown"

    registry.counter_inc(
        "moltbook_payments_verified_total",
        {"asset": clean_asset, "tier": clean_tier, "status": clean_status},
    )


def record_verification_latency(asset: str, duration_seconds: float):
    clean_asset = asset.upper().strip() if asset else "UNKNOWN"
    if clean_asset not in ALLOWED_ASSETS:
        clean_asset = "UNKNOWN"

    registry.histogram_observe(
        "moltbook_payment_verification_duration_seconds",
        max(0.0, float(duration_seconds)),
        {"asset": clean_asset},
    )


def record_rpc_hop(provider: str, outcome: str):
    clean_provider = sanitize_provider_host(provider)
    clean_outcome = outcome.strip() if outcome else "unknown"
    if clean_outcome not in ALLOWED_RPC_OUTCOMES:
        clean_outcome = "unknown"

    registry.counter_inc(
        "moltbook_rpc_failover_hops_total",
        {"provider": clean_provider, "outcome": clean_outcome},
    )


def record_webhook(status: str):
    clean_status = status.strip() if status else "unknown"
    if clean_status not in ALLOWED_WEBHOOK_STATUSES:
        clean_status = "unknown"

    registry.counter_inc(
        "moltbook_webhooks_processed_total",
        {"status": clean_status},
    )


def record_rate_limit(endpoint: str):
    clean_endpoint = endpoint.strip() if endpoint else "unmatched_route"
    if clean_endpoint not in KNOWN_NORMALIZED_ENDPOINTS:
        clean_endpoint = "unmatched_route"

    registry.counter_inc(
        "moltbook_rate_limit_exceeded_total",
        {"endpoint": clean_endpoint},
    )


def record_request(endpoint: str, method: str, status_code: int):
    clean_endpoint = endpoint.strip() if endpoint else "unmatched_route"
    if clean_endpoint not in KNOWN_NORMALIZED_ENDPOINTS:
        clean_endpoint = "unmatched_route"

    clean_method = method.upper().strip() if method else "UNKNOWN"
    if clean_method not in ALLOWED_HTTP_METHODS:
        clean_method = "UNKNOWN"

    try:
        code_int = int(status_code)
        if 100 <= code_int <= 599:
            clean_status = str(code_int)
        else:
            clean_status = "unknown"
    except Exception:
        clean_status = "unknown"

    registry.counter_inc(
        "moltbook_api_requests_total",
        {"endpoint": clean_endpoint, "method": clean_method, "status_code": clean_status},
    )


def update_active_keys_gauge(active_count: int):
    registry.gauge_set("moltbook_api_keys_active_total", value=float(max(0, active_count)))
