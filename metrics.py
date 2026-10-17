"""
Zero-dependency, thread-safe Prometheus & OpenTelemetry-compatible metrics exporter
for Moltbook Alpha API.

Tracks payment verification latencies, multi-RPC failover hop distributions,
webhook throughput, rate limit breaches, and active key counts.
"""

import threading
from typing import Dict, Tuple, List, Optional, Sequence



DEFAULT_LATENCY_BUCKETS: Sequence[float] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


class MetricsRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        # Counters: (name, tuple_of_sorted_label_pairs) -> float
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # Gauges: (name, tuple_of_sorted_label_pairs) -> float
        self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # Histograms: (name, tuple_of_sorted_label_pairs) -> { "buckets": dict(le -> count), "sum": float, "count": int }
        self._histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Dict] = {}
        # Metadata: name -> (help_text, metric_type)
        self._meta: Dict[str, Tuple[str, str]] = {}

    def register(self, name: str, help_text: str, metric_type: str):
        with self._lock:
            self._meta[name] = (help_text, metric_type)

    def counter_inc(self, name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0):
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def gauge_set(self, name: str, labels: Optional[Dict[str, str]] = None, value: float = 0.0):
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key] = value

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
            hist["sum"] += value
            hist["count"] += 1
            for b in hist["buckets"]:
                if value <= b:
                    hist["bucket_counts"][b] += 1
            hist["bucket_counts"][float("inf")] += 1

    @staticmethod
    def _make_key(name: str, labels: Optional[Dict[str, str]]) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
        if not labels:
            return name, ()
        sorted_pairs = tuple(sorted(labels.items()))
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
            val = str(d[k]).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            items.append(f'{k}="{val}"')
        return "{" + ",".join(items) + "}"

    def export_prometheus_text(self) -> str:
        """
        Exports all recorded metrics in the official Prometheus text exposition format (0.0.4).
        """
        lines: List[str] = []

        with self._lock:
            # Group keys by metric name
            all_names = sorted(set(
                [k[0] for k in self._counters] +
                [k[0] for k in self._gauges] +
                [k[0] for k in self._histograms] +
                list(self._meta.keys())
            ))

            for name in all_names:
                help_text, metric_type = self._meta.get(name, ("Moltbook API metric", "untyped"))
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {metric_type}")

                if metric_type == "counter":
                    for (m_name, pairs), val in sorted(self._counters.items()):
                        if m_name == name:
                            lbls = self._format_labels(pairs)
                            lines.append(f"{name}{lbls} {val:g}")

                elif metric_type == "gauge":
                    for (m_name, pairs), val in sorted(self._gauges.items()):
                        if m_name == name:
                            lbls = self._format_labels(pairs)
                            lines.append(f"{name}{lbls} {val:g}")

                elif metric_type == "histogram":
                    for (m_name, pairs), hist in sorted(self._histograms.items()):
                        if m_name == name:
                            # Buckets
                            cum_count = 0
                            for b in hist["buckets"]:
                                cum_count = hist["bucket_counts"][b]
                                lbls = self._format_labels(pairs, extra={"le": f"{b:g}"})
                                lines.append(f"{name}_bucket{lbls} {cum_count}")
                            inf_lbls = self._format_labels(pairs, extra={"le": "+Inf"})
                            lines.append(f"{name}_bucket{inf_lbls} {hist['count']}")
                            # Sum and Count
                            lbls_sum_count = self._format_labels(pairs)
                            lines.append(f"{name}_sum{lbls_sum_count} {hist['sum']:.6f}")
                            lines.append(f"{name}_count{lbls_sum_count} {hist['count']}")

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


# Convenience Instrumentation Functions
def record_payment(asset: str, tier: str, status: str):
    registry.counter_inc(
        "moltbook_payments_verified_total",
        {"asset": asset.upper(), "tier": tier, "status": status},
    )


def record_verification_latency(asset: str, duration_seconds: float):
    registry.histogram_observe(
        "moltbook_payment_verification_duration_seconds",
        duration_seconds,
        {"asset": asset.upper()},
    )


def record_rpc_hop(provider: str, outcome: str):
    # Simplify provider domain for clean cardinality (e.g. 'api.mainnet-beta.solana.com')
    clean_provider = provider.replace("https://", "").replace("http://", "").split("/")[0]
    registry.counter_inc(
        "moltbook_rpc_failover_hops_total",
        {"provider": clean_provider, "outcome": outcome},
    )


def record_webhook(status: str):
    registry.counter_inc(
        "moltbook_webhooks_processed_total",
        {"status": status},
    )


def record_rate_limit(endpoint: str):
    registry.counter_inc(
        "moltbook_rate_limit_exceeded_total",
        {"endpoint": endpoint},
    )


def record_request(endpoint: str, method: str, status_code: int):
    registry.counter_inc(
        "moltbook_api_requests_total",
        {"endpoint": endpoint, "method": method.upper(), "status_code": str(status_code)},
    )


def update_active_keys_gauge(active_count: int):
    registry.gauge_set("moltbook_api_keys_active_total", value=float(active_count))
