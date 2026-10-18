"""
Centralized Configuration for Moltbook Alpha API.
Provides cross-platform path resolution, environment variable management,
and fail-safe payment configuration loading.
"""

import os
import json
import re
import secrets
from pathlib import Path
from typing import Dict, Any

# Detect repository root portably across Windows and Linux
BASE_DIR = Path(__file__).resolve().parent

# Optional .env loading
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

APP_ENV = os.getenv("APP_ENV", "development").lower()


def _resolve_data_dir() -> Path:
    env_dir = os.getenv("MOLTBOOK_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    # On Linux production server, check standard system data directory
    sys_path = Path("/var/lib/moltbook-alpha")
    if sys_path.is_dir() and os.name != "nt":
        return sys_path
    return (BASE_DIR / "data").resolve()


DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "moltbook.db"
REPORTS_DIR = Path(os.getenv("MOLTBOOK_REPORTS_DIR", str(BASE_DIR / "reports"))).resolve()
INDEX_HTML_PATH = BASE_DIR / "index.html"
PAYMENT_CONFIG_PATH = BASE_DIR / "payment_config.json"

# Solana Mainnet Canonical USDC Mint (6 decimals)
CANONICAL_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6
SOL_DECIMALS = 9
LAMPORTS_PER_SOL = 1_000_000_000

# Base58 regex pattern (Solana addresses and signatures)
BASE58_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")

# Base58 alphabet and encoder for Solana Pay references
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(data: bytes) -> str:
    """Encodes arbitrary bytes into a standard Base58 string (Bitcoin/Solana alphabet)."""
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    num = int.from_bytes(data, "big")
    chars = []
    while num > 0:
        num, rem = divmod(num, 58)
        chars.append(B58_ALPHABET[rem])
    return ("1" * leading_zeros) + "".join(reversed(chars))


def generate_solana_reference() -> str:
    """Generates a cryptographically random Base58 public key for Solana Pay reference binding."""
    return b58encode(secrets.token_bytes(32))


# Solana Cluster Genesis Hashes
SOLANA_MAINNET_GENESIS_HASH = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
SOLANA_DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
SOLANA_TESTNET_GENESIS_HASH = "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY"

CLUSTER_GENESIS_HASHES: Dict[str, str] = {
    "mainnet-beta": SOLANA_MAINNET_GENESIS_HASH,
    "devnet": SOLANA_DEVNET_GENESIS_HASH,
    "testnet": SOLANA_TESTNET_GENESIS_HASH,
}

# Timing & Age Limits (seconds)
DEFAULT_MAX_TX_AGE_SECONDS = 1800  # 30 minutes
DEFAULT_INVOICE_TTL_SECONDS = 1800  # 30 minutes

# Webhook authentication secret for push-based settlement (e.g. Shyft / Helius webhooks)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "moltbook_webhook_secret_dev")

# Default production-safe rates (USD values converted to integer micro-units)
DEFAULT_RATES: Dict[str, Dict[str, Any]] = {
    "tier_starter": {
        "usd": 1.0,
        "credits": 50,
        "usdc_units": 1_000_000,
        "sol_lamports": 5_000_000,  # ~0.005 SOL
    },
    "tier_pro": {
        "usd": 5.0,
        "credits": 300,
        "usdc_units": 5_000_000,
        "sol_lamports": 25_000_000,  # ~0.025 SOL
    },
    "tier_unlimited": {
        "usd": 20.0,
        "credits": 999999,
        "usdc_units": 20_000_000,
        "sol_lamports": 100_000_000,  # ~0.100 SOL
    },
}


class ConfigError(Exception):
    """Raised when configuration is invalid or missing required production settings."""
    pass


def load_payment_config() -> Dict[str, Any]:
    """
    Loads payment configuration.
    Ensures treasury wallet is valid and never silently replaces a configured
    treasury wallet with an unknown placeholder.
    """
    config_data: Dict[str, Any] = {}
    if PAYMENT_CONFIG_PATH.exists():
        try:
            with open(PAYMENT_CONFIG_PATH, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            raise ConfigError(f"Failed to parse {PAYMENT_CONFIG_PATH}: {e}") from e

    treasury_wallet = os.getenv(
        "SOLANA_TREASURY_WALLET",
        config_data.get("solana_treasury_wallet", "DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC")
    ).strip()

    if not treasury_wallet:
        raise ConfigError("SOLANA_TREASURY_WALLET must be configured.")

    if not BASE58_PATTERN.match(treasury_wallet) or not (32 <= len(treasury_wallet) <= 44):
        raise ConfigError(f"Invalid Solana treasury wallet address: {treasury_wallet}")

    rpc_url = os.getenv(
        "SOLANA_RPC_URL",
        config_data.get("rpc_url", "https://api.mainnet-beta.solana.com")
    ).strip()

    # Load fallback RPC endpoints from env or config file
    fallback_env = os.getenv("SOLANA_RPC_FALLBACKS", "")
    if fallback_env:
        raw_fallbacks = [u.strip() for u in fallback_env.split(",") if u.strip()]
    else:
        raw_fallbacks = config_data.get(
            "fallback_rpc_urls",
            ["https://solana-rpc.publicnode.com"]
        )

    # Deduplicate endpoints preserving order
    rpc_endpoints = []
    for u in [rpc_url] + raw_fallbacks:
        if u and u not in rpc_endpoints:
            rpc_endpoints.append(u)

    if not rpc_endpoints:
        rpc_endpoints = ["https://api.mainnet-beta.solana.com"]

    # Load and normalize rates with integer units
    raw_rates = config_data.get("rates", DEFAULT_RATES)
    rates: Dict[str, Dict[str, Any]] = {}
    for tier, r in raw_rates.items():
        usd_val = float(r.get("usd", 0.0))
        rates[tier] = {
            "usd": usd_val,
            "credits": int(r.get("credits", 0)),
            "usdc_units": int(r.get("usdc_units", round(usd_val * (10 ** USDC_DECIMALS)))),
            "sol_lamports": int(r.get("sol_lamports", round(usd_val * 5_000_000))),
        }

    cluster = os.getenv("SOLANA_CLUSTER", config_data.get("cluster", "mainnet-beta")).strip()
    max_age = int(os.getenv("SOLANA_MAX_TX_AGE_SECONDS", str(config_data.get("max_age_seconds", DEFAULT_MAX_TX_AGE_SECONDS))))
    invoice_ttl = int(os.getenv("SOLANA_INVOICE_TTL_SECONDS", str(config_data.get("invoice_ttl_seconds", DEFAULT_INVOICE_TTL_SECONDS))))

    return {
        "solana_treasury_wallet": treasury_wallet,
        "rpc_url": rpc_endpoints[0],
        "rpc_endpoints": rpc_endpoints,
        "rates": rates,
        "cluster": cluster,
        "max_age_seconds": max_age,
        "invoice_ttl_seconds": invoice_ttl,
    }


def is_demo_keys_enabled() -> bool:
    """Returns True only if demo keys are explicitly enabled via environment variable."""
    val = os.getenv("ENABLE_DEMO_KEYS", "").lower().strip()
    return val in ("true", "1", "yes")


def get_trusted_proxies() -> list[str]:
    """
    Returns list of trusted proxy IP networks/addresses from TRUSTED_PROXIES env var.
    Defaults to empty list in production (fail-closed: no proxies trusted unless explicitly configured).
    In testing/development environments, loopback proxies ('testclient', '127.0.0.1', '::1') are trusted.
    """
    raw = os.getenv("TRUSTED_PROXIES", "").strip()
    if raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    if os.getenv("APP_ENV", "development").lower() != "production":
        return ["testclient", "127.0.0.1", "::1"]
    return []
