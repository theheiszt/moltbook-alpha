#!/usr/bin/env python3
"""
Moltbook Alpha — Autonomous Solana DEX Micro-Trading Runner.

Monitors local trading wallet on-chain balances, fetches real-time Jupiter quotes,
and executes ultra-low-fee micro-swaps ($0.50 - $2.50) across Solana liquidity pools.
"""

import argparse
import sys
import time
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

from ops.trading.solana_wallet_setup import (  # noqa: E402
    DEFAULT_WALLET_FILE,
    get_or_create_trading_wallet,
)
from ops.trading.solana_dex_client import SolanaDexClient  # noqa: E402


class SolanaDexRunner:
    def __init__(self, wallet_file: Path = DEFAULT_WALLET_FILE):
        self.wallet_file = wallet_file
        self.wallet, _ = get_or_create_trading_wallet(wallet_file)
        self.dex_client = SolanaDexClient(wallet=self.wallet)

    def check_wallet_status(self) -> Dict[str, Any]:
        """Returns public address and live on-chain balances."""
        balances = self.wallet.get_balances()
        return {
            "address": self.wallet.get_public_address(),
            "sol": balances.get("sol", 0.0),
            "usdc": balances.get("usdc", 0.0),
            "is_funded": balances.get("sol", 0.0) > 0.001 or balances.get("usdc", 0.0) > 0.10,
        }

    def wait_for_funding(self, poll_interval: int = 5, timeout_seconds: int = 300) -> bool:
        """Polls Solana cluster until the wallet receives funds."""
        print(f"[Moltbook Alpha] Waiting for funds on {self.wallet.get_public_address()}...")
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            status = self.check_wallet_status()
            if status["is_funded"]:
                print(f"\n[Moltbook Alpha] Funds detected! SOL: {status['sol']} | USDC: ${status['usdc']}")
                return True
            time.sleep(poll_interval)
            print(".", end="", flush=True)
        print("\n[Moltbook Alpha] Timed out waiting for deposit.")
        return False

    def display_market_opportunities(self, sol_amount: float = 0.01) -> None:
        """Displays live Jupiter quotes for common micro-trading pairs."""
        print(f"\n[Jupiter DEX Quotes for {sol_amount} SOL]:")
        for target_sym in ["USDC", "JUP", "BONK"]:
            try:
                quote = self.dex_client.get_quote("SOL", target_sym, sol_amount)
                out_fmt = f"{quote['out_amount']:,.2f}" if target_sym == "BONK" else f"{quote['out_amount']:.4f}"
                print(f"  SOL -> {target_sym:5s}: Yields {out_fmt} {target_sym} (Route: {quote['route_summary']})")
            except Exception as e:
                print(f"  SOL -> {target_sym:5s}: Quote unavailable ({e})")

    def execute_swap(
        self,
        input_token: str,
        output_token: str,
        amount: float,
        live_swap: bool = False,
    ) -> Dict[str, Any]:
        """Executes or dry-runs a micro-swap on Jupiter."""
        # 1. Fetch live quote
        quote = self.dex_client.get_quote(input_token, output_token, amount)
        user_pubkey = self.wallet.get_public_address()

        if not live_swap:
            return {
                "success": True,
                "mode": "DRY_RUN",
                "input": f"{amount} {input_token}",
                "expected_output": f"{quote['out_amount']} {output_token}",
                "price_impact": f"{quote['price_impact_pct']}%",
                "route": quote["route_summary"],
            }

        # 2. Build swap transaction
        tx_data = self.dex_client.build_swap_transaction(quote["raw_quote"], user_pubkey)
        swap_b64 = tx_data["swap_transaction_b64"]

        # 3. Sign and broadcast
        broadcast_res = self.dex_client.sign_and_broadcast_swap(swap_b64, self.wallet_file)
        return {
            "success": True,
            "mode": "LIVE_BROADCAST",
            "input": f"{amount} {input_token}",
            "expected_output": f"{quote['out_amount']} {output_token}",
            "tx_signature": broadcast_res["signature"],
            "explorer_url": broadcast_res["explorer_url"],
        }


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha — Solana DEX Micro-Trading Runner")
    parser.add_argument("--status", action="store_true", help="Display wallet status and balances")
    parser.add_argument("--quotes", action="store_true", help="Fetch live Jupiter DEX quotes")
    parser.add_argument("--wait", action="store_true", help="Poll until wallet receives deposit")
    parser.add_argument("--swap", choices=["USDC", "JUP", "BONK"], help="Swap SOL into target token")
    parser.add_argument("--amount", type=float, default=0.01, help="Amount of SOL to swap (default: 0.01 SOL)")
    parser.add_argument("--live", action="store_true", help="Execute live transaction on Solana (default: dry-run)")
    args = parser.parse_args()

    runner = SolanaDexRunner()
    status = runner.check_wallet_status()

    print("[Moltbook Alpha] Solana DEX Micro-Trading Environment:")
    print(f"  Wallet Address: {status['address']}")
    print(f"  Current Balances: {status['sol']} SOL | ${status['usdc']} USDC")

    if args.wait:
        if not status["is_funded"]:
            runner.wait_for_funding()
        else:
            print("  Wallet is already funded.")

    if args.quotes or not (args.swap or args.wait):
        runner.display_market_opportunities(sol_amount=args.amount)

    if args.swap:
        print(f"\n[Executing Swap: {args.amount} SOL -> {args.swap}]")
        mode_str = "LIVE ON-CHAIN" if args.live else "DRY-RUN SIMULATION"
        print(f"  Mode: {mode_str}")
        res = runner.execute_swap("SOL", args.swap, args.amount, live_swap=args.live)
        print(f"  Result: {res}")


if __name__ == "__main__":
    main()
