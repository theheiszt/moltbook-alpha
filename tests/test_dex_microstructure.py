"""
Tests for Pillar 1: Solana DEX Microstructure Engine, CLMM Math,
Manipulation Anomaly Detection, Intel Engine Ingestion, and API Endpoints.
"""

import time
from fastapi.testclient import TestClient

from ops.trading.dex_microstructure import (
    DEXMicrostructureEngine,
    DEXProtocol,
    TickLiquidityDepth,
    MicrostructureAnomaly,
)
from storage import StorageManager
from intel_engine import IntelEngine
from api_server import app


def test_clmm_math_tick_to_price_and_invert():
    engine = DEXMicrostructureEngine()

    # Tick 0 should yield 10^(9 - 6) = 1000 for standard 9/6 decimal token pair
    p0 = engine.tick_to_price(0, decimals_a=9, decimals_b=6)
    assert round(p0, 2) == 1000.0

    # Symmetric decimals (e.g. 6/6) at tick 0 should yield 1.0
    p_sym = engine.tick_to_price(0, decimals_a=6, decimals_b=6)
    assert round(p_sym, 4) == 1.0

    # Invert price back to tick
    tick = -15620
    price = engine.tick_to_price(tick, decimals_a=9, decimals_b=6)
    assert price > 0
    recovered_tick = engine.price_to_tick(price, decimals_a=9, decimals_b=6)
    assert abs(recovered_tick - tick) <= 1

    # Edge cases
    assert engine.tick_to_price(99999999) == 0.0  # Overflow caught
    assert engine.price_to_tick(-10.0) == 0
    assert engine.price_to_tick(0.0) == 0


def test_compute_bid_ask_imbalance():
    engine = DEXMicrostructureEngine()
    mid = 100.0

    # Perfectly balanced within 50 bps (99.50 to 100.50)
    bids = [(99.8, 10.0)]  # 998 USD
    asks = [(100.2, 9.96)] # 997.99 USD
    bid_d, ask_d, imb = engine.compute_bid_ask_imbalance(bids, asks, mid, depth_bps=50.0)
    assert round(bid_d, 1) == 998.0
    assert round(ask_d, 1) == 998.0
    assert abs(imb) < 0.01

    # Empty depth outside 50 bps radius
    bids_far = [(98.0, 10.0)]  # Outside 50 bps (200 bps away)
    asks_far = [(102.0, 10.0)]
    b_far, a_far, imb_far = engine.compute_bid_ask_imbalance(bids_far, asks_far, mid, depth_bps=50.0)
    assert b_far == 0.0
    assert a_far == 0.0
    assert imb_far == 0.0

    # Strong bid wall (spoof/skew)
    bids_heavy = [(99.9, 1000.0)] # 99,900 USD
    asks_light = [(100.1, 5.0)]   # 500.50 USD
    b_h, a_l, imb_heavy = engine.compute_bid_ask_imbalance(bids_heavy, asks_light, mid, depth_bps=50.0)
    assert imb_heavy > 0.90


def test_parse_raydium_clmm_pool():
    engine = DEXMicrostructureEngine()
    state = {
        "current_tick": -15620,
        "current_price": 101.50,
        "ticks": [
            {"tick": -15630, "price": 101.40, "liquidity_usd": 80000.0},
            {"tick": -15620, "price": 101.50, "liquidity_usd": 120000.0},
            {"tick": -15610, "price": 101.60, "liquidity_usd": 90000.0},
        ],
    }

    depth = engine.parse_raydium_clmm_pool("Raydium_SOL_USDC", "SOL/USDC", state)
    assert depth.pool_id == "Raydium_SOL_USDC"
    assert depth.protocol == DEXProtocol.RAYDIUM_CLMM
    assert depth.current_price == 101.50
    assert depth.active_bin_count == 3
    assert depth.bid_depth_usd > 0
    assert depth.ask_depth_usd > 0

    latest = engine.get_latest_depth("Raydium_SOL_USDC")
    assert latest is not None
    assert latest.pool_id == "Raydium_SOL_USDC"


def test_parse_orca_whirlpool():
    engine = DEXMicrostructureEngine()
    state = {
        "tick_current_index": -15620,
        "price": 101.52,
        "ticks": [
            {"index": -15625, "price": 101.47, "liquidity_net": 1500.0},
            {"index": -15620, "price": 101.52, "liquidity_net": 2000.0},
            {"index": -15615, "price": 101.57, "liquidity_net": -1500.0},
        ],
    }

    depth = engine.parse_orca_whirlpool("Orca_SOL_USDC", "SOL/USDC", state)
    assert depth.pool_id == "Orca_SOL_USDC"
    assert depth.protocol == DEXProtocol.ORCA_WHIRLPOOL
    assert depth.current_tick == -15620
    assert depth.active_bin_count == 3


def test_parse_meteora_dlmm():
    engine = DEXMicrostructureEngine()
    state = {
        "active_id": -15620,
        "current_price": 101.48,
        "bins": [
            {"bin_id": -15625, "price": 101.43, "amount_x_usd": 50000.0, "amount_y_usd": 55000.0},
            {"bin_id": -15620, "price": 101.48, "amount_x_usd": 70000.0, "amount_y_usd": 75000.0},
            {"bin_id": -15615, "price": 101.53, "amount_x_usd": 60000.0, "amount_y_usd": 65000.0},
        ],
    }

    depth = engine.parse_meteora_dlmm("Meteora_SOL_USDC", "SOL/USDC", state)
    assert depth.pool_id == "Meteora_SOL_USDC"
    assert depth.protocol == DEXProtocol.METEORA_DLMM
    assert depth.active_bin_count == 3
    assert depth.bid_depth_usd > 0


def test_detect_tick_vacuum_anomaly():
    engine = DEXMicrostructureEngine()
    t0 = time.time()

    prev_depth = TickLiquidityDepth(
        pool_id="Raydium_SOL_USDC",
        protocol=DEXProtocol.RAYDIUM_CLMM,
        pair="SOL/USDC",
        current_tick=-15620,
        current_price=101.50,
        bid_depth_usd=200_000.0,
        ask_depth_usd=200_000.0,
        imbalance_ratio=0.0,
        active_bin_count=10,
        timestamp_utc=t0,
    )

    # 1.5 seconds later, depth collapses from 400k to 100k (drop of 300k, 75%)
    curr_depth = TickLiquidityDepth(
        pool_id="Raydium_SOL_USDC",
        protocol=DEXProtocol.RAYDIUM_CLMM,
        pair="SOL/USDC",
        current_tick=-15620,
        current_price=101.45,
        bid_depth_usd=50_000.0,
        ask_depth_usd=50_000.0,
        imbalance_ratio=0.0,
        active_bin_count=10,
        timestamp_utc=t0 + 1.5,
    )

    anomalies = engine.detect_anomalies(prev_depth, curr_depth)
    assert len(anomalies) >= 1
    vacuum = next(a for a in anomalies if a.anomaly_type == "TICK_VACUUM")
    assert vacuum.severity == "CRITICAL"
    assert vacuum.evidence_details["liquidity_dropped_usd"] == 300_000.0
    assert vacuum.confidence_score >= 0.85


def test_detect_spoofed_wall_anomaly():
    engine = DEXMicrostructureEngine()
    curr_depth = TickLiquidityDepth(
        pool_id="Orca_SOL_USDC",
        protocol=DEXProtocol.ORCA_WHIRLPOOL,
        pair="SOL/USDC",
        current_tick=-15620,
        current_price=101.50,
        bid_depth_usd=150_000.0,
        ask_depth_usd=5_000.0,
        imbalance_ratio=0.935,
        active_bin_count=5,
        timestamp_utc=time.time(),
    )

    anomalies = engine.detect_anomalies(None, curr_depth)
    assert len(anomalies) == 1
    spoof = anomalies[0]
    assert spoof.anomaly_type == "SPOOFED_WALL"
    assert spoof.evidence_details["wall_side"] == "BID_SPOOF"
    assert spoof.evidence_details["imbalance_ratio"] == 0.935


def test_detect_fee_volatility_spike_meteora():
    engine = DEXMicrostructureEngine()
    curr_depth = TickLiquidityDepth(
        pool_id="Meteora_SOL_USDC",
        protocol=DEXProtocol.METEORA_DLMM,
        pair="SOL/USDC",
        current_tick=-15620,
        current_price=101.50,
        bid_depth_usd=50_000.0,
        ask_depth_usd=50_000.0,
        imbalance_ratio=0.0,
        active_bin_count=5,
        timestamp_utc=time.time(),
    )

    anomalies = engine.detect_anomalies(None, curr_depth, meteora_fee_volatility_bps=320.0)
    assert len(anomalies) == 1
    fee_spike = anomalies[0]
    assert fee_spike.anomaly_type == "FEE_VOLATILITY_SPIKE"
    assert fee_spike.evidence_details["fee_volatility_bps"] == 320.0


def test_intel_engine_ingest_microstructure_anomalies(tmp_path):
    db_file = tmp_path / "test_micro_intel.db"
    storage = StorageManager(db_file)
    intel = IntelEngine(storage)

    anomaly = MicrostructureAnomaly(
        pool_id="Raydium_SOL_USDC",
        protocol=DEXProtocol.RAYDIUM_CLMM,
        anomaly_type="TICK_VACUUM",
        severity="CRITICAL",
        confidence_score=0.95,
        evidence_details={"dropped_usd": 250000.0},
        detected_at=time.time(),
    )

    count = intel.ingest_microstructure_anomalies([anomaly])
    assert count == 1

    # Idempotent deduplication test: ingesting same anomaly produces 0 duplicates
    dupe_count = intel.ingest_microstructure_anomalies([anomaly])
    assert dupe_count == 0

    # Verify indexed signals
    signals = intel.search_signals(category="market_microstructure")
    assert len(signals) == 1
    sig = signals[0]
    assert sig["category"] == "market_microstructure"
    assert "TICK_VACUUM" in sig["headline"]
    assert sig["requires_human_review"] is True  # CRITICAL severity requires human review
    assert sig["automated_remedy_available"] is True


def test_api_microstructure_fleet_endpoint():
    client = TestClient(app)
    res = client.get("/v1/intel/microstructure")
    assert res.status_code == 200
    data = res.json()
    assert data["tracked_pool_count"] >= 3
    assert "Raydium_SOL_USDC" in [p["pool_id"] for p in data["pools"]]
    assert "Orca_SOL_USDC" in [p["pool_id"] for p in data["pools"]]
    assert "Meteora_SOL_USDC" in [p["pool_id"] for p in data["pools"]]
    assert "state_witness_id" in data


def test_api_microstructure_pool_detail_and_witness():
    client = TestClient(app)
    res = client.get("/v1/intel/microstructure/Raydium_SOL_USDC")
    assert res.status_code == 200
    data = res.json()
    assert data["pool_id"] == "Raydium_SOL_USDC"
    assert data["protocol"] == "raydium_clmm"
    assert data["current_price"] > 0
    assert len(data["raw_bins"]) > 0

    # Cryptographic state witness validation
    witness = data.get("state_witness")
    assert witness is not None
    assert witness["action"] == "POOL_MICROSTRUCTURE_OBSERVED"
    assert "signature" in witness

    # Verify signature against public verification endpoint
    v_res = client.post("/v1/witnesses/verify", json={"witness": witness})
    assert v_res.status_code == 200
    v_data = v_res.json()
    assert v_data["valid"] is True
    assert v_data["signature_valid"] is True


def test_api_microstructure_pool_not_found():
    client = TestClient(app)
    res = client.get("/v1/intel/microstructure/non_existent_pool_999")
    assert res.status_code == 404
    err_data = res.json()
    assert "detail" in err_data
    assert "non_existent_pool_999" in err_data["detail"]
