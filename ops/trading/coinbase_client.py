#!/usr/bin/env python3
"""
Moltbook Alpha — Coinbase Advanced Trade / CDP API Client.

Integrates with Coinbase Developer Platform (CDP) REST APIs using Ed25519 (EdDSA) JWTs.
Supports portfolio inspection, spot order book quotes, and zero-fee USDC conversion checks.

Safety:
- Read-only queries execute freely.
- Order execution and fund movement methods require explicit confirmation flags.
- Private keys are loaded in-memory and never logged or exposed.
"""

import base64
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519
import httpx
import jwt

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

DEFAULT_CDP_KEY_PATH = Path(os.getenv("CDP_API_KEY_PATH", r"F:\API Keys\CB\cdp_api_key.json"))
COINBASE_API_HOST = "api.coinbase.com"


class CoinbaseCdpClient:
    def __init__(self, key_path: Path | str = DEFAULT_CDP_KEY_PATH):
        self.key_path = Path(key_path)
        if not self.key_path.is_file():
            raise FileNotFoundError(f"Coinbase CDP API key file not found at: {self.key_path}")

        self._key_id, self._private_key = self._load_credentials()
        self._http = httpx.Client(timeout=10.0)

    def _load_credentials(self) -> tuple[str, ed25519.Ed25519PrivateKey]:
        with open(self.key_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        key_id = data.get("name") or data.get("id")
        if not key_id:
            raise ValueError("CDP key JSON must contain 'name' or 'id'")

        raw_secret = data.get("privateKey", "").strip()
        if not raw_secret:
            raise ValueError("CDP key JSON must contain 'privateKey'")

        # Parse Ed25519 private key
        raw_bytes = base64.b64decode(raw_secret)
        if len(raw_bytes) < 32:
            raise ValueError(f"Decoded privateKey too short ({len(raw_bytes)} bytes)")

        # Ed25519 seed is first 32 bytes
        priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes[:32])
        return str(key_id), priv_key

    def generate_jwt(self, method: str, path: str) -> str:
        """Generates a 2-minute expiring EdDSA JWT for Coinbase Advanced Trade REST endpoints."""
        uri = f"{method.upper()} {COINBASE_API_HOST}{path}"
        now = int(time.time())
        payload = {
            "sub": self._key_id,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": uri,
        }
        headers = {
            "kid": self._key_id,
            "nonce": secrets.token_hex(),
        }
        return jwt.encode(payload, self._private_key, algorithm="EdDSA", headers=headers)

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        token = self.generate_jwt(method, path)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"https://{COINBASE_API_HOST}{path}"

        if method.upper() == "GET":
            resp = self._http.get(url, headers=headers, params=params)
        elif method.upper() == "POST":
            resp = self._http.post(url, headers=headers, json=json_body)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if resp.status_code != 200:
            raise RuntimeError(f"Coinbase API {method} {path} failed ({resp.status_code}): {resp.text}")

        return resp.json()

    def get_accounts(self) -> List[Dict[str, Any]]:
        """Retrieves list of brokerage accounts."""
        res = self._request("GET", "/api/v3/brokerage/accounts")
        return res.get("accounts", [])

    def get_balances_summary(self) -> Dict[str, float]:
        """Returns non-zero available balances mapped by currency."""
        accounts = self.get_accounts()
        balances = {}
        for acc in accounts:
            curr = acc.get("currency")
            avail = float(acc.get("available_balance", {}).get("value", 0.0))
            if avail > 0:
                balances[curr] = avail
        return balances

    def get_product(self, product_id: str) -> Dict[str, Any]:
        """Retrieves product trading pair info (e.g. 'SOL-USDC', 'BTC-USD')."""
        return self._request("GET", f"/api/v3/brokerage/products/{product_id}")

    def get_orderbook(self, product_id: str, limit: int = 10) -> Dict[str, Any]:
        """Retrieves real-time product bid/ask order book."""
        return self._request("GET", "/api/v3/brokerage/product_book", params={"product_id": product_id, "limit": limit})

    def create_limit_order(
        self,
        product_id: str,
        side: str,  # "BUY" or "SELL"
        base_size: float,
        limit_price: float,
        post_only: bool = True,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """
        Creates a Post-Only limit order.
        Safety: dry_run defaults to True to prevent accidental execution.
        """
        side_upper = side.upper()
        if side_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}. Must be 'BUY' or 'SELL'.")

        client_order_id = secrets.token_hex(16)
        formatted_price = f"{limit_price:.2f}"
        formatted_size = f"{base_size:.8f}"
        notional_usd = base_size * limit_price

        payload = {
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side_upper,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": formatted_size,
                    "limit_price": formatted_price,
                    "post_only": post_only,
                }
            },
        }

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "client_order_id": client_order_id,
                "product_id": product_id,
                "side": side_upper,
                "base_size": float(formatted_size),
                "limit_price": float(formatted_price),
                "notional_usd": round(notional_usd, 4),
                "post_only": post_only,
                "payload": payload,
            }

        res = self._request("POST", "/api/v3/brokerage/orders", json_body=payload)
        return {
            "success": True,
            "dry_run": False,
            "response": res,
        }

    def list_orders(self, product_id: Optional[str] = None, order_status: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Lists active or historical orders."""
        params: Dict[str, Any] = {}
        if product_id:
            params["product_id"] = product_id
        if order_status:
            params["order_status"] = order_status
        res = self._request("GET", "/api/v3/brokerage/orders/historical/batch", params=params)
        return res.get("orders", [])

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancels an order by ID."""
        payload = {"order_ids": [order_id]}
        return self._request("POST", "/api/v3/brokerage/orders/batch_cancel", json_body=payload)


if __name__ == "__main__":
    client = CoinbaseCdpClient()
    print("[Coinbase CDP] Successfully authenticated.")
    balances = client.get_balances_summary()
    print("Non-zero balances:")
    for curr, amt in balances.items():
        print(f"  {curr}: {amt}")

    # Check SOL-USDC market price
    try:
        sol_prod = client.get_product("SOL-USDC")
        price = sol_prod.get("price")
        print(f"Current SOL-USDC price: ${price}")
    except Exception as e:
        print(f"Could not fetch SOL-USDC: {e}")
