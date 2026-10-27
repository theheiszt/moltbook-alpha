"""
Unit tests for Coinbase Advanced Trade CDP Client (ops/trading/coinbase_client.py).
"""

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
import jwt

from ops.trading.coinbase_client import CoinbaseCdpClient


def create_dummy_cdp_key_file(tmp_path: Path) -> Path:
    priv = ed25519.Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = priv.public_key()
    raw_pub = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    b64_priv = base64.b64encode(raw_priv + raw_pub).decode("utf-8")

    key_data = {
        "id": "test-key-uuid-1234-5678",
        "privateKey": b64_priv,
    }
    key_file = tmp_path / "test_cdp_key.json"
    with open(key_file, "w", encoding="utf-8") as f:
        json.dump(key_data, f)
    return key_file


def test_coinbase_client_jwt_generation():
    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = create_dummy_cdp_key_file(Path(tmpdir))
        client = CoinbaseCdpClient(key_path=key_file)

        token = client.generate_jwt("GET", "/api/v3/brokerage/accounts")
        assert token is not None

        # Verify decoded payload
        unverified_claims = jwt.decode(token, options={"verify_signature": False})
        assert unverified_claims["sub"] == "test-key-uuid-1234-5678"
        assert unverified_claims["iss"] == "cdp"
        assert "GET api.coinbase.com/api/v3/brokerage/accounts" in unverified_claims["uri"]
        assert unverified_claims["exp"] > unverified_claims["nbf"]


def test_coinbase_client_get_balances_summary_mocked():
    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = create_dummy_cdp_key_file(Path(tmpdir))
        client = CoinbaseCdpClient(key_path=key_file)

        mock_accounts = [
            {"currency": "USDC", "available_balance": {"value": "2.7379"}},
            {"currency": "SOL", "available_balance": {"value": "0.0"}},
            {"currency": "LTC", "available_balance": {"value": "0.0067"}},
        ]
        client.get_accounts = MagicMock(return_value=mock_accounts)

        balances = client.get_balances_summary()
        assert balances["USDC"] == 2.7379
        assert balances["LTC"] == 0.0067
        assert "SOL" not in balances  # Zero balance excluded


def test_coinbase_client_get_orderbook_mocked():
    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = create_dummy_cdp_key_file(Path(tmpdir))
        client = CoinbaseCdpClient(key_path=key_file)

        mock_book = {
            "pricebook": {
                "product_id": "SOL-USDC",
                "bids": [{"price": "101.96", "size": "61.64"}],
                "asks": [{"price": "101.98", "size": "138.84"}],
            }
        }
        client._request = MagicMock(return_value=mock_book)

        book = client.get_orderbook("SOL-USDC", limit=1)
        bids = book["pricebook"]["bids"]
        assert bids[0]["price"] == "101.96"


def test_coinbase_quant_runner_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        from ops.trading.coinbase_quant_runner import CoinbaseQuantRunner
        from ops.trading.quant_trader import QuantTradingEngine

        key_file = create_dummy_cdp_key_file(Path(tmpdir))
        client = CoinbaseCdpClient(key_path=key_file)

        client.get_balances_summary = MagicMock(return_value={"USDC": 2.73, "SOL": 0.0})
        client.get_orderbook = MagicMock(return_value={
            "pricebook": {
                "bids": [{"price": "100.00", "size": "10.0"}],
                "asks": [{"price": "100.02", "size": "10.0"}],
            }
        })

        engine = QuantTradingEngine()
        runner = CoinbaseQuantRunner(client=client, engine=engine)

        res = runner.run_strategy_cycle(product_id="SOL-USDC", trade_size_usd=1.0, live_trade=False)
        assert res["success"] is True
        assert res["live_trade"] is False
        assert res["order"]["dry_run"] is True
        assert res["order"]["limit_price"] == 100.00
        assert res["order"]["base_size"] == 0.01  # $1 / 100
        assert res["order"]["post_only"] is True
