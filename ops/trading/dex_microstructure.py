"""
Moltbook Alpha — High-Frequency Solana DEX Microstructure Engine.

Implements Concentrated Liquidity Market Maker (CLMM) orderbook depth parsing,
tick bounds calculation, bid-ask imbalance analysis, and real-time flash-loan
spoofing detection across Raydium CLMM, Orca Whirlpools, and Meteora DLMM.
"""

import asyncio
import hashlib
import hmac
import json
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Set


class DEXProtocol(str, Enum):
    RAYDIUM_CLMM = "raydium_clmm"
    ORCA_WHIRLPOOL = "orca_whirlpool"
    METEORA_DLMM = "meteora_dlmm"


@dataclass
class TickLiquidityDepth:
    """Represents concentrated liquidity distribution for a Solana DEX pool."""
    pool_id: str
    protocol: DEXProtocol
    pair: str
    current_tick: int
    current_price: float
    bid_depth_usd: float          # Liquidity within specified basis points (e.g. 50 bps) below mid
    ask_depth_usd: float          # Liquidity within specified basis points (e.g. 50 bps) above mid
    imbalance_ratio: float        # (Bid - Ask) / (Bid + Ask), [-1.0, 1.0]
    active_bin_count: int
    timestamp_utc: float
    raw_bins: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "protocol": self.protocol.value,
            "pair": self.pair,
            "current_tick": self.current_tick,
            "current_price": round(self.current_price, 6),
            "bid_depth_usd": round(self.bid_depth_usd, 2),
            "ask_depth_usd": round(self.ask_depth_usd, 2),
            "imbalance_ratio": round(self.imbalance_ratio, 4),
            "active_bin_count": self.active_bin_count,
            "timestamp_utc": self.timestamp_utc,
        }


@dataclass
class MicrostructureAnomaly:
    """Represents a detected market manipulation or liquidity anomaly."""
    pool_id: str
    protocol: DEXProtocol
    anomaly_type: str             # "TICK_VACUUM", "SPOOFED_WALL", "FEE_VOLATILITY_SPIKE"
    severity: str                 # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    confidence_score: float       # 0.0 to 1.0
    evidence_details: Dict[str, Any]
    detected_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "protocol": self.protocol.value,
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "confidence_score": round(self.confidence_score, 4),
            "evidence_details": self.evidence_details,
            "detected_at": self.detected_at,
        }


class DEXMicrostructureEngine:
    """
    High-performance analytical engine for parsing Solana DEX pools
    and detecting flash-loan spoofing, tick vacuums, and toxic flow.
    """

    def __init__(
        self,
        rpc_endpoints: Optional[List[str]] = None,
        broadcaster: Optional["MicrostructureBroadcaster"] = None,
    ):
        self.rpc_endpoints = rpc_endpoints or [
            "https://api.mainnet-beta.solana.com",
            "https://solana-rpc.publicnode.com",
            "https://rpc.ankr.com/solana",
        ]
        self._history: Dict[str, List[TickLiquidityDepth]] = {}
        self._active_anomalies: List[MicrostructureAnomaly] = []
        self.broadcaster = broadcaster

    # =========================================================================
    # Mathematical Transformations (CLMM Tick-to-Price)
    # =========================================================================

    @staticmethod
    def tick_to_price(tick: int, decimals_a: int = 9, decimals_b: int = 6) -> float:
        """
        Converts an integer CLMM tick index to price:
        P = 1.0001^tick * 10^(decimals_a - decimals_b)
        """
        try:
            raw_ratio = math.pow(1.0001, tick)
            decimal_scale = math.pow(10, decimals_a - decimals_b)
            return raw_ratio * decimal_scale
        except (OverflowError, ValueError):
            return 0.0

    @staticmethod
    def price_to_tick(price: float, decimals_a: int = 9, decimals_b: int = 6) -> int:
        """
        Inverts price to nearest integer CLMM tick index:
        tick = round(ln(P * 10^(decimals_b - decimals_a)) / ln(1.0001))
        """
        if price <= 0:
            return 0
        decimal_scale = math.pow(10, decimals_b - decimals_a)
        target = price * decimal_scale
        if target <= 0:
            return 0
        return int(round(math.log(target) / math.log(1.0001)))

    @staticmethod
    def compute_bid_ask_imbalance(
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        mid_price: float,
        depth_bps: float = 50.0,
    ) -> Tuple[float, float, float]:
        """
        Calculates cumulative bid depth, ask depth, and orderbook imbalance
        within a basis-point radius of the mid-price.

        Returns:
            Tuple of (bid_depth_usd, ask_depth_usd, imbalance_ratio)
            imbalance_ratio = (bid - ask) / (bid + ask)
        """
        if mid_price <= 0:
            return 0.0, 0.0, 0.0

        bps_factor = depth_bps / 10000.0
        bid_threshold = mid_price * (1.0 - bps_factor)
        ask_threshold = mid_price * (1.0 + bps_factor)

        # Bids: price >= bid_threshold and price <= mid_price
        bid_depth = sum(
            px * size for px, size in bids if bid_threshold <= px <= mid_price
        )
        # Asks: price <= ask_threshold and price >= mid_price
        ask_depth = sum(
            px * size for px, size in asks if mid_price <= px <= ask_threshold
        )

        total_depth = bid_depth + ask_depth
        if total_depth <= 0:
            imbalance = 0.0
        else:
            imbalance = (bid_depth - ask_depth) / total_depth

        return bid_depth, ask_depth, max(-1.0, min(1.0, imbalance))

    # =========================================================================
    # Protocol-Specific Parsers
    # =========================================================================

    def parse_raydium_clmm_pool(
        self,
        pool_id: str,
        pair: str,
        pool_state: Dict[str, Any],
        depth_bps: float = 50.0,
    ) -> TickLiquidityDepth:
        """
        Parses Raydium CLMM concentrated liquidity state.
        Accepts state containing 'current_tick', 'current_price', and 'bins' or 'ticks'.
        """
        current_tick = int(pool_state.get("current_tick", 0))
        current_price = float(pool_state.get("current_price", self.tick_to_price(current_tick)))
        raw_ticks = pool_state.get("ticks", pool_state.get("bins", []))

        bids: List[Tuple[float, float]] = []
        asks: List[Tuple[float, float]] = []

        for item in raw_ticks:
            tick_idx = int(item.get("tick", 0))
            liq_usd = float(item.get("liquidity_usd", item.get("liquidity", 0)))
            px = float(item.get("price", self.tick_to_price(tick_idx)))
            size = (liq_usd / px) if px > 0 else 0.0

            if px <= current_price:
                bids.append((px, size))
            else:
                asks.append((px, size))

        bid_depth, ask_depth, imbalance = self.compute_bid_ask_imbalance(
            bids, asks, current_price, depth_bps=depth_bps
        )

        depth = TickLiquidityDepth(
            pool_id=pool_id,
            protocol=DEXProtocol.RAYDIUM_CLMM,
            pair=pair,
            current_tick=current_tick,
            current_price=current_price,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            imbalance_ratio=imbalance,
            active_bin_count=len(raw_ticks),
            timestamp_utc=float(pool_state.get("timestamp_utc", time.time())),
            raw_bins=raw_ticks,
        )
        self._record_depth(depth)
        return depth

    def parse_orca_whirlpool(
        self,
        pool_id: str,
        pair: str,
        pool_state: Dict[str, Any],
        depth_bps: float = 50.0,
    ) -> TickLiquidityDepth:
        """Parses Orca Whirlpool concentrated liquidity state."""
        current_tick = int(pool_state.get("tick_current_index", pool_state.get("current_tick", 0)))
        current_price = float(pool_state.get("price", self.tick_to_price(current_tick)))
        whirlpool_ticks = pool_state.get("ticks", [])

        bids: List[Tuple[float, float]] = []
        asks: List[Tuple[float, float]] = []

        for item in whirlpool_ticks:
            tick_idx = int(item.get("index", item.get("tick", 0)))
            px = float(item.get("price", self.tick_to_price(tick_idx)))
            liq = float(item.get("liquidity_net", item.get("liquidity", 0)))
            liq_usd = abs(liq) * (px if px > 0 else 1.0)
            size = (liq_usd / px) if px > 0 else 0.0

            if px <= current_price:
                bids.append((px, size))
            else:
                asks.append((px, size))

        bid_depth, ask_depth, imbalance = self.compute_bid_ask_imbalance(
            bids, asks, current_price, depth_bps=depth_bps
        )

        depth = TickLiquidityDepth(
            pool_id=pool_id,
            protocol=DEXProtocol.ORCA_WHIRLPOOL,
            pair=pair,
            current_tick=current_tick,
            current_price=current_price,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            imbalance_ratio=imbalance,
            active_bin_count=len(whirlpool_ticks),
            timestamp_utc=float(pool_state.get("timestamp_utc", time.time())),
            raw_bins=whirlpool_ticks,
        )
        self._record_depth(depth)
        return depth

    def parse_meteora_dlmm(
        self,
        pool_id: str,
        pair: str,
        pool_state: Dict[str, Any],
        depth_bps: float = 50.0,
    ) -> TickLiquidityDepth:
        """Parses Meteora Dynamic Liquidity Market Maker (DLMM) bin arrays."""
        active_bin_id = int(pool_state.get("active_id", pool_state.get("current_tick", 0)))
        current_price = float(pool_state.get("current_price", self.tick_to_price(active_bin_id)))
        bins = pool_state.get("bins", [])

        bids: List[Tuple[float, float]] = []
        asks: List[Tuple[float, float]] = []

        for b in bins:
            bin_id = int(b.get("bin_id", 0))
            px = float(b.get("price", self.tick_to_price(bin_id)))
            x_usd = float(b.get("amount_x_usd", 0.0))
            y_usd = float(b.get("amount_y_usd", 0.0))
            total_bin_usd = x_usd + y_usd
            size = (total_bin_usd / px) if px > 0 else 0.0

            if px <= current_price:
                bids.append((px, size))
            else:
                asks.append((px, size))

        bid_depth, ask_depth, imbalance = self.compute_bid_ask_imbalance(
            bids, asks, current_price, depth_bps=depth_bps
        )

        depth = TickLiquidityDepth(
            pool_id=pool_id,
            protocol=DEXProtocol.METEORA_DLMM,
            pair=pair,
            current_tick=active_bin_id,
            current_price=current_price,
            bid_depth_usd=bid_depth,
            ask_depth_usd=ask_depth,
            imbalance_ratio=imbalance,
            active_bin_count=len(bins),
            timestamp_utc=float(pool_state.get("timestamp_utc", time.time())),
            raw_bins=bins,
        )
        self._record_depth(depth)
        return depth

    # =========================================================================
    # Anomaly & Manipulation Detection
    # =========================================================================

    def detect_anomalies(
        self,
        prev_depth: Optional[TickLiquidityDepth],
        curr_depth: TickLiquidityDepth,
        meteora_fee_volatility_bps: Optional[float] = None,
    ) -> List[MicrostructureAnomaly]:
        """
        Analyzes consecutive microstructure snapshots to detect:
        1. TICK_VACUUM (flash-loan drain or sudden liquidity pull)
        2. SPOOFED_WALL (extreme imbalance manipulation)
        3. FEE_VOLATILITY_SPIKE (Meteora dynamic fee volatility spikes)
        """
        anomalies: List[MicrostructureAnomaly] = []
        now = time.time()

        if prev_depth is not None:
            time_delta = max(0.001, curr_depth.timestamp_utc - prev_depth.timestamp_utc)
            prev_total_liq = prev_depth.bid_depth_usd + prev_depth.ask_depth_usd
            curr_total_liq = curr_depth.bid_depth_usd + curr_depth.ask_depth_usd

            # 1. TICK_VACUUM Detection:
            # Significant drop in 50-bps depth (>150k USD drop or >60% drop within 3 seconds)
            liq_drop = prev_total_liq - curr_total_liq
            drop_ratio = (liq_drop / prev_total_liq) if prev_total_liq > 0 else 0.0

            if time_delta <= 3.0 and (liq_drop >= 150_000 or (prev_total_liq > 50_000 and drop_ratio >= 0.60)):
                severity = "CRITICAL" if liq_drop >= 300_000 or drop_ratio >= 0.80 else "HIGH"
                conf = min(0.99, 0.70 + (drop_ratio * 0.25))
                anomalies.append(
                    MicrostructureAnomaly(
                        pool_id=curr_depth.pool_id,
                        protocol=curr_depth.protocol,
                        anomaly_type="TICK_VACUUM",
                        severity=severity,
                        confidence_score=conf,
                        evidence_details={
                            "previous_depth_usd": round(prev_total_liq, 2),
                            "current_depth_usd": round(curr_total_liq, 2),
                            "liquidity_dropped_usd": round(liq_drop, 2),
                            "drop_pct": round(drop_ratio * 100, 2),
                            "elapsed_seconds": round(time_delta, 3),
                        },
                        detected_at=now,
                    )
                )

        # 2. SPOOFED_WALL Detection:
        # Extreme bid or ask imbalance (> 0.85 or < -0.85) in concentrated bins
        if abs(curr_depth.imbalance_ratio) >= 0.85 and (curr_depth.bid_depth_usd + curr_depth.ask_depth_usd) >= 100_000:
            wall_side = "BID_SPOOF" if curr_depth.imbalance_ratio > 0 else "ASK_SPOOF"
            anomalies.append(
                MicrostructureAnomaly(
                    pool_id=curr_depth.pool_id,
                    protocol=curr_depth.protocol,
                    anomaly_type="SPOOFED_WALL",
                    severity="HIGH",
                    confidence_score=0.88,
                    evidence_details={
                        "imbalance_ratio": round(curr_depth.imbalance_ratio, 4),
                        "wall_side": wall_side,
                        "bid_depth_usd": round(curr_depth.bid_depth_usd, 2),
                        "ask_depth_usd": round(curr_depth.ask_depth_usd, 2),
                    },
                    detected_at=now,
                )
            )

        # 3. FEE_VOLATILITY_SPIKE Detection (Meteora DLMM specific):
        if (
            curr_depth.protocol == DEXProtocol.METEORA_DLMM
            and meteora_fee_volatility_bps is not None
            and meteora_fee_volatility_bps >= 250.0
        ):
            anomalies.append(
                MicrostructureAnomaly(
                    pool_id=curr_depth.pool_id,
                    protocol=curr_depth.protocol,
                    anomaly_type="FEE_VOLATILITY_SPIKE",
                    severity="MEDIUM" if meteora_fee_volatility_bps < 400.0 else "HIGH",
                    confidence_score=0.92,
                    evidence_details={
                        "fee_volatility_bps": round(meteora_fee_volatility_bps, 2),
                        "threshold_bps": 250.0,
                    },
                    detected_at=now,
                )
            )

        self._active_anomalies.extend(anomalies)
        if self.broadcaster and anomalies and self.broadcaster.active_connections_count > 0:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    for a in anomalies:
                        loop.create_task(self.broadcaster.broadcast_anomaly(a))
            except Exception:
                pass
        return anomalies

    # =========================================================================
    # Snapshot & Intel Signal Translation
    # =========================================================================

    def _record_depth(self, depth: TickLiquidityDepth) -> None:
        if depth.pool_id not in self._history:
            self._history[depth.pool_id] = []
        self._history[depth.pool_id].append(depth)
        # Keep last 100 snapshots per pool
        if len(self._history[depth.pool_id]) > 100:
            self._history[depth.pool_id].pop(0)

        if self.broadcaster and self.broadcaster.active_connections_count > 0:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.broadcaster.broadcast_tick_delta(depth))
            except Exception:
                pass

    def get_latest_depth(self, pool_id: str) -> Optional[TickLiquidityDepth]:
        snapshots = self._history.get(pool_id)
        return snapshots[-1] if snapshots else None

    def get_tracked_pools(self) -> List[str]:
        return list(self._history.keys())

    def get_active_anomalies(self, limit: int = 20) -> List[MicrostructureAnomaly]:
        return sorted(self._active_anomalies, key=lambda a: a.detected_at, reverse=True)[:limit]

    def convert_anomalies_to_intel_signals(
        self, anomalies: List[MicrostructureAnomaly]
    ) -> List[Dict[str, Any]]:
        """
        Translates raw microstructure anomalies into formatted Moltbook Alpha signals
        ready for insertion into SQLite 'intel_signals'.
        """
        signals = []
        for a in anomalies:
            headline = f"DEX Alert: {a.anomaly_type} detected on {a.protocol.value} pool {a.pool_id[:12]}"
            summary = (
                f"Microstructure anomaly {a.anomaly_type} observed (severity: {a.severity}, "
                f"confidence: {a.confidence_score:.2f}). Evidence: {a.evidence_details}"
            )
            signals.append({
                "category": "market_microstructure",
                "headline": headline,
                "summary": summary,
                "confidence": a.severity,
                "requires_human_review": 1 if a.severity == "CRITICAL" else 0,
                "automated_remedy_available": 1,
                "remedy_description": "Auto-adjust execution slippage bounds or pause taker entries on affected pool.",
            })
        return signals


class MicrostructureBroadcaster:
    """
    Real-time broadcaster for Solana DEX microstructure tick deltas and anomaly alerts.
    Supports concurrent WebSocket client subscriptions and HMAC-SHA256 signed webhooks.
    """

    def __init__(self) -> None:
        self._clients: Dict[Any, Set[str]] = {}

    @property
    def active_connections_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: Any) -> None:
        """Registers a new WebSocket connection."""
        self._clients[websocket] = set()

    def disconnect(self, websocket: Any) -> None:
        """Deregisters a WebSocket connection."""
        self._clients.pop(websocket, None)

    def set_subscriptions(self, websocket: Any, pools: List[str]) -> None:
        """Sets the pool filter for a connected client. Empty list means all pools."""
        if websocket in self._clients:
            self._clients[websocket] = set(pools)

    def get_subscriptions(self, websocket: Any) -> Set[str]:
        """Returns the pool filter for a connected client."""
        return self._clients.get(websocket, set())

    async def broadcast_tick_delta(self, depth: TickLiquidityDepth) -> int:
        """Broadcasts a tick liquidity depth update to subscribed clients."""
        payload = {
            "type": "TICK_DELTA",
            "data": depth.to_dict(),
            "timestamp": time.time(),
        }
        return await self._broadcast(payload, target_pool_id=depth.pool_id)

    async def broadcast_anomaly(self, anomaly: MicrostructureAnomaly) -> int:
        """Broadcasts a detected microstructure anomaly to subscribed clients."""
        payload = {
            "type": "ANOMALY_ALERT",
            "data": anomaly.to_dict(),
            "timestamp": time.time(),
        }
        return await self._broadcast(payload, target_pool_id=anomaly.pool_id)

    async def _broadcast(self, payload: Dict[str, Any], target_pool_id: Optional[str] = None) -> int:
        sent_count = 0
        dead = []
        for ws, pools in list(self._clients.items()):
            if pools and target_pool_id and target_pool_id not in pools:
                continue
            try:
                await ws.send_json(payload)
                sent_count += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
        return sent_count

    @staticmethod
    def sign_payload(secret_token: str, payload_bytes: bytes) -> str:
        """Generates standard HMAC-SHA256 signature header for webhook payload."""
        sig = hmac.new(secret_token.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        return f"sha256={sig}"

    async def dispatch_webhook(
        self,
        target_url: str,
        secret_token: str,
        event_type: str,
        data: Dict[str, Any],
        timeout_seconds: float = 5.0,
    ) -> Dict[str, Any]:
        """Dispatches an HTTP POST webhook signed with HMAC-SHA256."""
        import httpx

        envelope = {
            "event": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        payload_bytes = json.dumps(envelope).encode("utf-8")
        signature = self.sign_payload(secret_token, payload_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-Moltbook-Signature": signature,
            "User-Agent": "MoltbookAlpha-Webhook/1.0",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                res = await client.post(target_url, content=payload_bytes, headers=headers)
                return {
                    "success": 200 <= res.status_code < 300,
                    "status_code": res.status_code,
                    "signature": signature,
                    "error": None if res.is_success else f"HTTP {res.status_code}",
                }
        except Exception as exc:
            return {
                "success": False,
                "status_code": None,
                "signature": signature,
                "error": str(exc),
            }

    async def dispatch_to_matching_webhooks(
        self,
        storage: Any,
        event_type: str,
        data: Dict[str, Any],
        severity: str = "HIGH",
    ) -> List[Dict[str, Any]]:
        """
        Queries all active webhook subscriptions from storage, filters by event_type
        and min_severity, and dispatches the payload.
        """
        subs = storage.list_webhook_subscriptions(active_only=True)
        results = []
        severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        event_sev = severity_rank.get(severity.upper(), 3)

        for sub in subs:
            subscribed_events = sub.get("subscribed_events", [])
            min_sev = sub.get("min_severity", "HIGH").upper()
            min_rank = severity_rank.get(min_sev, 3)

            if "ALL" not in subscribed_events and event_type not in subscribed_events:
                continue

            if event_sev < min_rank:
                continue

            res = await self.dispatch_webhook(
                target_url=sub["target_url"],
                secret_token=sub["secret_token"],
                event_type=event_type,
                data=data,
            )
            res["subscription_id"] = sub["subscription_id"]
            results.append(res)
        return results


# Module-level broadcaster singleton
microstructure_broadcaster = MicrostructureBroadcaster()

