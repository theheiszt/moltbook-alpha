"""
Unit tests for Solana Trading Wallet Setup & Jupiter DEX Client.
(ops/trading/solana_wallet_setup.py & ops/trading/solana_dex_client.py)
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from ops.trading.solana_wallet_setup import (
    SolanaTradingWallet,
    b58decode,
)
from ops.trading.solana_dex_client import SolanaDexClient, TOKEN_MINTS
from ops.trading.quant_trader import QuantTradingEngine
from config import b58encode, BASE58_PATTERN


def test_wallet_generation_and_b58():
    wallet = SolanaTradingWallet.generate()
    addr = wallet.get_public_address()
    assert BASE58_PATTERN.match(addr)
    assert 32 <= len(addr) <= 44

    # Test signature
    sig = wallet.sign_message(b"moltbook-alpha-test-payload")
    assert len(sig) == 64


def test_b58decode_roundtrip():
    payloads = [
        b"\x00\x00\x01\x02\x03\x04test",
        b"solana-mainnet-test",
        bytes([i for i in range(32)]),
    ]
    for p in payloads:
        encoded = b58encode(p)
        decoded = b58decode(encoded)
        assert decoded == p


def test_wallet_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "test_keypair.json"
        wallet = SolanaTradingWallet.generate()
        wallet.save_to_file(key_path)

        loaded = SolanaTradingWallet.from_file(key_path)
        assert loaded.get_public_address() == wallet.get_public_address()


def test_dex_client_token_info_resolution():
    client = SolanaDexClient()
    sol_info = client.resolve_token_info("SOL")
    assert sol_info["decimals"] == 9
    assert sol_info["mint"] == TOKEN_MINTS["SOL"]["mint"]

    usdc_info = client.resolve_token_info("USDC")
    assert usdc_info["decimals"] == 6

    custom_info = client.resolve_token_info("CustomMint11111111111111111111111111111111")
    assert custom_info["mint"] == "CustomMint11111111111111111111111111111111"
    assert custom_info["decimals"] == 6


def test_dex_client_quote_parsing_with_mock():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "inputMint": TOKEN_MINTS["USDC"]["mint"],
        "inAmount": "1000000",
        "outputMint": TOKEN_MINTS["SOL"]["mint"],
        "outAmount": "9800000",
        "priceImpactPct": "0.02",
        "routePlan": [{"swapInfo": {"label": "Orca Whirlpool"}}],
    }

    mock_http = MagicMock()
    mock_http.get.return_value = mock_resp

    client = SolanaDexClient(http_client=mock_http)
    quote = client.get_quote("USDC", "SOL", 1.0)

    assert quote["success"] is True
    assert quote["in_amount"] == 1.0
    assert quote["out_amount"] == 0.0098
    assert quote["price_impact_pct"] == 0.02
    assert "Orca Whirlpool" in quote["route_summary"]


def test_dex_client_rejection_on_excessive_slippage():
    # Mock quote with high price impact (e.g. illiquid pool, 5% impact)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "inputMint": TOKEN_MINTS["USDC"]["mint"],
        "inAmount": "1000000",
        "outputMint": TOKEN_MINTS["SOL"]["mint"],
        "outAmount": "5000000",
        "priceImpactPct": "5.25",  # Over 0.30% cap
        "routePlan": [],
    }

    mock_http = MagicMock()
    mock_http.get.return_value = mock_resp

    client = SolanaDexClient(http_client=mock_http)
    eval_res = client.evaluate_micro_trade("USDC", "SOL", 1.0)

    assert eval_res["is_viable"] is False
    assert eval_res["rejection_reason"] == "FRICTION_OR_PRICE_IMPACT_EXCEEDED"

    sim_res = client.simulate_micro_swap("USDC", "SOL", 1.0)
    assert sim_res["success"] is False


def test_dex_client_simulate_micro_swap_paper_execution():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "inputMint": TOKEN_MINTS["USDC"]["mint"],
        "inAmount": "2000000",
        "outputMint": TOKEN_MINTS["SOL"]["mint"],
        "outAmount": "19600000",
        "priceImpactPct": "0.01",
        "routePlan": [{"swapInfo": {"label": "Raydium CLMM"}}],
    }

    mock_http = MagicMock()
    mock_http.get.return_value = mock_resp

    engine = QuantTradingEngine(initial_capital_usdc=5.0)
    client = SolanaDexClient(quant_engine=engine, http_client=mock_http)

    sim = client.simulate_micro_swap("USDC", "SOL", 2.0)
    assert sim["success"] is True
    assert sim["dry_run"] is True
    assert "SOL" in engine.positions
    assert engine.capital_usdc == 3.0  # $5.00 - $2.00


def test_solana_dex_runner_dry_run():
    from ops.trading.solana_dex_runner import SolanaDexRunner

    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = Path(tmpdir) / "test_runner_wallet.json"
        wallet = SolanaTradingWallet.generate()
        wallet.save_to_file(key_file)

        runner = SolanaDexRunner(wallet_file=key_file)
        status = runner.check_wallet_status()
        assert status["address"] == wallet.get_public_address()

        mock_quote = {
            "success": True,
            "out_amount": 1.02,
            "price_impact_pct": 0.01,
            "route_summary": "Orca",
        }
        runner.dex_client.get_quote = MagicMock(return_value=mock_quote)

        res = runner.execute_swap("SOL", "USDC", 0.01, live_swap=False)
        assert res["success"] is True
        assert res["mode"] == "DRY_RUN"
        assert res["expected_output"] == "1.02 USDC"
