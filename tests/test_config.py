"""
Tests for configuration parsing, treasury validation, and cross-platform path resolution.
"""

from pathlib import Path
import pytest
from config import (
    load_payment_config,
    ConfigError,
    BASE_DIR,
    DATA_DIR,
    REPORTS_DIR,
    CANONICAL_USDC_MINT,
    is_demo_keys_enabled,
)


def test_paths_are_portable_and_resolved():
    assert isinstance(BASE_DIR, Path)
    assert isinstance(DATA_DIR, Path)
    assert isinstance(REPORTS_DIR, Path)
    assert BASE_DIR.is_absolute()
    assert DATA_DIR.is_absolute()


def test_payment_config_loads_canonical_rates():
    cfg = load_payment_config()
    assert "solana_treasury_wallet" in cfg
    assert len(cfg["solana_treasury_wallet"]) >= 32
    assert "rates" in cfg

    rates = cfg["rates"]
    assert "tier_starter" in rates
    assert rates["tier_starter"]["usdc_units"] == 1_000_000
    assert rates["tier_pro"]["usdc_units"] == 5_000_000
    assert rates["tier_unlimited"]["usdc_units"] == 20_000_000


def test_invalid_treasury_wallet_raises_config_error(monkeypatch):
    monkeypatch.setenv("SOLANA_TREASURY_WALLET", "invalid_wallet_not_base58_!@#$")
    with pytest.raises(ConfigError) as exc_info:
        load_payment_config()
    assert "Invalid Solana treasury wallet" in str(exc_info.value)


def test_empty_treasury_wallet_raises_config_error(monkeypatch):
    monkeypatch.setenv("SOLANA_TREASURY_WALLET", "")
    with pytest.raises(ConfigError):
        load_payment_config()


def test_demo_keys_enabled_flag(monkeypatch):
    monkeypatch.setenv("ENABLE_DEMO_KEYS", "true")
    assert is_demo_keys_enabled() is True

    monkeypatch.setenv("ENABLE_DEMO_KEYS", "false")
    assert is_demo_keys_enabled() is False

    monkeypatch.setenv("ENABLE_DEMO_KEYS", "1")
    assert is_demo_keys_enabled() is True

    monkeypatch.delenv("ENABLE_DEMO_KEYS", raising=False)
    assert is_demo_keys_enabled() is False


def test_canonical_usdc_mint_matches_mainnet():
    assert CANONICAL_USDC_MINT == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
