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
def _resolve_reports_dir() -> Path:
    env_reports = os.getenv("MOLTBOOK_REPORTS_DIR")
    if env_reports:
        return Path(env_reports).resolve()
    if DATA_DIR != (BASE_DIR / "data").resolve():
        return (DATA_DIR / "reports").resolve()
    return (BASE_DIR / "reports").resolve()


REPORTS_DIR = _resolve_reports_dir()
INDEX_HTML_PATH = BASE_DIR / "index.html"
PAYMENT_CONFIG_PATH = BASE_DIR / "payment_config.json"
WITNESS_KEY_PATH = Path(os.getenv("WITNESS_KEY_PATH", str(DATA_DIR / "witness_ed25519.pem"))).resolve()

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
        "display_name": "Starter",
        "usd": 1.0,
        "credits": 50,
        "validity_days": None,
        "usdc_units": 1_000_000,
        "sol_lamports": 5_000_000,  # ~0.005 SOL
    },
    "tier_pro": {
        "display_name": "Pro",
        "usd": 5.0,
        "credits": 300,
        "validity_days": None,
        "usdc_units": 5_000_000,
        "sol_lamports": 25_000_000,  # ~0.025 SOL
    },
    "tier_unlimited": {
        "display_name": "Premium (10,000 queries / 30 days)",
        "usd": 20.0,
        "credits": 10000,
        "validity_days": 30,
        "usdc_units": 20_000_000,
        "sol_lamports": 100_000_000,  # ~0.100 SOL
    },
    "tier_premium": {
        "display_name": "Premium (10,000 queries / 30 days)",
        "usd": 20.0,
        "credits": 10000,
        "validity_days": 30,
        "usdc_units": 20_000_000,
        "sol_lamports": 100_000_000,  # ~0.100 SOL
    },
}

DEFAULT_TOPUP_PACKAGES: Dict[str, Dict[str, Any]] = {
    "topup_500": {
        "display_name": "Credit Top-Up (500 queries / 90 days)",
        "usd": 8.0,
        "credits": 500,
        "validity_days": 90,
        "usdc_units": 8_000_000,
        "sol_lamports": 40_000_000,
    },
    "topup_1500": {
        "display_name": "Credit Top-Up (1,500 queries / 90 days)",
        "usd": 20.0,
        "credits": 1500,
        "validity_days": 90,
        "usdc_units": 20_000_000,
        "sol_lamports": 100_000_000,
    },
    "topup_5000": {
        "display_name": "Credit Top-Up (5,000 queries / 90 days)",
        "usd": 50.0,
        "credits": 5000,
        "validity_days": 90,
        "usdc_units": 50_000_000,
        "sol_lamports": 250_000_000,
    },
}


# API Rate Limiting & Concurrency Defaults
DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN = 60
DEFAULT_RATE_LIMIT_BURST_CAPACITY = 5
DEFAULT_RATE_LIMIT_MAX_CONCURRENT = 5
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0

# Usage Warning Thresholds (50%, 80%, 90%, 95%)
DEFAULT_QUOTA_WARNING_THRESHOLDS = (0.50, 0.80, 0.90, 0.95)


def get_rate_limit_config() -> Dict[str, Any]:
    sustained = int(os.getenv("RATE_LIMIT_SUSTAINED_PER_MIN", str(DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN)))
    burst = int(os.getenv("RATE_LIMIT_BURST_CAPACITY", str(DEFAULT_RATE_LIMIT_BURST_CAPACITY)))
    max_concurrent = int(os.getenv("RATE_LIMIT_MAX_CONCURRENT", str(DEFAULT_RATE_LIMIT_MAX_CONCURRENT)))
    timeout = float(os.getenv("REQUEST_TIMEOUT_SECONDS", str(DEFAULT_REQUEST_TIMEOUT_SECONDS)))
    return {
        "sustained_per_min": sustained,
        "burst_capacity": burst,
        "max_concurrent": max_concurrent,
        "request_timeout_seconds": timeout,
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
        config_data.get("solana_treasury_wallet", "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx")
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
        validity = r.get("validity_days")
        display_name = r.get("display_name", tier.replace("tier_", "").capitalize())
        rates[tier] = {
            "display_name": display_name,
            "usd": usd_val,
            "credits": int(r.get("credits", 0)),
            "validity_days": int(validity) if validity is not None else None,
            "usdc_units": int(r.get("usdc_units", round(usd_val * (10 ** USDC_DECIMALS)))),
            "sol_lamports": int(r.get("sol_lamports", round(usd_val * 5_000_000))),
        }

    # Load and normalize top-up packages (configurable, default 90 days validity)
    raw_topups = config_data.get("topup_packages", DEFAULT_TOPUP_PACKAGES)
    env_topups = os.getenv("TOPUP_PACKAGES")
    if env_topups:
        try:
            raw_topups = json.loads(env_topups)
        except Exception:
            pass

    topup_packages: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_topups, dict):
        for pkg_id, p in raw_topups.items():
            if not isinstance(p, dict):
                continue
            usd_val = float(p.get("usd", 0.0))
            credits_val = int(p.get("credits", 0))
            validity_days = int(p.get("validity_days", 90))
            topup_packages[pkg_id] = {
                "display_name": p.get("display_name", f"Top-up ({credits_val} credits)"),
                "usd": usd_val,
                "credits": credits_val,
                "validity_days": validity_days,
                "usdc_units": int(p.get("usdc_units", round(usd_val * (10 ** USDC_DECIMALS)))),
                "sol_lamports": int(p.get("sol_lamports", round(usd_val * 5_000_000))),
            }

    cluster = os.getenv("SOLANA_CLUSTER", config_data.get("cluster", "mainnet-beta")).strip()
    max_age = int(os.getenv("SOLANA_MAX_TX_AGE_SECONDS", str(config_data.get("max_age_seconds", DEFAULT_MAX_TX_AGE_SECONDS))))
    invoice_ttl = int(os.getenv("SOLANA_INVOICE_TTL_SECONDS", str(config_data.get("invoice_ttl_seconds", DEFAULT_INVOICE_TTL_SECONDS))))

    return {
        "solana_treasury_wallet": treasury_wallet,
        "rpc_url": rpc_endpoints[0],
        "rpc_endpoints": rpc_endpoints,
        "rates": rates,
        "topup_packages": topup_packages,
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
