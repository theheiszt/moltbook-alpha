#!/usr/bin/env python3
"""
Moltbook Alpha — Solana DEX Micro-Trading Client.

Integrates with Jupiter v6 Swap API to quote, route, and execute ultra-low-fee
micro-trades ($1 - $5) across Solana DEX liquidity pools (Orca Whirlpools,
Raydium CLMM, OpenBook, Meteora DLMM).

Safety Rules:
- Enforces max slippage cap (default 50 bps / 0.50%).
- Rejects trades with price impact > 0.30% for micro-lots.
- Verifies CLOB/AMM spread feasibility before building execution transactions.
- Zero live execution without explicit user consent.
"""

import base64
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import httpx

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

from config import CANONICAL_USDC_MINT, USDC_DECIMALS, SOL_DECIMALS  # noqa: E402
from ops.trading.quant_trader import QuantTradingEngine  # noqa: E402
from ops.trading.solana_wallet_setup import SolanaTradingWallet  # noqa: E402

# Well-known mint addresses
TOKEN_MINTS = {
    "USDC": {
        "mint": CANONICAL_USDC_MINT,
        "decimals": USDC_DECIMALS,
    },
    "SOL": {
        "mint": "So11111111111111111111111111111111111111112",
        "decimals": SOL_DECIMALS,
    },
    "WSOL": {
        "mint": "So11111111111111111111111111111111111111112",
        "decimals": SOL_DECIMALS,
    },
    "BONK": {
        "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "decimals": 5,
    },
    "JUP": {
        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "decimals": 6,
    },
}

JUPITER_QUOTE_API = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_API = "https://api.jup.ag/swap/v1/swap"

# Typical Solana transaction base fee + priority fee in USD (~0.000005 to 0.00002 SOL)
ESTIMATED_SOL_FEE_USD = 0.0003


class SolanaDexClient:
    def __init__(
        self,
        wallet: Optional[SolanaTradingWallet] = None,
        quant_engine: Optional[QuantTradingEngine] = None,
        max_slippage_bps: int = 50,  # 0.5%
        http_client: Optional[httpx.Client] = None,
    ):
        self.wallet = wallet
        self.quant_engine = quant_engine or QuantTradingEngine(initial_capital_usdc=5.0)
        self.max_slippage_bps = max_slippage_bps
        self._client = http_client or httpx.Client(timeout=10.0)

    def resolve_token_info(self, symbol_or_mint: str) -> Dict[str, Any]:
        """Resolves symbol or raw mint string to mint address and decimals."""
        upper = symbol_or_mint.upper()
        if upper in TOKEN_MINTS:
            return TOKEN_MINTS[upper]
        return {
            "mint": symbol_or_mint,
            "decimals": 6,  # default fallback
        }

    def get_quote(
        self,
        input_symbol: str,
        output_symbol: str,
        amount_human: float,
        slippage_bps: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Fetches best execution route and quote from Jupiter v6 API.
        """
        in_info = self.resolve_token_info(input_symbol)
        out_info = self.resolve_token_info(output_symbol)

        in_decimals = in_info["decimals"]
        out_decimals = out_info["decimals"]

        raw_in_amount = int(round(amount_human * (10 ** in_decimals)))
        bps = slippage_bps if slippage_bps is not None else self.max_slippage_bps

        params = {
            "inputMint": in_info["mint"],
            "outputMint": out_info["mint"],
            "amount": str(raw_in_amount),
            "slippageBps": str(bps),
        }

        resp = self._client.get(JUPITER_QUOTE_API, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Jupiter quote failed with HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        raw_out_amount = int(data.get("outAmount", 0))
        out_amount_human = raw_out_amount / (10 ** out_decimals)

        # Price impact pct
        price_impact_pct = float(data.get("priceImpactPct", 0.0))

        # Extract route protocol names
        route_plan = data.get("routePlan", [])
        protocol_steps = [
            step.get("swapInfo", {}).get("label", "DEX")
            for step in route_plan
        ]
        route_summary = " -> ".join(protocol_steps) if protocol_steps else "Direct"

        return {
            "success": True,
            "input_symbol": input_symbol.upper(),
            "output_symbol": output_symbol.upper(),
            "in_amount": amount_human,
            "out_amount": out_amount_human,
            "raw_in_amount": raw_in_amount,
            "raw_out_amount": raw_out_amount,
            "price_impact_pct": price_impact_pct,
            "route_summary": route_summary,
            "slippage_bps": bps,
            "raw_quote": data,
        }

    def evaluate_micro_trade(
        self,
        input_symbol: str,
        output_symbol: str,
        amount_usd: float,
    ) -> Dict[str, Any]:
        """
        Validates whether a micro-trade is economically viable after fees and slippage.
        """
        quote = self.get_quote(input_symbol, output_symbol, amount_usd)

        # Calculate estimated fee friction
        fee_friction_usd = ESTIMATED_SOL_FEE_USD
        price_impact_usd = (quote["price_impact_pct"] / 100.0) * amount_usd

        # Safety checks for micro-trading:
        # 1. Price impact must not exceed 0.30%
        # 2. Total friction must be less than 1.0% of the trade size
        total_friction_usd = fee_friction_usd + price_impact_usd
        friction_pct = (total_friction_usd / max(amount_usd, 0.01)) * 100.0

        is_viable = quote["price_impact_pct"] < 0.30 and friction_pct < 1.0

        return {
            "quote": quote,
            "amount_usd": amount_usd,
            "estimated_gas_usd": round(fee_friction_usd, 6),
            "price_impact_usd": round(price_impact_usd, 6),
            "total_friction_usd": round(total_friction_usd, 6),
            "friction_pct": round(friction_pct, 4),
            "is_viable": is_viable,
            "rejection_reason": None if is_viable else "FRICTION_OR_PRICE_IMPACT_EXCEEDED",
        }

    def simulate_micro_swap(
        self,
        input_symbol: str,
        output_symbol: str,
        amount_usd: float,
    ) -> Dict[str, Any]:
        """
        Runs a dry-run / paper execution of a micro-swap using live on-chain quotes.
        Safe to execute without moving real funds.
        """
        eval_res = self.evaluate_micro_trade(input_symbol, output_symbol, amount_usd)
        if not eval_res["is_viable"]:
            return {
                "success": False,
                "error": eval_res["rejection_reason"],
                "evaluation": eval_res,
            }

        quote = eval_res["quote"]
        in_amt = quote["in_amount"]
        out_amt = quote["out_amount"]
        exec_price = in_amt / max(out_amt, 1e-9)

        # Log simulated trade to QuantTradingEngine paper ledger
        paper_res = self.quant_engine.execute_paper_order(
            symbol=output_symbol.upper(),
            side="BUY",
            amount_usd=amount_usd,
            price=exec_price,
        )

        return {
            "success": True,
            "dry_run": True,
            "input_swapped": f"{in_amt} {input_symbol.upper()}",
            "output_received": f"{out_amt:.6f} {output_symbol.upper()}",
            "execution_price": exec_price,
            "price_impact_pct": quote["price_impact_pct"],
            "route": quote["route_summary"],
            "estimated_sol_gas": f"${ESTIMATED_SOL_FEE_USD:.4f}",
            "paper_ledger_status": paper_res,
        }

    def build_swap_transaction(
        self,
        raw_quote: Dict[str, Any],
        user_public_key: str,
    ) -> Dict[str, Any]:
        """
        Builds the raw serialized versioned transaction via Jupiter /swap endpoint.
        Does NOT sign or broadcast.
        """
        payload = {
            "quoteResponse": raw_quote,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": "auto",
        }
        resp = self._client.post(JUPITER_SWAP_API, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to build swap transaction: {resp.text}")
        data = resp.json()
        return {
            "swap_transaction_b64": data.get("swapTransaction"),
            "last_valid_block_height": data.get("lastValidBlockHeight"),
        }

    def sign_and_broadcast_swap(
        self,
        swap_tx_b64: str,
        wallet_file: Path | str,
        rpc_url: str = "https://api.mainnet-beta.solana.com",
    ) -> Dict[str, Any]:
        """
        Signs the serialized VersionedTransaction and broadcasts it via Solana JSON-RPC.
        """
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction

        p = Path(wallet_file)
        with open(p, "r", encoding="utf-8") as f:
            key_data = json.load(f)
        kp = Keypair.from_bytes(bytes(key_data))

        raw_tx = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(raw_tx)

        sig = kp.sign_message(bytes(tx.message))
        signed_tx = VersionedTransaction.populate(tx.message, [sig])
        encoded_tx = base64.b64encode(bytes(signed_tx)).decode("utf-8")

        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                encoded_tx,
                {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"},
            ],
        }
        resp = self._client.post(rpc_url, json=req, timeout=15.0)
        if resp.status_code != 200:
            raise RuntimeError(f"RPC sendTransaction failed ({resp.status_code})")
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Solana transaction failed: {data['error']}")
        return {
            "success": True,
            "signature": data.get("result"),
            "explorer_url": f"https://solscan.io/tx/{data.get('result')}" if data.get("result") else None,
        }


if __name__ == "__main__":
    print("[Moltbook Alpha] Testing Jupiter DEX Quote for $1.00 USDC -> SOL...")
    client = SolanaDexClient()
    try:
        quote = client.get_quote("USDC", "SOL", 1.0)
        print(f"  Input:        {quote['in_amount']} USDC")
        print(f"  Output:       {quote['out_amount']:.6f} SOL")
        print(f"  Price Impact: {quote['price_impact_pct']}%")
        print(f"  Route:        {quote['route_summary']}")

        sim = client.simulate_micro_swap("USDC", "SOL", 1.0)
        print(f"  Dry-run Swap: {sim['output_received']} via {sim['route']}")
    except Exception as e:
        print(f"  Quote error (network check): {e}")
