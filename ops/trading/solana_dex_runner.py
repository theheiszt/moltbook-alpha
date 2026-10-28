#!/usr/bin/env python3
"""
Moltbook Alpha — Autonomous Solana DEX Micro-Trading Runner.

Monitors local trading wallet on-chain balances, fetches real-time Jupiter quotes,
enforces a minimum SOL gas/rent reserve, checks round-trip spread friction,
executes ultra-low-fee micro-swaps, and runs an autonomous take-profit watcher.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

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
from ops.trading.solana_wallet_setup import (  # noqa: E402
    DEFAULT_WALLET_FILE,
    get_or_create_trading_wallet,
)
from ops.trading.solana_dex_client import (  # noqa: E402
    SolanaDexClient,
    MIN_SOL_GAS_RESERVE,
)

DEX_TRADES_LOG = DATA_DIR / "solana_dex_trades.json"


class SolanaDexRunner:
    def __init__(self, wallet_file: Path = DEFAULT_WALLET_FILE, trades_log_path: Path = DEX_TRADES_LOG):
        self.wallet_file = wallet_file
        self.trades_log_path = trades_log_path
        self.wallet, _ = get_or_create_trading_wallet(wallet_file)
        self.dex_client = SolanaDexClient(wallet=self.wallet)

    def _record_trade(self, event: Dict[str, Any]) -> None:
        """Persists a swap or take-profit event to data/solana_dex_trades.json."""
        try:
            self.trades_log_path.parent.mkdir(parents=True, exist_ok=True)
            history: List[Dict[str, Any]] = []
            if self.trades_log_path.is_file():
                with open(self.trades_log_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        history = loaded
            history.append(event)
            with open(self.trades_log_path, "w", encoding="utf-8") as f:
                json.dump(history[-200:], f, indent=2)
        except Exception:
            pass

    def check_wallet_status(self) -> Dict[str, Any]:
        """Returns public address and live on-chain balances."""
        balances = self.wallet.get_balances()
        sol_bal = balances.get("sol", 0.0)
        usdc_bal = balances.get("usdc", 0.0)
        bonk_bal = balances.get("bonk", 0.0)
        jup_bal = balances.get("jup", 0.0)
        return {
            "address": self.wallet.get_public_address(),
            "sol": sol_bal,
            "usdc": usdc_bal,
            "bonk": bonk_bal,
            "jup": jup_bal,
            "spendable_sol": round(max(0.0, sol_bal - MIN_SOL_GAS_RESERVE), 6),
            "is_funded": sol_bal > MIN_SOL_GAS_RESERVE or usdc_bal > 0.10 or bonk_bal > 1000 or jup_bal > 0.1,
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
        """Displays live Jupiter quotes and round-trip spread friction for common pairs."""
        print(f"\n[Jupiter DEX Quotes for {sol_amount} SOL]:")
        for target_sym in ["USDC", "JUP", "BONK"]:
            try:
                quote = self.dex_client.get_quote("SOL", target_sym, sol_amount)
                out_fmt = f"{quote['out_amount']:,.2f}" if target_sym == "BONK" else f"{quote['out_amount']:.4f}"
                print(
                    f"  SOL -> {target_sym:5s}: Yields {out_fmt} {target_sym} "
                    f"(Impact: {quote['price_impact_pct']:.4f}%, Route: {quote['route_summary']})"
                )
            except Exception as e:
                print(f"  SOL -> {target_sym:5s}: Quote unavailable ({e})")

    def execute_swap(
        self,
        input_token: str,
        output_token: str,
        amount: float,
        live_swap: bool = False,
    ) -> Dict[str, Any]:
        """Executes or dry-runs a micro-swap on Jupiter with SOL gas reserve enforcement."""
        in_sym = input_token.upper()
        out_sym = output_token.upper()

        # 1. Fetch live quote
        quote = self.dex_client.get_quote(in_sym, out_sym, amount)
        user_pubkey = self.wallet.get_public_address()

        if not live_swap:
            return {
                "success": True,
                "mode": "DRY_RUN",
                "input": f"{amount} {in_sym}",
                "expected_output": f"{quote['out_amount']} {out_sym}",
                "out_amount": quote["out_amount"],
                "price_impact": f"{quote['price_impact_pct']}%",
                "route": quote["route_summary"],
            }

        # 2. Enforce minimum SOL gas/rent reserve before live broadcast
        status = self.check_wallet_status()
        if in_sym == "SOL":
            if status["sol"] - amount < MIN_SOL_GAS_RESERVE:
                return {
                    "success": False,
                    "mode": "REJECTED_GAS_RESERVE",
                    "error": (
                        f"Swapping {amount} SOL from {status['sol']} SOL would breach "
                        f"MIN_SOL_GAS_RESERVE ({MIN_SOL_GAS_RESERVE} SOL). Max spendable: {status['spendable_sol']} SOL."
                    ),
                }
        elif status["sol"] < 0.001:
            return {
                "success": False,
                "mode": "REJECTED_NO_GAS",
                "error": f"Insufficient SOL ({status['sol']}) to pay network transaction fees.",
            }

        # 3. Build swap transaction & run validator simulation pre-flight
        tx_data = self.dex_client.build_swap_transaction(quote["raw_quote"], user_pubkey)
        swap_b64 = tx_data["swap_transaction_b64"]
        sim_check = self.dex_client.simulate_transaction_onchain(swap_b64)
        if not sim_check.get("success", True):
            return {
                "success": False,
                "mode": "REJECTED_SIMULATION_ERROR",
                "error": sim_check.get("error"),
            }

        # 4. Sign and broadcast
        broadcast_res = self.dex_client.sign_and_broadcast_swap(swap_b64, self.wallet_file)
        tx_sig = broadcast_res.get("signature")
        encoded_tx = broadcast_res.get("encoded_tx")

        # 5. Poll on-chain confirmation status with idempotent multi-RPC rebroadcast
        confirmation = (
            self.dex_client.confirm_transaction(tx_sig, encoded_tx=encoded_tx)
            if tx_sig
            else {"confirmed": False}
        )
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": confirmation.get("confirmed", False),
            "mode": "LIVE_BROADCAST",
            "input_token": in_sym,
            "output_token": out_sym,
            "in_amount": amount,
            "out_amount": quote["out_amount"],
            "input": f"{amount} {in_sym}",
            "expected_output": f"{quote['out_amount']} {out_sym}",
            "route": quote["route_summary"],
            "tx_signature": tx_sig,
            "confirmed": confirmation.get("confirmed", False),
            "confirmation_status": confirmation.get("status"),
            "explorer_url": broadcast_res["explorer_url"],
        }
        self._record_trade(result)
        return result

    def check_take_profit_once(
        self,
        token_symbol: str,
        entry_sol_amount: float,
        target_profit_pct: float = 0.015,
        live_swap: bool = False,
        token_amount_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Checks live Jupiter quote for swapping held token_symbol back into SOL.
        If out_amount >= entry_sol_amount * (1 + target_profit_pct), executes (or dry-runs) the exit swap.
        """
        sym = token_symbol.upper()
        status = self.check_wallet_status()
        held_amount = token_amount_override if token_amount_override is not None else status.get(sym.lower(), 0.0)
        if held_amount <= 0:
            return {
                "state": "NO_TOKEN_BALANCE",
                "token": sym,
                "held_amount": 0.0,
            }

        quote = self.dex_client.get_quote(sym, "SOL", held_amount)
        current_sol_out = quote["out_amount"]
        target_sol_out = round(entry_sol_amount * (1.0 + target_profit_pct), 6)
        pnl_sol = current_sol_out - entry_sol_amount
        pnl_pct = (pnl_sol / max(entry_sol_amount, 1e-9)) * 100.0

        if current_sol_out >= target_sol_out:
            swap_res = self.execute_swap(sym, "SOL", held_amount, live_swap=live_swap)
            return {
                "state": "TAKE_PROFIT_TRIGGERED",
                "token": sym,
                "held_amount": held_amount,
                "entry_sol": entry_sol_amount,
                "current_sol_out": round(current_sol_out, 6),
                "target_sol_out": target_sol_out,
                "pnl_sol": round(pnl_sol, 6),
                "pnl_pct": round(pnl_pct, 3),
                "swap_result": swap_res,
            }

        return {
            "state": "WATCHING_FOR_TARGET",
            "token": sym,
            "held_amount": held_amount,
            "entry_sol": entry_sol_amount,
            "current_sol_out": round(current_sol_out, 6),
            "target_sol_out": target_sol_out,
            "pnl_sol": round(pnl_sol, 6),
            "pnl_pct": round(pnl_pct, 3),
            "route": quote["route_summary"],
        }


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha — Solana DEX Micro-Trading Runner")
    parser.add_argument("--status", action="store_true", help="Display wallet status and balances")
    parser.add_argument("--quotes", action="store_true", help="Fetch live Jupiter DEX quotes")
    parser.add_argument("--wait", action="store_true", help="Poll until wallet receives deposit")
    parser.add_argument("--from-token", default="SOL", choices=["SOL", "USDC", "JUP", "BONK"], help="Input token symbol (default: SOL)")
    parser.add_argument("--swap", choices=["SOL", "USDC", "JUP", "BONK"], help="Swap into target token")
    parser.add_argument("--amount", type=float, default=0.01, help="Amount of input token to swap (default: 0.01)")
    parser.add_argument("--watch-tp", choices=["BONK", "JUP", "USDC"], help="Monitor held token and auto-swap back to SOL at target profit")
    parser.add_argument("--entry-sol", type=float, default=0.02, help="Entry SOL cost basis for take-profit calculation (default: 0.02)")
    parser.add_argument("--target-pct", type=float, default=0.015, help="Take-profit target ratio (default: 0.015 = +1.5%%)")
    parser.add_argument("--interval", type=int, default=15, help="Polling interval in seconds for --watch-tp (default: 15s)")
    parser.add_argument("--once", action="store_true", help="Run a single --watch-tp evaluation and exit")
    parser.add_argument("--live", action="store_true", help="Execute live transaction on Solana (default: dry-run)")
    args = parser.parse_args()

    runner = SolanaDexRunner()
    status = runner.check_wallet_status()

    print("[Moltbook Alpha] Solana DEX Micro-Trading Environment:")
    print(f"  Wallet Address:   {status['address']}")
    print(
        f"  Current Balances: {status['sol']} SOL (Spendable: {status['spendable_sol']} SOL) | "
        f"${status['usdc']} USDC | {status['bonk']:,.2f} BONK | {status['jup']} JUP"
    )

    if args.wait:
        if not status["is_funded"]:
            runner.wait_for_funding()
        else:
            print("  Wallet is already funded.")

    if args.swap:
        print(f"\n[Executing Swap: {args.amount} {args.from_token} -> {args.swap}]")
        mode_str = "LIVE ON-CHAIN" if args.live else "DRY-RUN SIMULATION"
        print(f"  Mode: {mode_str}")
        res = runner.execute_swap(args.from_token, args.swap, args.amount, live_swap=args.live)
        print(f"  Result: {json.dumps(res, indent=2)}")

    if args.watch_tp:
        print(
            f"\n[Take-Profit Watcher: {args.watch_tp} -> SOL | "
            f"Entry: {args.entry_sol} SOL | Target: +{args.target_pct * 100:.2f}% "
            f"({args.entry_sol * (1 + args.target_pct):.6f} SOL) | Live: {args.live}]"
        )
        if args.once:
            tp_res = runner.check_take_profit_once(
                token_symbol=args.watch_tp,
                entry_sol_amount=args.entry_sol,
                target_profit_pct=args.target_pct,
                live_swap=args.live,
            )
            print(f"  TP Check: {json.dumps(tp_res, indent=2)}")
            return

        try:
            while True:
                tp_res = runner.check_take_profit_once(
                    token_symbol=args.watch_tp,
                    entry_sol_amount=args.entry_sol,
                    target_profit_pct=args.target_pct,
                    live_swap=args.live,
                )
                now_str = datetime.now().strftime("%H:%M:%S")
                state = tp_res.get("state")
                if state == "NO_TOKEN_BALANCE":
                    print(f"[{now_str}] No {args.watch_tp} balance detected; stopping watcher.")
                    break
                print(
                    f"[{now_str}] {state} | Held: {tp_res.get('held_amount'):,.2f} {args.watch_tp} -> "
                    f"Now: {tp_res.get('current_sol_out'):.6f} SOL ({tp_res.get('pnl_pct'):+.2f}%) | "
                    f"Target: {tp_res.get('target_sol_out'):.6f} SOL"
                )
                if state == "TAKE_PROFIT_TRIGGERED":
                    print(f"[Moltbook Alpha] Take-Profit executed! Details: {json.dumps(tp_res['swap_result'], indent=2)}")
                    break
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[Moltbook Alpha] Take-Profit Watcher stopped gracefully.")
        return

    if args.quotes or not (args.swap or args.wait or args.watch_tp):
        runner.display_market_opportunities(sol_amount=args.amount if args.from_token == "SOL" else 0.01)


if __name__ == "__main__":
    main()
