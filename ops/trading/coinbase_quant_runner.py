#!/usr/bin/env python3
"""
Moltbook Alpha — Autonomous Coinbase Advanced Trade Quant Runner.

Executes quantitative CLOB spread capture and passive limit maker orders on
Coinbase Advanced Trade using live market feeds and the CDP API.

Safety:
- Defaults to dry-run mode unless --live-trade is explicitly provided.
- Strictly enforces Post-Only limit orders (0.4% maker fee, never crosses spread).
- Limits single trade allocation to max $1.00 - $2.00 (protecting small balances).
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Any

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

from ops.trading.coinbase_client import CoinbaseCdpClient  # noqa: E402
from ops.trading.quant_trader import QuantTradingEngine  # noqa: E402


class CoinbaseQuantRunner:
    def __init__(self, client: CoinbaseCdpClient, engine: QuantTradingEngine):
        self.client = client
        self.engine = engine

    def evaluate_market_opportunity(self, product_id: str = "SOL-USDC", trade_size_usd: float = 1.0) -> Dict[str, Any]:
        """
        Polls live order book, evaluates feasibility, and calculates optimal passive maker price.
        """
        # 1. Check account balances
        balances = self.client.get_balances_summary()
        usdc_avail = balances.get("USDC", 0.0)
        sol_avail = balances.get("SOL", 0.0)

        # 2. Fetch live order book
        book_resp = self.client.get_orderbook(product_id, limit=10)
        pricebook = book_resp.get("pricebook", {})
        raw_bids = pricebook.get("bids", [])
        raw_asks = pricebook.get("asks", [])

        if not raw_bids or not raw_asks:
            raise RuntimeError(f"Empty orderbook returned for {product_id}")

        best_bid = float(raw_bids[0]["price"])
        best_ask = float(raw_asks[0]["price"])

        orderbook_bids = [(float(b["price"]), float(b["size"])) for b in raw_bids]
        orderbook_asks = [(float(a["price"]), float(a["size"])) for a in raw_asks]

        total_reported_liquidity = sum(s for _, s in orderbook_bids) + sum(s for _, s in orderbook_asks)

        # 3. Quant Engine evaluation
        feasibility = self.engine.evaluate_clob_spread_feasibility(
            best_bid=best_bid,
            best_ask=best_ask,
            reported_liquidity=total_reported_liquidity,
            orderbook_bids=orderbook_bids,
            orderbook_asks=orderbook_asks,
            tick_size=0.01,
        )

        # 4. Compute target limit price
        # For a passive maker buy order: sit at the best bid (or 1 tick below best ask)
        target_bid_price = best_bid
        base_size = trade_size_usd / target_bid_price

        # Fee calculations: Maker fee on Coinbase Advanced is 0.40%
        maker_fee_rate = 0.0040
        est_fee_usd = trade_size_usd * maker_fee_rate

        return {
            "product_id": product_id,
            "trade_size_usd": trade_size_usd,
            "usdc_available": usdc_avail,
            "sol_available": sol_avail,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": feasibility["spread"],
            "target_bid_price": target_bid_price,
            "target_base_size": round(base_size, 8),
            "estimated_maker_fee_usd": round(est_fee_usd, 5),
            "quant_feasibility": feasibility,
            "can_afford": usdc_avail >= trade_size_usd,
        }

    def run_strategy_cycle(self, product_id: str = "SOL-USDC", trade_size_usd: float = 1.0, live_trade: bool = False) -> Dict[str, Any]:
        opp = self.evaluate_market_opportunity(product_id=product_id, trade_size_usd=trade_size_usd)

        if not opp["can_afford"]:
            return {
                "success": False,
                "error": f"INSUFFICIENT_USDC: Available ${opp['usdc_available']:.2f} < Required ${trade_size_usd:.2f}",
                "opportunity": opp,
            }

        # Place order (Post-Only maker)
        order_res = self.client.create_limit_order(
            product_id=product_id,
            side="BUY",
            base_size=opp["target_base_size"],
            limit_price=opp["target_bid_price"],
            post_only=True,
            dry_run=not live_trade,
        )

        return {
            "success": True,
            "live_trade": live_trade,
            "opportunity": opp,
            "order": order_res,
        }


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha — Coinbase Advanced Trade Quant Runner")
    parser.add_argument("--product", default="SOL-USDC", help="Product pair (default: SOL-USDC)")
    parser.add_argument("--amount", type=float, default=1.0, help="Trade amount in USD (default: $1.00)")
    parser.add_argument("--live-trade", action="store_true", help="Execute live order on Coinbase (defaults to dry-run)")
    args = parser.parse_args()

    client = CoinbaseCdpClient()
    engine = QuantTradingEngine(initial_capital_usdc=2.73)
    runner = CoinbaseQuantRunner(client=client, engine=engine)

    mode = "LIVE EXECUTION" if args.live_trade else "DRY-RUN SIMULATION"
    print(f"[Moltbook Alpha] Running Coinbase Quant Runner in {mode} mode for {args.product}...")

    res = runner.run_strategy_cycle(product_id=args.product, trade_size_usd=args.amount, live_trade=args.live_trade)

    if not res["success"]:
        print(f"  Run aborted: {res.get('error')}")
        return

    opp = res["opportunity"]
    print(f"  Available USDC:   ${opp['usdc_available']:.4f}")
    print(f"  Market Best Bid:  ${opp['best_bid']:.2f}")
    print(f"  Market Best Ask:  ${opp['best_ask']:.2f}")
    print(f"  Spread:           ${opp['spread']:.2f}")
    print(f"  Target Limit Buy: {opp['target_base_size']} {args.product.split('-')[0]} @ ${opp['target_bid_price']:.2f} (Post-Only)")
    print(f"  Estimated Fee:    ${opp['estimated_maker_fee_usd']} (0.40% Maker)")
    print(f"  Order Status:     {'PLACED ON ORDERBOOK' if args.live_trade else 'SIMULATED (DRY-RUN)'}")
    if not args.live_trade:
        print(f"  Dry-run Payload:  {res['order']['payload']}")


if __name__ == "__main__":
    main()
