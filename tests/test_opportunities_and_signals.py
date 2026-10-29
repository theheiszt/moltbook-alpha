"""
Tests for Structured Trading Alpha, Cross-DEX Arbitrage Scanner, and Signal Generation.
Covers:
- DEX Microstructure cross-pool arbitrage and tick vacuum squeeze scanning
- Machine-readable trading alpha synthesis and risk-reward calculation
- HTTP API Endpoints: GET /v1/intel/opportunities, GET /v1/intel/signals/trading
- DAG tool parameter registration for autonomous agent discovery
- Client SDK integration
"""

import time
import pytest
from fastapi.testclient import TestClient

from ops.trading.dex_microstructure import (
    DEXMicrostructureEngine,
    DEXProtocol,
    MicrostructureAnomaly,
)
from intel_engine import IntelEngine
from storage import StorageManager
from cryptographic_witness import WitnessManager
from api_server import app
from dag_tool_parameters import TOOL_DAG_REGISTRY


@pytest.fixture
def test_storage(tmp_path):
    db_path = tmp_path / "test_intel_signals.db"
    return StorageManager(db_path=db_path)


@pytest.fixture
def witness_manager(test_storage):
    return WitnessManager(test_storage)


@pytest.fixture
def dex_engine():
    engine = DEXMicrostructureEngine()
    engine.seed_default_pools(base_sol_price=182.50)
    return engine


def test_dex_microstructure_arbitrage_scanning(dex_engine):
    # Scan opportunities with standard threshold
    opps = dex_engine.scan_arbitrage_opportunities(min_profit_pct=0.05, limit=10)
    assert len(opps) > 0

    sol_opp = next((o for o in opps if o.pair == "SOL/USDC"), None)
    assert sol_opp is not None
    assert sol_opp.buy_price > 0
    assert sol_opp.sell_price > sol_opp.buy_price
    assert sol_opp.gross_spread_bps > 0
    assert sol_opp.net_profit_pct > 0.05
    assert sol_opp.urgency in ["IMMEDIATE", "HIGH", "MEDIUM", "LOW"]
    assert sol_opp.estimated_capacity_usd > 0
    assert "total_swap_fees_bps" in sol_opp.evidence_details

    # Test filtering by higher min_profit_pct
    high_opps = dex_engine.scan_arbitrage_opportunities(min_profit_pct=5.0)
    assert len(high_opps) == 0


def test_dex_microstructure_tick_vacuum_squeeze(dex_engine):
    # Inject a tick vacuum anomaly
    pool_id = "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm"
    anomaly = MicrostructureAnomaly(
        pool_id=pool_id,
        protocol=DEXProtocol.ORCA_WHIRLPOOL,
        anomaly_type="TICK_VACUUM",
        severity="CRITICAL",
        confidence_score=0.95,
        evidence_details={"drop_pct": 75.0, "liquidity_dropped_usd": 250000.0},
        detected_at=time.time(),
    )
    dex_engine._active_anomalies.append(anomaly)

    opps = dex_engine.scan_arbitrage_opportunities(limit=10)
    squeeze = next((o for o in opps if o.opportunity_type == "tick_vacuum_squeeze"), None)
    assert squeeze is not None
    assert squeeze.urgency == "IMMEDIATE"
    assert squeeze.net_profit_pct > 0


def test_intel_engine_generate_trading_signals(test_storage, dex_engine, witness_manager):
    intel = IntelEngine(storage_manager=test_storage)

    signals = intel.generate_trading_signals(
        limit=10,
        min_confidence=0.5,
        dex_microstructure=dex_engine,
        witness_manager=witness_manager,
    )

    assert len(signals) >= 3

    for sig in signals:
        assert "signal_id" in sig
        assert sig["asset"] in ["SOL", "JUP", "RAY", "BONK"]
        assert "pair" in sig
        assert sig["action"] in ["BUY_ACCUMULATE", "SCALPER_LONG", "MONITOR", "SCALPER_SHORT"]
        assert 0.0 <= sig["confidence_score"] <= 1.0
        assert sig["confidence_tier"] in ["HIGH", "MEDIUM", "LOW"]
        assert sig["risk_rating"] in ["LOW", "MEDIUM", "HIGH"]
        assert sig["entry_price"] > 0
        assert len(sig["price_targets"]) >= 1
        assert sig["stop_loss"] > 0
        assert sig["risk_reward_ratio"] > 0
        assert "timeframe" in sig
        assert "headline" in sig
        assert "rationale" in sig
        assert "execution_params" in sig
        assert "recommended_venue" in sig["execution_params"]
        assert "state_witness_id" in sig
        assert sig["state_witness_id"].startswith("wit_")

    # Filter tests
    sol_signals = intel.generate_trading_signals(asset="SOL", dex_microstructure=dex_engine)
    assert all(s["asset"] == "SOL" for s in sol_signals)

    buy_signals = intel.generate_trading_signals(action="BUY_ACCUMULATE", dex_microstructure=dex_engine)
    assert all(s["action"] == "BUY_ACCUMULATE" for s in buy_signals)


def test_intel_engine_get_live_opportunities(test_storage, dex_engine, witness_manager):
    intel = IntelEngine(storage_manager=test_storage)

    opps = intel.get_live_opportunities(
        dex_microstructure=dex_engine,
        min_profit_pct=0.05,
        limit=10,
        witness_manager=witness_manager,
    )

    assert len(opps) > 0
    first = opps[0]
    assert "opportunity_id" in first
    assert "pair" in first
    assert "buy_venue" in first
    assert "sell_venue" in first
    assert "buy_price" in first
    assert "sell_price" in first
    assert "net_profit_pct" in first
    assert "state_witness_id" in first
    assert first["state_witness_id"].startswith("wit_")


def test_http_api_intel_opportunities():
    client = TestClient(app)

    # 1. Fetch opportunities without filters
    res = client.get("/v1/intel/opportunities")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert "opportunities" in data
    assert data["count"] > 0

    opp = data["opportunities"][0]
    assert "opportunity_id" in opp
    assert "pair" in opp
    assert "buy_venue" in opp
    assert "sell_venue" in opp
    assert opp["net_profit_pct"] >= 0.05

    # 2. Filter by pair
    res_pair = client.get("/v1/intel/opportunities?pair=SOL/USDC")
    assert res_pair.status_code == 200
    pair_data = res_pair.json()
    assert all(o["pair"] == "SOL/USDC" for o in pair_data["opportunities"])


def test_http_api_intel_trading_signals():
    client = TestClient(app)

    # 1. Fetch trading signals without filters
    res = client.get("/v1/intel/signals/trading")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert "trading_signals" in data
    assert data["count"] >= 3

    sig = data["trading_signals"][0]
    assert "signal_id" in sig
    assert "asset" in sig
    assert "action" in sig
    assert "entry_price" in sig
    assert "price_targets" in sig
    assert "stop_loss" in sig
    assert "risk_reward_ratio" in sig
    assert "execution_params" in sig

    # 2. Filter by asset
    res_sol = client.get("/v1/intel/signals/trading?asset=SOL")
    assert res_sol.status_code == 200
    sol_data = res_sol.json()
    assert all(s["asset"] == "SOL" for s in sol_data["trading_signals"])

    # 3. Filter by action
    res_buy = client.get("/v1/intel/signals/trading?action=BUY_ACCUMULATE")
    assert res_buy.status_code == 200
    buy_data = res_buy.json()
    assert all(s["action"] == "BUY_ACCUMULATE" for s in buy_data["trading_signals"])


def test_http_api_intel_sample_payload():
    client = TestClient(app)
    res = client.get("/v1/intel/sample")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["mode"] == "evaluation_unmetered"
    assert "trading_signals" in data
    assert len(data["trading_signals"]) > 0
    assert "opportunities" in data
    assert len(data["opportunities"]) > 0


def test_dag_tool_parameter_registration():
    # Verify new tools are present in registry
    assert "scan_arbitrage_opportunities" in TOOL_DAG_REGISTRY
    assert "get_trading_signals" in TOOL_DAG_REGISTRY

    arb_dag = TOOL_DAG_REGISTRY["scan_arbitrage_opportunities"]
    assert arb_dag.tool_name == "scan_arbitrage_opportunities"
    assert "min_profit_pct" in arb_dag.parameters
    assert "pair" in arb_dag.parameters
    assert "opp_type" in arb_dag.parameters

    sig_dag = TOOL_DAG_REGISTRY["get_trading_signals"]
    assert sig_dag.tool_name == "get_trading_signals"
    assert "asset" in sig_dag.parameters
    assert "action" in sig_dag.parameters
    assert "min_confidence" in sig_dag.parameters

    # Test via API tools endpoint
    client = TestClient(app)
    res = client.get("/v1/tools")
    assert res.status_code == 200
    tools = res.json()["tools"]
    tool_names = [t["tool_name"] for t in tools]
    assert "scan_arbitrage_opportunities" in tool_names
    assert "get_trading_signals" in tool_names
