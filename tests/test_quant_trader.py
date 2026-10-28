"""
Unit tests for Autonomous Quantitative Trading & Arbitrage Engine (ops/trading/quant_trader.py).
"""

from ops.trading.quant_trader import QuantTradingEngine


def test_clob_spread_feasibility_detects_phantom_liquidity():
    engine = QuantTradingEngine(initial_capital_usdc=1000.0)

    # Orderbook where reported liquidity is 10,000, but real depth is only 500
    bids = [(0.48, 250.0), (0.47, 500.0)]
    asks = [(0.52, 250.0), (0.53, 500.0)]

    res = engine.evaluate_clob_spread_feasibility(
        best_bid=0.48,
        best_ask=0.52,
        reported_liquidity=10000.0,
        orderbook_bids=bids,
        orderbook_asks=asks,
        tick_size=0.01,
    )

    assert res["spread"] == 0.04
    assert res["is_phantom_liquidity_detected"] is True
    assert res["depth_to_reported_ratio"] < 0.20
    assert res["recommended_strategy"] == "PASSIVE_LIMIT_MAKER"


def test_cluster_momentum_volatility_expansion():
    engine = QuantTradingEngine()

    res = engine.evaluate_cluster_momentum(
        current_tps=5128.9,
        baseline_tps=3200.0,
        priority_fee_percentile_75=50000.0,
        baseline_priority_fee=20000.0,
        rejection_rate=0.08,
    )

    assert res["is_breakout_regime"] is True
    assert res["trading_signal"] == "VOLATILITY_EXPANSION_BREAKOUT"
    assert res["recommended_action"] == "ENTER_MOMENTUM_RUN"


def test_cluster_momentum_congestion_risk():
    engine = QuantTradingEngine()

    res = engine.evaluate_cluster_momentum(
        current_tps=5200.0,
        baseline_tps=3000.0,
        priority_fee_percentile_75=60000.0,
        baseline_priority_fee=20000.0,
        rejection_rate=0.25,  # High rejection rate indicates severe drop congestion
    )

    assert res["trading_signal"] == "CONGESTION_LIQUIDATION_RISK"
    assert res["recommended_action"] == "REDUCE_EXPOSURE"


def test_rmt_eigenvalue_denoising():
    engine = QuantTradingEngine()

    # N = 10 assets, T = 100 periods -> q = 0.1
    # lambda_max = (1 + sqrt(0.1))^2 ≈ (1 + 0.3162)^2 ≈ 1.7325
    lambda_max = engine.compute_rmt_upper_bound(n_assets=10, t_periods=100)
    assert 1.70 < lambda_max < 1.75

    eigenvalues = [4.5, 2.8, 1.7, 1.2, 0.9, 0.6, 0.4]
    signals, noise = engine.filter_rmt_eigenvalues(eigenvalues, n_assets=10, t_periods=100)

    # 4.5 and 2.8 are above 1.73 -> real market factors
    assert len(signals) == 2
    assert 4.5 in signals and 2.8 in signals
    # remaining are noise eigenvalues that should be clipped
    assert len(noise) == 5


def test_paper_trading_execution():
    engine = QuantTradingEngine(initial_capital_usdc=500.0, taker_fee_rate=0.001)

    # Buy 100 USD of SOL at 150.0
    res_buy = engine.execute_paper_order("SOL", "BUY", amount_usd=100.0, price=150.0)
    assert res_buy["success"] is True
    assert engine.capital_usdc == 400.0
    assert "SOL" in engine.positions
    assert engine.positions["SOL"] > 0.60

    # Sell half
    res_sell = engine.execute_paper_order("SOL", "SELL", amount_usd=50.0, price=160.0)
    assert res_sell["success"] is True
    assert engine.capital_usdc > 449.0
    assert len(engine.trade_history) == 2
