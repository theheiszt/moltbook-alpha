"""
Moltbook Alpha — Central Application State and Singletons (app_state.py).

Provides shared singletons, storage, rate limiters, witness managers,
market intelligence engines, and the MeteredCall gate across all routes
without circular dependencies.
"""

import functools
import ipaddress
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder

from config import (
    BASE_DIR,
    DB_PATH,
    DEFAULT_RATE_LIMIT_BURST_CAPACITY,
    DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
    DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    WITNESS_KEY_PATH,
    get_trusted_proxies,
    load_payment_config,
)
from cryptographic_witness import WitnessKeyManager, WitnessManager
from data_products import DataProductExchange
from errors import ApiError
from intel_engine import IntelEngine
from metrics import record_rate_limit
from ops.trading.dex_microstructure import (
    DEXMicrostructureEngine,
    microstructure_broadcaster,
)
from payment_verifier import (
    NanoInvoicePaymentAdapter,
    SolanaRefundDispatcher,
)
from rate_limiter import (
    ConcurrencyLimiter,
    InFlightDeduplicator,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)
from storage import StorageManager

logger = logging.getLogger("moltbook.api")

SERVER_START_TIME = time.time()
PROJECT_ROOT = Path(__file__).resolve().parent
_assets_dir = PROJECT_ROOT / "assets"

# In-memory TTL cache for dashboard metrics (prevents SQLite lock contention from concurrent/rapid UI polling)
_DASHBOARD_METRICS_CACHE_LOCK = threading.Lock()
_DASHBOARD_METRICS_CACHE = {"timestamp": 0.0, "payload": None}
_DASHBOARD_METRICS_CACHE_TTL_SECONDS = 10.0

# Initialize storage, rate limiters, deduplicator, cryptographic state witness manager, and intel engine
storage = StorageManager(DB_PATH)
rate_limiter = SlidingWindowRateLimiter()
token_bucket_limiter = TokenBucketRateLimiter(
    default_capacity=DEFAULT_RATE_LIMIT_BURST_CAPACITY,
    default_refill_per_min=DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    storage=storage,
)
concurrency_limiter = ConcurrencyLimiter(
    default_max_concurrent=DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
    storage=storage,
)
in_flight_deduplicator = InFlightDeduplicator()
witness_key_manager = WitnessKeyManager(WITNESS_KEY_PATH)
witness_manager = WitnessManager(storage, witness_key_manager)
intel_engine = IntelEngine(storage)
payment_cfg = load_payment_config()
nano_adapter = NanoInvoicePaymentAdapter(
    merchant_address=payment_cfg.get(
        "nano_treasury_address",
        "nano_3t1sxtuxyjgdabj6miwn6st58p8x553i8ybkikoc9ozn7mra7kk71iysfyn1",
    )
)
refund_dispatcher = SolanaRefundDispatcher(
    treasury_wallet=payment_cfg["solana_treasury_wallet"]
)

dex_microstructure = DEXMicrostructureEngine(broadcaster=microstructure_broadcaster)
data_product_exchange = DataProductExchange()

# Seed default baseline pools with realistic institutional prices ($182 SOL)
dex_microstructure.parse_raydium_clmm_pool(
    pool_id="Raydium_SOL_USDC",
    pair="SOL/USDC",
    pool_state={
        "current_tick": -15620,
        "current_price": 182.15,
        "ticks": [
            {"tick": -15630, "price": 182.05, "liquidity_usd": 125000.0},
            {"tick": -15625, "price": 182.10, "liquidity_usd": 185000.0},
            {"tick": -15620, "price": 182.15, "liquidity_usd": 220000.0},
            {"tick": -15615, "price": 182.20, "liquidity_usd": 195000.0},
            {"tick": -15610, "price": 182.25, "liquidity_usd": 140000.0},
        ],
    },
)

dex_microstructure.parse_orca_whirlpool(
    pool_id="Orca_SOL_USDC",
    pair="SOL/USDC",
    pool_state={
        "tick_current_index": -15620,
        "price": 182.38,
        "ticks": [
            {"index": -15630, "price": 182.28, "liquidity_net": 1200.0},
            {"index": -15625, "price": 182.33, "liquidity_net": 1800.0},
            {"index": -15620, "price": 182.38, "liquidity_net": 2100.0},
            {"index": -15615, "price": 182.43, "liquidity_net": -1700.0},
            {"index": -15610, "price": 182.48, "liquidity_net": -1300.0},
        ],
    },
)

dex_microstructure.parse_meteora_dlmm(
    pool_id="Meteora_SOL_USDC",
    pair="SOL/USDC",
    pool_state={
        "active_id": -15620,
        "current_price": 182.25,
        "bins": [
            {"bin_id": -15630, "price": 182.15, "amount_x_usd": 60000.0, "amount_y_usd": 65000.0},
            {"bin_id": -15625, "price": 182.20, "amount_x_usd": 90000.0, "amount_y_usd": 95000.0},
            {"bin_id": -15620, "price": 182.25, "amount_x_usd": 110000.0, "amount_y_usd": 105000.0},
            {"bin_id": -15615, "price": 182.30, "amount_x_usd": 95000.0, "amount_y_usd": 90000.0},
            {"bin_id": -15610, "price": 182.35, "amount_x_usd": 70000.0, "amount_y_usd": 65000.0},
        ],
    },
)

# Seed standard production liquidity depths for Solana CLMM arbitrage
dex_microstructure.seed_default_pools(base_sol_price=182.50)

# Run one-time legacy migration from api_keys.json if present (skipping any admin backdoors)
legacy_keys_file = BASE_DIR / "api_keys.json"
if legacy_keys_file.exists():
    storage.migrate_from_json(legacy_keys_file)


def is_trusted_proxy(ip_str: str, trusted_proxies: list[str]) -> bool:
    """Verifies whether an IP address matches an explicitly trusted proxy or network."""
    if not trusted_proxies or not ip_str:
        return False
    if ip_str in trusted_proxies:
        return True
    try:
        addr = ipaddress.ip_address(ip_str)
        for net_str in trusted_proxies:
            try:
                net = ipaddress.ip_network(net_str, strict=False)
                if addr in net:
                    return True
            except ValueError:
                continue
    except ValueError:
        return False
    return False


def get_client_ip(request: Request) -> str:
    """
    Extracts authentic client IP address safely according to trusted-hop topology.
    Only respects X-Forwarded-For if the immediate peer (request.client.host)
    is an explicitly trusted proxy configured in TRUSTED_PROXIES.

    When traversing multi-hop chains, parses from right-to-left (nearest hop to farthest):
    skips hops that belong to TRUSTED_PROXIES, and selects the first non-trusted IP.
    This prevents untrusted clients from injecting spoofed IPs into the leftmost position.
    """
    peer_ip = request.client.host if request.client else "127.0.0.1"
    trusted_proxies = get_trusted_proxies()

    if not is_trusted_proxy(peer_ip, trusted_proxies):
        return peer_ip

    # If behind a trusted proxy and CF-Connecting-IP is provided, prioritize authentic edge IP
    cf_connecting = request.headers.get("cf-connecting-ip")
    if cf_connecting:
        try:
            ipaddress.ip_address(cf_connecting.strip())
            return cf_connecting.strip()
        except ValueError:
            pass

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer_ip

    # Split and clean all hops in the chain
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    if not hops:
        return peer_ip

    # Traverse from rightmost (nearest upstream proxy) to leftmost (farthest origin)
    for hop in reversed(hops):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            # Malformed IP in chain - fail closed to peer_ip
            return peer_ip

        if not is_trusted_proxy(hop, trusted_proxies):
            # This is the first untrusted entity in the proxy chain -> authentic client
            return hop

    # If every hop in the chain is in TRUSTED_PROXIES, return the leftmost trusted hop
    return hops[0]


def _payment_required_detail(
    message: str = "Access requires an active API key or payment.",
    price: Optional[str] = None,
) -> Dict[str, Any]:
    cfg = load_payment_config()
    return {
        "error": "Payment Required",
        "message": message,
        "price": price
        or "Starter: $1 (50 queries), Pro: $5 (300 queries), Premium: $20 (10,000 queries / 30 days).",
        "purchase_instructions": {
            "treasury_wallet": cfg["solana_treasury_wallet"],
            "rates": cfg["rates"],
            "topup_packages": cfg.get("topup_packages", {}),
            "verify_endpoint": "POST /v1/payments/verify-solana",
        },
    }


def extract_api_key(request: Request) -> Optional[str]:
    """Returns the caller's key from X-API-KEY or Authorization: Bearer (never from the query string)."""
    raw_key = (request.headers.get("x-api-key") or "").strip()
    if not raw_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_key = auth_header[7:].strip()
    return raw_key or None


class IdempotentReplay(Exception):
    """Raised when a metered request repeats a settled idempotency key; carries the cached response."""

    def __init__(self, payload: Dict[str, Any]):
        super().__init__("idempotent replay")
        self.payload = payload


class MeteredCall:
    """
    Shared paid-access gate for metered endpoints.

    Entering the context authenticates the key, applies per-IP and per-key rate limits,
    takes a concurrency slot, and reserves 1 credit (two-phase, idempotency-key aware).
    Call settle(payload) on success. Any exception releases the reservation (zero charge
    on failure), and the concurrency slot is always freed on exit.

        with MeteredCall(request, "/v1/intel/signals") as call:
            return call.settle(build_payload())
    """

    def __init__(
        self,
        request: Request,
        endpoint: str,
        ip_bucket: Optional[str] = None,
        payment_required_detail: Optional[Dict[str, Any]] = None,
    ):
        self.request = request
        self.endpoint = endpoint
        self.ip_bucket = ip_bucket or endpoint
        self.payment_required_detail = payment_required_detail
        self.request_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
        self.reservation: Dict[str, Any] = {}
        self._slot_id: Optional[str] = None
        self._rate_key: Optional[str] = None
        self._settled = False

    def __enter__(self) -> "MeteredCall":
        request = self.request
        client_ip = get_client_ip(request)

        # General rate limit: 60 requests per minute per IP
        allowed, retry_after = rate_limiter.is_allowed(f"{self.ip_bucket}:{client_ip}", limit=60, window_seconds=60)
        if not allowed:
            record_rate_limit(self.endpoint)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Please retry in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

        raw_key = extract_api_key(request)
        if not raw_key:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=self.payment_required_detail or _payment_required_detail(),
            )

        rate_key = f"key:{storage.hash_key(raw_key)}"

        # Token bucket rate limiting (Burst 5, Sustained 60/min)
        tb_allowed, tb_retry_after, tb_remaining = token_bucket_limiter.is_allowed(
            rate_key,
            capacity=DEFAULT_RATE_LIMIT_BURST_CAPACITY,
            refill_per_min=DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
        )
        request.state.rate_limit_limit = DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN
        request.state.rate_limit_remaining = tb_remaining
        request.state.rate_limit_reset = tb_retry_after

        if not tb_allowed:
            record_rate_limit(self.endpoint)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Request rate exceeded. Please retry in {tb_retry_after} seconds.",
                headers={
                    "Retry-After": str(tb_retry_after),
                    "X-RateLimit-Limit": str(DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(tb_retry_after),
                },
            )

        # Concurrency Limiter (Max 5 concurrent requests)
        slot_acquired, slot_id, _ = concurrency_limiter.acquire(
            rate_key,
            max_concurrent=DEFAULT_RATE_LIMIT_MAX_CONCURRENT,
        )
        if not slot_acquired:
            record_rate_limit(self.endpoint)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Maximum concurrent requests reached (5). Please back off and retry.",
                headers={"Retry-After": "1"},
            )

        self._slot_id, self._rate_key = slot_id, rate_key
        request.state.concurrency_slot_id = slot_id
        request.state.concurrency_rate_key = rate_key

        try:
            self._reserve(raw_key)
        except BaseException:
            self._release_slot()
            raise
        return self

    def _reserve(self, raw_key: str) -> None:
        # Two-Phase Quota Reservation with Idempotency Key
        idempotency_key = self.request.headers.get("idempotency-key") or self.request.headers.get("x-idempotency-key")
        res_info, state = storage.reserve_quota(raw_key, idempotency_key=idempotency_key, request_id=self.request_id)

        if state == "ok" and res_info and res_info.get("reservation_id"):
            self.reservation = res_info
            self.request.state.quota_reservation_id = res_info["reservation_id"]
            return

        if state == "idempotent_replay":
            raise IdempotentReplay(res_info.get("cached_response") or {
                "status": "settled",
                "reservation_id": res_info.get("reservation_id"),
                "idempotency_key": res_info.get("idempotency_key"),
                "message": "Request previously settled under this idempotency key. Cached payload not retained.",
            })
        if state == "in_flight":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="A request with this idempotency key is currently in flight. Please retry shortly.",
                headers={"Retry-After": "1"},
            )
        if state == "revoked":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key has been revoked.")
        if state == "entitlement_expired":
            detail = _payment_required_detail()
            detail["error"] = "Entitlement Expired"
            detail["message"] = "Premium entitlement has expired. Renew your Premium subscription to continue spending credits."
            del detail["price"]
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)
        if state == "exhausted":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Key credits exhausted. Top up your balance via Solana USDC.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key. Submit payment to /v1/payments/verify-solana or contact administrator.",
        )

    def settle(self, payload: Any) -> Any:
        """Commits the reserved credit, caching the payload for idempotent replay, and returns it."""
        reservation_id = self.reservation.get("reservation_id")
        if reservation_id and not self._settled:
            storage.settle_quota(reservation_id, response_payload=jsonable_encoder(payload))
            self.request.state.quota_reservation_id = None
        self._settled = True
        return payload

    def _release_slot(self) -> None:
        if self._slot_id and self._rate_key:
            concurrency_limiter.release(self._slot_id, self._rate_key)
        self._slot_id = None
        self.request.state.concurrency_slot_id = None

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc is None:
                if not self._settled:
                    self.settle(None)
                return False
            reservation_id = self.reservation.get("reservation_id")
            if reservation_id and not self._settled:
                reason = "http_exception" if isinstance(exc, (HTTPException, ApiError)) else type(exc).__name__
                storage.release_quota(reservation_id, reason=reason)
                self.request.state.quota_reservation_id = None
        finally:
            self._release_slot()

        if isinstance(exc, Exception) and not isinstance(exc, (HTTPException, ApiError)):
            logger.exception("Metered endpoint %s failed [req_id: %s]", self.endpoint, self.request_id)
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error serving {self.endpoint}. Incident recorded with request ID {self.request_id}.",
            ) from exc
        return False


def metered(endpoint: str):
    """
    Route decorator that puts a sync handler behind MeteredCall (1 credit per successful call).
    The handler must declare a `request: Request` parameter. Place it below the @router route decorator.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with MeteredCall(kwargs["request"], endpoint) as call:
                return call.settle(fn(*args, **kwargs))
        return wrapper
    return decorator
