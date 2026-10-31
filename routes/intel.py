"""
Moltbook Alpha — Market Intelligence, Quant Analysis, and Briefing Routes.
"""

import hashlib
import json as _json
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

from app_state import (
    MeteredCall,
    metered,
    get_client_ip,
    intel_engine,
    dex_microstructure,
    witness_manager,
    storage,
    rate_limiter,
    record_rate_limit,
)
from config import REPORTS_DIR
from routes.schemas import (
    BriefingLatestResponse,
    IntelMicrostructureOverviewResponse,
    IntelOpportunitiesResponse,
    IntelPoolMicrostructureResponse,
    IntelSignalsResponse,
    IntelTradingSignalsResponse,
    QuantFirstPassageResponse,
    QuantTradeViabilityResponse,
)

router = APIRouter(tags=["Intelligence & Quant"])


def create_intel_router() -> APIRouter:
    return router


class QuantTradeViabilityInput(BaseModel):
    pair: str = "BONK/SOL"
    target_net_pct: float = 0.015
    stop_loss_pct: float = 0.020
    roundtrip_spread_bps: float = 8.0
    hourly_volatility: Optional[float] = None
    hourly_drift: float = 0.0
    horizons_hours: Optional[List[int]] = None


_QUANT_FP_CACHE: Dict[str, Any] = {}
_QUANT_FP_TTL_SECONDS = 45.0


def get_sample_briefing_payload() -> Dict[str, Any]:
    """
    Returns a realistic, schema-valid synthetic briefing for unmetered evaluation.
    """
    sample_content = (
        "# Moltbook Alpha Intelligence Briefing [SAMPLE EVALUATION]\n\n"
        "## Executive Summary\n"
        "Synthesized market telemetry across Solana concentrated liquidity pools, "
        "Moltbook autonomous agent discussions, and protocol security advisories.\n\n"
        "## Critical Signals\n"
        "- **Orca Whirlpool SOL-USDC**: Tick vacuum detected at -25 bps tick boundary; skew indicates institutional bid support.\n"
        "- **Agent Ecosystem**: Autonomous agent challenge verification throughput up 42% over last 6 hours.\n\n"
        "## Provenance Witness\n"
        "State witness ID: `wit_sample_e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`\n"
        "Signature verified against Atlas Provenance Guard.\n"
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "success": True,
        "sample": True,
        "mode": "evaluation_unmetered",
        "generated_at": now_iso,
        "credits_remaining": "unmetered",
        "briefing_markdown": sample_content,
        "signals": [
            {
                "signal_id": "sig_sample_001",
                "category": "dex_microstructure",
                "confidence": "HIGH",
                "title": "Orca Whirlpool SOL-USDC Tick Vacuum Detected",
                "summary": "Sub-tick volume divergence identified at lower tick boundary indicating upward volatility squeeze.",
                "sources": [
                    {
                        "source_name": "Orca Whirlpool",
                        "source_type": "dex_clmm",
                        "pool_id": "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm",
                        "verified": True,
                    }
                ],
                "observed_at": now_iso,
            },
            {
                "signal_id": "sig_sample_002",
                "category": "security_advisory",
                "confidence": "HIGH",
                "title": "Moltbook Protocol Agent Identity Verification Standard",
                "summary": "Cryptographic Ed25519 witness state validation mandated for autonomous trading bot telemetry pipelines.",
                "sources": [
                    {
                        "source_name": "Moltbook Protocol",
                        "source_type": "social_graph",
                        "post_id": "e2ae1289-a20b-4bd4-ba46-1af0fd1fc6cc",
                        "verified": True,
                    }
                ],
                "observed_at": now_iso,
            },
        ],
        "trading_signals": [
            {
                "signal_id": "sig_sample_sol_001",
                "asset": "SOL",
                "pair": "SOL/USDC",
                "action": "BUY_ACCUMULATE",
                "confidence_score": 0.88,
                "confidence_tier": "HIGH",
                "risk_rating": "LOW",
                "entry_price": 182.15,
                "price_targets": [186.70, 193.99],
                "stop_loss": 178.87,
                "risk_reward_ratio": 2.36,
                "timeframe": "1h",
                "catalyst_type": "orderflow_imbalance",
                "headline": "Institutional Bid Skew & Orderbook Imbalance on SOL-USDC",
                "rationale": "Concentrated liquidity orderbooks show heavy bid imbalance (+10.6%) with over $2.4M bid depth inside the 50 bps band.",
                "execution_params": {
                    "recommended_venue": "Raydium CLMM",
                    "route_type": "CLMM_DIRECT",
                    "max_slippage_bps": 25,
                    "min_liquidity_depth_usd": 100000.0,
                },
                "created_at": now_iso,
            }
        ],
        "opportunities": [
            {
                "opportunity_id": "opp_sample_arb_sol_usdc",
                "opportunity_type": "cross_dex_arbitrage",
                "pair": "SOL/USDC",
                "buy_venue": "Raydium CLMM",
                "buy_pool_id": "2QdhepnKRTLjjSqPL1PtKNwqrUkoLee5Gqs8bvZhRdMv",
                "buy_price": 182.15,
                "sell_venue": "Orca Whirlpool",
                "sell_pool_id": "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm",
                "sell_price": 182.80,
                "gross_spread_bps": 35.68,
                "net_profit_pct": 0.28,
                "estimated_capacity_usd": 75000.0,
                "urgency": "HIGH",
                "estimated_decay_seconds": 15,
                "detected_at": time.time(),
            }
        ],
        "microstructure_summary": {
            "tracked_pools": 5,
            "anomalies_detected": 1,
            "aggregate_depth_usd_50bps": 14250000.0,
        },
        "state_witness": {
            "action": "SAMPLE_EVALUATION",
            "witness_id": "wit_sample_e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "canonical_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "verified": True,
        },
        "documentation_url": "https://theheiszt.github.io/moltbook-alpha",
    }


@router.get("/v1/briefing/latest", response_model=BriefingLatestResponse)
def get_latest_briefing(request: Request, x_api_key: Optional[str] = Header(None)):
    with MeteredCall(request, "/v1/briefing/latest", ip_bucket="briefing") as call:
        res_info = call.reservation
        latest_path = REPORTS_DIR / "latest_briefing.md"
        if not latest_path.exists():
            raise HTTPException(status_code=404, detail="No briefing generated yet.")

        with open(latest_path, "r", encoding="utf-8") as f:
            content = f.read()

        witness_id = None
        if res_info.get("key_hash"):
            try:
                w = witness_manager.create_witness(
                    action="QUERY_DEDUCTED",
                    actor=res_info.get("key_prefix", "unknown"),
                    key_hash=res_info.get("key_hash"),
                    lot_id=res_info.get("lot_id"),
                    pre_balance=(res_info.get("credits") or 0) + 1,
                    credit_delta=-1,
                    post_balance=res_info.get("credits"),
                    request_id=call.request_id,
                )
                witness_id = w["witness_id"]
            except Exception:
                pass

        # Synthesize real-time quantitative trading signals & cross-DEX arbitrage
        trading_signals = intel_engine.generate_trading_signals(
            limit=5,
            dex_microstructure=dex_microstructure,
            witness_manager=witness_manager,
        )
        live_opportunities = intel_engine.get_live_opportunities(
            dex_microstructure=dex_microstructure,
            min_profit_pct=0.05,
            limit=5,
            witness_manager=witness_manager,
        )

        res = {
            "success": True,
            "user_tier": res_info.get("tier"),
            "credits_remaining": res_info.get("credits"),
            "briefing_markdown": content,
            "trading_signals": trading_signals,
            "opportunities": live_opportunities,
        }
        if witness_id:
            res["state_witness_id"] = witness_id

        return call.settle(res)


@router.get("/v1/sample")
def get_sample_alias(request: Request):
    """
    [UNMETERED - 0 CREDITS] Convenience alias for /v1/intel/sample.
    """
    return get_intel_sample(request)


@router.get("/v1/intel/sample")
def get_intel_sample(request: Request):
    """
    Returns an unmetered, realistic sample briefing payload for evaluation and schema validation.
    No API key or payment required.
    Emits a privacy-preserving 'sample_viewed' conversion funnel event.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"sample:{client_ip}", limit=60, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/intel/sample")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    storage.record_funnel_event(
        "sample_viewed",
        {"endpoint": "/v1/intel/sample", "user_agent": (request.headers.get("user-agent") or "unknown")[:64]}
    )

    return get_sample_briefing_payload()


@router.get("/v1/intel/latest")
def get_intel_latest(request: Request, x_api_key: Optional[str] = Header(None)):
    """
    Returns the latest synthesized market intelligence briefing,
    including actionable signals, verified sources, and cryptographic state witness ID.
    Enforces atomic credit deduction via API key or Bearer token.
    """
    return get_latest_briefing(request, x_api_key=x_api_key)


@router.get("/v1/intel/signals", response_model=IntelSignalsResponse)
@metered("/v1/intel/signals")
def get_intel_signals(
    request: Request,
    category: Optional[str] = None,
    confidence: Optional[str] = None,
    limit: int = 25,
):
    """
    Queries indexed intelligence signals across security advisories, API changes,
    operational failures, architecture patterns, and market alpha.
    """
    signals = intel_engine.search_signals(
        category=category,
        confidence=confidence,
        limit=min(limit, 100),
    )
    return {
        "count": len(signals),
        "signals": signals,
    }


@router.get("/v1/intel/opportunities", response_model=IntelOpportunitiesResponse)
@metered("/v1/intel/opportunities")
def get_intel_opportunities(
    request: Request,
    min_profit_pct: float = 0.05,
    pair: Optional[str] = None,
    opp_type: Optional[str] = None,
    limit: int = 25,
):
    """
    Scans real-time cross-DEX arbitrage opportunities, liquidity gaps,
    and tick vacuum squeeze alerts across tracked Solana liquidity pools (Orca, Raydium, Meteora).
    Calculates net profitability after pool fee tiers and execution gas costs.
    """
    opps = intel_engine.get_live_opportunities(
        dex_microstructure=dex_microstructure,
        min_profit_pct=min_profit_pct,
        pair=pair,
        opp_type=opp_type,
        limit=min(limit, 100),
        witness_manager=witness_manager,
    )
    return {
        "count": len(opps),
        "min_profit_pct": min_profit_pct,
        "opportunities": opps,
        "timestamp_utc": time.time(),
    }


@router.get("/v1/intel/signals/trading", response_model=IntelTradingSignalsResponse)
@metered("/v1/intel/signals/trading")
def get_intel_trading_signals(
    request: Request,
    asset: Optional[str] = None,
    action: Optional[str] = None,
    min_confidence: float = 0.5,
    limit: int = 25,
):
    """
    Returns synthesized machine-readable trading directives with entry price,
    targets, stop loss, risk rating, execution venue, and Ed25519 cryptographic witness.
    """
    signals = intel_engine.generate_trading_signals(
        limit=min(limit, 100),
        asset=asset,
        action=action,
        min_confidence=min_confidence,
        dex_microstructure=dex_microstructure,
        witness_manager=witness_manager,
    )
    return {
        "count": len(signals),
        "min_confidence": min_confidence,
        "trading_signals": signals,
        "timestamp_utc": time.time(),
    }


@router.get("/v1/intel/demand")
def get_intel_service_demand_leaderboard(
    request: Request,
    limit: int = 20,
):
    """
    [UNMETERED - 0 CREDITS] Synthesizes community posts across Moltbook submolts
    into a ranked Agent Service Demand Leaderboard, mapping top agent pain points
    and RFPs directly to Moltbook Alpha API endpoints and open bounties.
    """
    return intel_engine.get_service_demand_leaderboard(limit=min(limit, 50))


@router.get("/v1/intel/observatory/status")
def get_intel_observatory_status(request: Request):
    """
    [UNMETERED - 0 CREDITS] Returns sync status, checkpoints, and ingestion telemetry
    for the decoupled Moltbook Observatory intelligence source adapter.
    """
    from ops.observatory_adapter import ObservatorySourceAdapter
    adapter = ObservatorySourceAdapter(storage_manager=storage)
    return adapter.get_status()


@router.get("/v1/intel/observatory/trends")
def get_intel_observatory_trends(
    request: Request,
    hours: int = 24,
    limit: int = 50,
    category: Optional[str] = None,
):
    """
    [UNMETERED - 0 CREDITS] Retrieves ingested Moltbook Observatory macro keyword trends
    and velocity anomaly signals, classified by security, alpha, ops, and architecture.
    """
    from ops.observatory_adapter import ObservatorySourceAdapter
    adapter = ObservatorySourceAdapter(storage_manager=storage)
    return adapter.get_recent_trends(hours=hours, limit=limit, category=category)


@router.get("/v1/quant/first-passage", response_model=QuantFirstPassageResponse)
def get_quant_first_passage(
    request: Request,
    pair: str = "BONK/SOL",
    target_net_pct: float = 0.015,
    stop_loss_pct: float = 0.020,
    roundtrip_spread_bps: float = 8.0,
    hourly_volatility: Optional[float] = None,
    hourly_drift: float = 0.0,
    refresh: bool = False,
):
    """
    Computes analytical Brownian reflection and drift-adjusted inverse Gaussian
    first-passage probabilities across multiple time horizons (4h, 8h, 12h, 24h, 48h, 72h),
    two-barrier win odds (take-profit before stop-loss), Kelly sizing, and an optimal
    target velocity ladder, bound to an Ed25519 cryptographic state witness.
    Includes a 45-second TTL cache (?refresh=true to bypass).
    """
    if target_net_pct <= 0 or target_net_pct > 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_net_pct must be between 0.0001 and 1.0 (e.g. 0.015 for +1.5%).",
        )
    if stop_loss_pct <= 0 or stop_loss_pct >= 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stop_loss_pct must be between 0.0001 and 0.9999 (e.g. 0.020 for -2.0%).",
        )

    cache_key = f"{pair.upper().strip()}|{target_net_pct:.5f}|{stop_loss_pct:.5f}|{roundtrip_spread_bps:.2f}|{hourly_volatility}|{hourly_drift:.5f}"
    now_ts = time.time()
    cached = _QUANT_FP_CACHE.get(cache_key)
    if cached and not refresh and (now_ts - cached["ts"]) < _QUANT_FP_TTL_SECONDS:
        out = dict(cached["profile"])
        out["cache_status"] = "HIT"
        out["cache_age_seconds"] = round(now_ts - cached["ts"], 2)
        return out

    from ops.trading.quant_trader import QuantTradingEngine

    q_engine = QuantTradingEngine()
    profile = q_engine.evaluate_trade_probability_profile(
        pair=pair,
        target_net_pct=target_net_pct,
        stop_loss_pct=stop_loss_pct,
        roundtrip_spread_bps=roundtrip_spread_bps,
        hourly_volatility=hourly_volatility,
        hourly_drift=hourly_drift,
    )

    w = witness_manager.create_witness(
        action="QUANT_FIRST_PASSAGE_EVALUATED",
        actor=profile["pair"],
        key_hash="public_quant_query",
        request_id=getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(6)}",
        environmental_anchor={
            "pair": profile["pair"],
            "target_net_pct": target_net_pct,
            "stop_loss_pct": stop_loss_pct,
            "recommended_target_net_pct": profile["recommended_target_net_pct"],
        },
    )
    profile["state_witness_id"] = w.get("witness_id")
    profile["witness_signature"] = w.get("signature")
    profile["generated_at"] = datetime.now(timezone.utc).isoformat()
    profile["cache_status"] = "MISS"
    profile["cache_age_seconds"] = 0.0
    _QUANT_FP_CACHE[cache_key] = {"ts": now_ts, "profile": profile}
    return profile


@router.post("/v1/quant/trade-viability", response_model=QuantTradeViabilityResponse)
@metered("/v1/quant/trade-viability")
def post_quant_trade_viability(
    payload: QuantTradeViabilityInput,
    request: Request,
):
    """
    Evaluates custom quantitative trade viability, round-trip spread drag, two-barrier
    win odds, and multi-horizon first-passage probabilities with an Ed25519 state witness.
    """
    if payload.target_net_pct <= 0 or payload.target_net_pct > 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_net_pct must be between 0.0001 and 1.0.",
        )
    if payload.stop_loss_pct <= 0 or payload.stop_loss_pct >= 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stop_loss_pct must be between 0.0001 and 0.9999.",
        )

    from ops.trading.quant_trader import QuantTradingEngine

    q_engine = QuantTradingEngine()
    profile = q_engine.evaluate_trade_probability_profile(
        pair=payload.pair,
        target_net_pct=payload.target_net_pct,
        stop_loss_pct=payload.stop_loss_pct,
        roundtrip_spread_bps=payload.roundtrip_spread_bps,
        hourly_volatility=payload.hourly_volatility,
        hourly_drift=payload.hourly_drift,
        horizons_hours=payload.horizons_hours,
    )

    w = witness_manager.create_witness(
        action="QUANT_TRADE_VIABILITY_EVALUATED",
        actor=profile["pair"],
        key_hash="public_quant_query",
        request_id=getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(6)}",
        environmental_anchor={
            "pair": profile["pair"],
            "target_net_pct": payload.target_net_pct,
            "stop_loss_pct": payload.stop_loss_pct,
            "recommended_target_net_pct": profile["recommended_target_net_pct"],
        },
    )
    profile["state_witness_id"] = w.get("witness_id")
    profile["witness_signature"] = w.get("signature")
    profile["generated_at"] = datetime.now(timezone.utc).isoformat()
    return profile


@router.get("/v1/newsletter/latest")
def get_latest_daily_newsletter():
    """
    Returns the latest automated Daily Intelligence & Quant Newsletter (JSON + Markdown)
    combining verified submolt radar, first-passage probability matrices, and Molt Alpha DEMS NFT supply.
    """
    news_json_path = REPORTS_DIR / "latest_newsletter.json"
    if news_json_path.is_file():
        try:
            return _json.loads(news_json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    from ops.publisher import publish_daily_alpha

    publish_daily_alpha(dry_run=True, force_refresh=False, storage_manager=storage, witness_manager=witness_manager)
    if news_json_path.is_file():
        return _json.loads(news_json_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=500, detail="Failed to synthesize daily newsletter.")


@router.get("/v1/intel/microstructure", response_model=IntelMicrostructureOverviewResponse)
@metered("/v1/intel/microstructure")
def get_intel_microstructure(
    request: Request,
    depth_bps: float = 50.0,
):
    """
    Returns fleet-wide DEX microstructure intelligence, active orderbook depth,
    and detected manipulation anomalies (tick vacuums, spoofed walls, fee volatility spikes)
    across tracked Solana concentrated liquidity pools.
    """
    tracked_pools = dex_microstructure.get_tracked_pools()
    pool_summaries = []
    for pid in tracked_pools:
        depth = dex_microstructure.get_latest_depth(pid)
        if depth:
            pool_summaries.append(depth.to_dict())

    anomalies = dex_microstructure.get_active_anomalies(limit=25)
    anomalies_data = [a.to_dict() for a in anomalies]

    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    witness_id = None
    if witness_manager:
        try:
            w = witness_manager.create_witness(
                action="MICROSTRUCTURE_FLEET_QUERY",
                actor="intel_engine_v1",
                key_hash=hashlib.sha256(f"fleet_{len(tracked_pools)}".encode()).hexdigest(),
                request_id=req_id,
                environmental_anchor={
                    "tracked_count": len(tracked_pools),
                    "anomalies_count": len(anomalies),
                    "depth_bps": depth_bps,
                },
            )
            witness_id = w.get("witness_id")
        except Exception:
            pass

    return {
        "status": "anomalies_detected" if anomalies else "healthy",
        "tracked_pool_count": len(tracked_pools),
        "active_anomaly_count": len(anomalies),
        "depth_bps": depth_bps,
        "pools": pool_summaries,
        "recent_anomalies": anomalies_data,
        "state_witness_id": witness_id,
        "timestamp_utc": time.time(),
    }


@router.get("/v1/intel/microstructure/{pool_id}", response_model=IntelPoolMicrostructureResponse)
@metered("/v1/intel/microstructure/{pool_id}")
def get_pool_microstructure(
    pool_id: str,
    request: Request,
    depth_bps: float = 50.0,
):
    """
    Returns deep orderbook liquidity distribution, tick arrays, bid/ask depth,
    imbalance ratio, and anomaly telemetry for a specific concentrated liquidity pool.
    Binds the observation to a verifiable cryptographic state witness.
    """
    depth = dex_microstructure.get_latest_depth(pool_id)
    if not depth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DEX pool '{pool_id}' is not tracked by the microstructure engine. Tracked: {dex_microstructure.get_tracked_pools()}",
        )

    pool_anomalies = [
        a.to_dict()
        for a in dex_microstructure.get_active_anomalies(limit=50)
        if a.pool_id == pool_id
    ]

    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
    witness_record = None
    if witness_manager:
        try:
            witness_record = witness_manager.create_witness(
                action="POOL_MICROSTRUCTURE_OBSERVED",
                actor="dex_microstructure_engine",
                key_hash=hashlib.sha256(pool_id.encode()).hexdigest(),
                request_id=req_id,
                environmental_anchor={
                    "pool_id": pool_id,
                    "protocol": depth.protocol.value,
                    "current_price": depth.current_price,
                    "imbalance_ratio": depth.imbalance_ratio,
                    "bid_depth_usd": depth.bid_depth_usd,
                    "ask_depth_usd": depth.ask_depth_usd,
                },
            )
        except Exception:
            pass

    res = depth.to_dict()
    res["raw_bins"] = depth.raw_bins
    res["anomalies"] = pool_anomalies
    res["state_witness"] = witness_record
    return res


@router.post("/v1/intel/refresh")
@metered("/v1/intel/refresh")
def refresh_intelligence(request: Request):
    """
    Triggers an immediate collection and synthesis cycle across all approved sources.
    """
    stats = intel_engine.collect_all_sources(dex_microstructure=dex_microstructure)
    signals_count = intel_engine.extract_signals(limit_items=100)
    briefing = intel_engine.generate_briefing(witness_manager=witness_manager)
    return {
        "status": "success",
        "sources_collected": stats,
        "signals_extracted": signals_count,
        "briefing_id": briefing["briefing_id"],
        "state_witness_id": briefing["state_witness_id"],
    }
