#!/usr/bin/env python3
"""
Moltbook Alpha — Secure Solana Trading Wallet Manager.

Provides non-custodial Solana keypair generation, standard [u8; 64] JSON export,
and on-chain SOL / SPL token (USDC, BONK, JUP) balance queries via multi-RPC failover.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

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

from config import (  # noqa: E402
    DATA_DIR,
    CANONICAL_USDC_MINT,
    B58_ALPHABET,
    b58encode,
    load_payment_config,
)

DEFAULT_WALLET_FILE = DATA_DIR / "trading_wallet.json"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
JUP_MINT = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"


def b58decode(s: str) -> bytes:
    """Decodes a Base58 string into raw bytes."""
    num = 0
    for char in s:
        if char not in B58_ALPHABET:
            raise ValueError(f"Invalid Base58 character: {char}")
        num = num * 58 + B58_ALPHABET.index(char)

    leading_ones = len(s) - len(s.lstrip("1"))
    num_bytes = []
    while num > 0:
        num, rem = divmod(num, 256)
        num_bytes.append(rem)
    return (b"\x00" * leading_ones) + bytes(reversed(num_bytes))


class SolanaTradingWallet:
    def __init__(self, private_key: ed25519.Ed25519PrivateKey):
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self._raw_pub = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self._raw_priv = self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.pubkey_b58 = b58encode(self._raw_pub)

    @classmethod
    def generate(cls) -> "SolanaTradingWallet":
        """Generates a cryptographically secure fresh Ed25519 keypair."""
        priv = ed25519.Ed25519PrivateKey.generate()
        return cls(priv)

    @classmethod
    def from_bytes(cls, raw_bytes: bytes) -> "SolanaTradingWallet":
        """Initializes from 32-byte seed or 64-byte keypair bytes."""
        if len(raw_bytes) == 64:
            seed = raw_bytes[:32]
        elif len(raw_bytes) == 32:
            seed = raw_bytes
        else:
            raise ValueError(f"Expected 32 or 64 bytes for keypair, got {len(raw_bytes)}")
        priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        return cls(priv)

    @classmethod
    def from_file(cls, path: Path | str) -> "SolanaTradingWallet":
        """Loads keypair from standard Solana CLI JSON format [u8; 64]."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Keypair file not found at {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or len(data) not in (32, 64):
            raise ValueError(f"Invalid Solana keypair JSON at {p}. Must be a list of 32 or 64 integers.")
        raw_bytes = bytes(data)
        return cls.from_bytes(raw_bytes)

    def save_to_file(self, path: Path | str, overwrite: bool = False) -> Path:
        """Saves keypair to standard Solana CLI JSON format [u8; 64] with restrictive permissions."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and not overwrite:
            raise FileExistsError(f"File {p} already exists. Pass overwrite=True to replace.")

        keypair_bytes = list(self._raw_priv + self._raw_pub)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(keypair_bytes, f)

        # Set restrictive permissions on POSIX
        if os.name != "nt":
            os.chmod(p, 0o600)
        return p

    def sign_message(self, message: bytes) -> bytes:
        """Signs an arbitrary message using Ed25519."""
        return self._private_key.sign(message)

    def get_public_address(self) -> str:
        """Returns the public Base58 Solana address."""
        return self.pubkey_b58

    def get_balances(self, rpc_urls: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Queries live SOL, USDC, BONK, and JUP balances via Solana JSON-RPC with multi-endpoint failover.
        """
        import httpx

        if not rpc_urls:
            try:
                cfg = load_payment_config()
                endpoints: List[str] = []
                if cfg.get("rpc_url"):
                    endpoints.append(cfg["rpc_url"])
                for fb in cfg.get("fallback_rpc_urls", []):
                    if fb not in endpoints:
                        endpoints.append(fb)
                for ep in cfg.get("rpc_endpoints", []):
                    if ep not in endpoints:
                        endpoints.append(ep)
                rpc_urls = endpoints or ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"]
            except Exception:
                rpc_urls = ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"]

        last_error = None
        sol_balance = 0.0
        usdc_balance = 0.0
        bonk_balance = 0.0
        jup_balance = 0.0
        success = False

        for rpc in rpc_urls:
            try:
                # 1. Fetch SOL Balance
                req_sol = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBalance",
                    "params": [self.pubkey_b58, {"commitment": "confirmed"}],
                }
                resp = httpx.post(rpc, json=req_sol, timeout=6.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if "result" in data and "value" in data["result"]:
                        lamports = data["result"]["value"]
                        sol_balance = lamports / 1_000_000_000.0

                # 2. Fetch all SPL Token Accounts in one RPC call
                req_spl = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        self.pubkey_b58,
                        {"programId": SPL_TOKEN_PROGRAM_ID},
                        {"encoding": "jsonParsed", "commitment": "confirmed"},
                    ],
                }
                resp_spl = httpx.post(rpc, json=req_spl, timeout=6.0)
                if resp_spl.status_code == 200:
                    data_spl = resp_spl.json()
                    accounts = data_spl.get("result", {}).get("value", [])
                    for acc in accounts:
                        info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                        mint = info.get("mint")
                        ui_amt = float(info.get("tokenAmount", {}).get("uiAmount") or 0.0)
                        if mint == CANONICAL_USDC_MINT:
                            usdc_balance += ui_amt
                        elif mint == BONK_MINT:
                            bonk_balance += ui_amt
                        elif mint == JUP_MINT:
                            jup_balance += ui_amt

                success = True
                break
            except Exception as e:
                last_error = str(e)
                continue

        return {
            "address": self.pubkey_b58,
            "sol": round(sol_balance, 6),
            "usdc": round(usdc_balance, 4),
            "bonk": round(bonk_balance, 2),
            "jup": round(jup_balance, 6),
            "success": success,
            "error": None if success else last_error,
        }


def get_or_create_trading_wallet(path: Path = DEFAULT_WALLET_FILE) -> Tuple[SolanaTradingWallet, bool]:
    """
    Retrieves existing trading wallet or creates a fresh secure keypair if none exists.
    Returns (wallet, is_newly_created).
    """
    if path.is_file():
        return SolanaTradingWallet.from_file(path), False
    wallet = SolanaTradingWallet.generate()
    wallet.save_to_file(path)
    return wallet, True


if __name__ == "__main__":
    wallet, is_created = get_or_create_trading_wallet()
    action_str = "CREATED NEW" if is_created else "LOADED EXISTING"
    print(f"[Moltbook Alpha] {action_str} Solana Trading Wallet:")
    print(f"  Public Address: {wallet.get_public_address()}")
    print(f"  Keypair File:   {DEFAULT_WALLET_FILE}")

    balances = wallet.get_balances()
    print("  Live Balances:")
    print(f"    SOL:  {balances['sol']} SOL")
    print(f"    USDC: ${balances['usdc']} USDC")
    print(f"    BONK: {balances['bonk']:,.2f} BONK")
    print(f"    JUP:  {balances['jup']} JUP")
