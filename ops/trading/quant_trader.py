#!/usr/bin/env python3
"""
Moltbook Alpha — Autonomous Quantitative Trading & Arbitrage Runner.
Implements:
1. Prediction Market CLOB Spread Arbitrage & Zero-Cost Gross Mean Filtering
2. Solana Cluster Priority-Fee Volatility Momentum Detection
3. Random Matrix Theory (RMT) Correlation Denoising for Cross-Asset Statistical Arbitrage
4. Paper-Trading Execution Engine & Ledger Logging
"""

import math
from typing import Dict, Any, List, Tuple


class QuantTradingEngine:
    def __init__(self, initial_capital_usdc: float = 1000.0, taker_fee_rate: float = 0.001):
        self.capital_usdc = initial_capital_usdc
        self.taker_fee_rate = taker_fee_rate
        self.positions: Dict[str, float] = {}
        self.trade_history: List[Dict[str, Any]] = []

    # =========================================================================
    # 1. Prediction Market CLOB Spread Arbitrage & Gross Mean Feasibility
    # =========================================================================
    def evaluate_clob_spread_feasibility(
        self,
        best_bid: float,
        best_ask: float,
        reported_liquidity: float,
        orderbook_bids: List[Tuple[float, float]],  # List of (price, size)
        orderbook_asks: List[Tuple[float, float]],  # List of (price, size)
        tick_size: float = 0.01,
    ) -> Dict[str, Any]:
        """
        Calculates genuine takeable depth within one tick and evaluates whether
        the spread clears the zero-cost gross mean profitability filter.
        """
        spread = best_ask - best_bid
        half_spread = spread / 2.0
        mid_price = (best_bid + best_ask) / 2.0

        # Calculate takeable ask depth within 1 tick of best ask
        takeable_ask_depth = sum(size for price, size in orderbook_asks if price <= best_ask + tick_size)
        takeable_bid_depth = sum(size for price, size in orderbook_bids if price >= best_bid - tick_size)

        # Phantom liquidity ratio
        depth_ratio = (takeable_ask_depth + takeable_bid_depth) / max(reported_liquidity, 1.0)

        # Zero-Cost Gross Mean Rule: Expected spread capture must exceed 2.5x total round-trip fee friction
        fee_friction = 2.0 * (self.taker_fee_rate * mid_price)
        threshold_friction = 2.5 * (half_spread * 0.1 + fee_friction)
        is_viable = spread > threshold_friction and depth_ratio < 0.60

        return {
            "mid_price": round(mid_price, 4),
            "spread": round(spread, 4),
            "half_spread": round(half_spread, 4),
            "takeable_ask_depth": round(takeable_ask_depth, 2),
            "takeable_bid_depth": round(takeable_bid_depth, 2),
            "depth_to_reported_ratio": round(depth_ratio, 4),
            "is_phantom_liquidity_detected": depth_ratio < 0.50,
            "is_arbitrage_viable": is_viable,
            "recommended_strategy": "PASSIVE_LIMIT_MAKER" if is_viable else "AVOID_CROSSING_SPREAD",
        }

    # =========================================================================
    # 2. Solana Cluster Priority-Fee Volatility Momentum
    # =========================================================================
    def evaluate_cluster_momentum(
        self,
        current_tps: float,
        baseline_tps: float,
        priority_fee_percentile_75: float,
        baseline_priority_fee: float,
        rejection_rate: float,
    ) -> Dict[str, Any]:
        """
        Detects volatility breakout regimes triggered by Solana cluster TPS surges
        and priority fee bidding wars.
        """
        tps_surge_ratio = current_tps / max(baseline_tps, 1.0)
        fee_velocity_ratio = priority_fee_percentile_75 / max(baseline_priority_fee, 1.0)

        is_surge = current_tps > 5000.0 or tps_surge_ratio > 1.30
        is_fee_spike = fee_velocity_ratio > 1.50
        is_breakout_regime = is_surge and is_fee_spike

        signal = "NEUTRAL"
        if is_breakout_regime:
            signal = "VOLATILITY_EXPANSION_BREAKOUT" if rejection_rate < 0.15 else "CONGESTION_LIQUIDATION_RISK"

        return {
            "current_tps": current_tps,
            "tps_surge_ratio": round(tps_surge_ratio, 2),
            "fee_velocity_ratio": round(fee_velocity_ratio, 2),
            "rejection_rate": round(rejection_rate, 4),
            "is_breakout_regime": is_breakout_regime,
            "trading_signal": signal,
            "recommended_action": "ENTER_MOMENTUM_RUN" if signal == "VOLATILITY_EXPANSION_BREAKOUT" else "REDUCE_EXPOSURE",
        }

    # =========================================================================
    # 3. Random Matrix Theory (RMT) Eigenvalue Denoising
    # =========================================================================
    def compute_rmt_upper_bound(self, n_assets: int, t_periods: int, variance: float = 1.0) -> float:
        """
        Calculates the Marcenko-Pastur theoretical upper bound for noise eigenvalues:
        lambda_max = variance * (1 + sqrt(N/T))^2
        """
        q = n_assets / max(t_periods, 1)
        return variance * ((1.0 + math.sqrt(q)) ** 2)

    def filter_rmt_eigenvalues(
        self,
        eigenvalues: List[float],
        n_assets: int,
        t_periods: int,
    ) -> Tuple[List[float], List[float]]:
        """
        Splits eigenvalues into genuine signal factors (above Marcenko-Pastur bound)
        and noise eigenvalues (which should be shrunk / clipped).
        """
        lambda_max = self.compute_rmt_upper_bound(n_assets, t_periods)
        signals = [lam for lam in eigenvalues if lam > lambda_max]
        noise = [lam for lam in eigenvalues if lam <= lambda_max]
        return signals, noise

    # =========================================================================
    # 4. Paper-Trading Execution & Accounting
    # =========================================================================
    def execute_paper_order(
        self,
        symbol: str,
        side: str,  # "BUY" or "SELL"
        amount_usd: float,
        price: float,
    ) -> Dict[str, Any]:
        fee = amount_usd * self.taker_fee_rate
        net_amount = amount_usd - fee

        if side == "BUY":
            if amount_usd > self.capital_usdc:
                return {"success": False, "error": "INSUFFICIENT_FUNDS"}
            units = net_amount / price
            self.capital_usdc -= amount_usd
            self.positions[symbol] = self.positions.get(symbol, 0.0) + units
        elif side == "SELL":
            current_units = self.positions.get(symbol, 0.0)
            units_to_sell = amount_usd / price
            if units_to_sell > current_units:
                return {"success": False, "error": "INSUFFICIENT_POSITION"}
            self.positions[symbol] -= units_to_sell
            self.capital_usdc += net_amount
        else:
            return {"success": False, "error": "INVALID_SIDE"}

        trade_record = {
            "symbol": symbol,
            "side": side,
            "amount_usd": amount_usd,
            "price": price,
            "fee": fee,
            "remaining_cash": self.capital_usdc,
        }
        self.trade_history.append(trade_record)
        return {"success": True, "trade": trade_record}
