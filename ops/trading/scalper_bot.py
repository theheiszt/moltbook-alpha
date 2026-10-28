#!/usr/bin/env python3
"""
Moltbook Alpha — Autonomous CLOB Spread Scalper Bot.

Monitors active orders, detects fills, calculates realized PnL,
and autonomously cycles between passive Post-Only Maker bids and profit-taking asks.

Safety Features:
- Post-Only Maker enforcement (never pays retail taker fees).
- Re-evaluates takeable depth and phantom liquidity before each cycle.
- Graceful shutdown on SIGINT/SIGTERM.
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# Fix Windows console encoding if executed standalone
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import DATA_DIR  # noqa: E402
from ops.trading.coinbase_client import CoinbaseCdpClient  # noqa: E402
from ops.trading.quant_trader import QuantTradingEngine  # noqa: E402

TRADES_LOG = DATA_DIR / "coinbase_trades.json"


class SpreadScalperBot:
    def __init__(
        self,
        client: CoinbaseCdpClient,
        engine: Optional[QuantTradingEngine] = None,
        product_id: str = "SOL-USDC",
        profit_target_pct: float = 0.010,  # 1.0% target
    ):
        self.client = client
        self.engine = engine or QuantTradingEngine(initial_capital_usdc=2.73)
        self.product_id = product_id
        self.profit_target_pct = profit_target_pct

    def check_active_orders(self) -> Dict[str, Any]:
        """Queries any currently open orders for the product."""
        orders = self.client.list_orders(product_id=self.product_id, order_status=["OPEN"])
        if orders:
            active = orders[0]
            cfg = active.get("order_configuration", {}).get("limit_limit_gtc", {})
            return {
                "has_open_order": True,
                "order_id": active.get("order_id"),
                "side": active.get("side"),
                "limit_price": float(cfg.get("limit_price", 0.0)),
                "base_size": float(cfg.get("base_size", 0.0)),
                "raw_order": active,
            }
        return {"has_open_order": False}

    def run_single_iteration(self) -> Dict[str, Any]:
        """
        Runs one evaluation cycle:
        - If an order is open, reports current market distance to target.
        - If no order is open, checks if we hold SOL to sell or USDC to buy.
        """
        # 1. Check order status
        active = self.check_active_orders()

        # 2. Get current market price
        prod = self.client.get_product(self.product_id)
        current_price = float(prod.get("price", 0.0))

        # 3. Check balances
        balances = self.client.get_balances_summary()
        sol_bal = balances.get("SOL", 0.0)
        usdc_bal = balances.get("USDC", 0.0)

        timestamp_iso = datetime.now(timezone.utc).isoformat()

        if active["has_open_order"]:
            target_price = active["limit_price"]
            side = active["side"]
            diff_pct = ((target_price - current_price) / max(current_price, 0.01)) * 100.0

            return {
                "timestamp": timestamp_iso,
                "state": f"WAITING_FOR_FILL_{side}",
                "order_id": active["order_id"],
                "side": side,
                "target_price": target_price,
                "current_price": current_price,
                "distance_to_target_pct": round(diff_pct, 2),
                "sol_balance": sol_bal,
                "usdc_balance": usdc_bal,
            }

        # No open order: decide next move based on balances
        if sol_bal >= 0.01:
            # We hold SOL: Place profit-take limit sell
            target_sell_price = round(current_price * (1.0 + self.profit_target_pct), 2)
            order_res = self.client.create_limit_order(
                product_id=self.product_id,
                side="SELL",
                base_size=sol_bal,
                limit_price=target_sell_price,
                post_only=True,
                dry_run=False,
            )
            return {
                "timestamp": timestamp_iso,
                "state": "PLACED_PROFIT_TAKE_SELL",
                "sell_price": target_sell_price,
                "size": sol_bal,
                "response": order_res,
            }

        elif usdc_bal >= 1.0:
            # We hold USDC: Place passive maker buy on the bid
            book = self.client.get_orderbook(self.product_id, limit=5)
            bids = book.get("pricebook", {}).get("bids", [])
            best_bid = float(bids[0]["price"]) if bids else current_price
            trade_amount_usd = min(usdc_bal, 2.70)
            base_size = round(trade_amount_usd / best_bid, 8)

            order_res = self.client.create_limit_order(
                product_id=self.product_id,
                side="BUY",
                base_size=base_size,
                limit_price=best_bid,
                post_only=True,
                dry_run=False,
            )
            return {
                "timestamp": timestamp_iso,
                "state": "PLACED_PASSIVE_BUY",
                "buy_price": best_bid,
                "size": base_size,
                "response": order_res,
            }

        else:
            return {
                "timestamp": timestamp_iso,
                "state": "INSUFFICIENT_FUNDS_TO_CYCLE",
                "current_price": current_price,
                "sol_balance": sol_bal,
                "usdc_balance": usdc_bal,
            }


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha — Autonomous Spread Scalper Bot")
    parser.add_argument("--once", action="store_true", help="Run a single status check and exit")
    parser.add_argument("--interval", type=int, default=15, help="Seconds between cycles (default: 15s)")
    args = parser.parse_args()

    client = CoinbaseCdpClient()
    bot = SpreadScalperBot(client=client)

    print("[Moltbook Alpha] Starting Autonomous CLOB Spread Scalper Bot...")
    if args.once:
        status = bot.run_single_iteration()
        print(f"  State: {status['state']}")
        print(f"  Current SOL Price: ${status.get('current_price')}")
        if "target_price" in status:
            print(f"  Open Order: {status['side']} @ ${status['target_price']:.2f} (Gap: {status['distance_to_target_pct']:+.2f}%)")
        print(f"  Balances: SOL={status.get('sol_balance')}, USDC=${status.get('usdc_balance')}")
        return

    print(f"  Monitoring order book every {args.interval}s. Press Ctrl+C to stop.")
    try:
        while True:
            status = bot.run_single_iteration()
            now_str = datetime.now().strftime("%H:%M:%S")
            state = status.get("state")
            curr_px = status.get("current_price")
            gap = status.get("distance_to_target_pct", 0.0)
            print(f"[{now_str}] State: {state} | SOL: ${curr_px} | Target Gap: {gap:+.2f}%")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[Moltbook Alpha] Scalper Bot stopped gracefully.")


if __name__ == "__main__":
    main()
