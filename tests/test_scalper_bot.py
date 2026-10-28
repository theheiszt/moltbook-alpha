"""
Unit tests for Autonomous CLOB Spread Scalper Bot (ops/trading/scalper_bot.py).
"""

from unittest.mock import MagicMock
from ops.trading.scalper_bot import SpreadScalperBot


def test_scalper_bot_detects_open_order():
    mock_client = MagicMock()
    mock_client.list_orders.return_value = [
        {
            "order_id": "test-order-1234",
            "side": "SELL",
            "status": "OPEN",
            "order_configuration": {
                "limit_limit_gtc": {
                    "limit_price": "102.80",
                    "base_size": "0.02652520",
                }
            },
        }
    ]
    mock_client.get_product.return_value = {"price": "101.65"}
    mock_client.get_balances_summary.return_value = {"SOL": 0.0, "USDC": 0.03}

    bot = SpreadScalperBot(client=mock_client)
    res = bot.run_single_iteration()

    assert res["state"] == "WAITING_FOR_FILL_SELL"
    assert res["order_id"] == "test-order-1234"
    assert res["target_price"] == 102.80
    assert res["distance_to_target_pct"] > 0.50


def test_scalper_bot_cycles_to_sell_when_holding_sol():
    mock_client = MagicMock()
    mock_client.list_orders.return_value = []
    mock_client.get_product.return_value = {"price": "100.00"}
    mock_client.get_balances_summary.return_value = {"SOL": 0.05, "USDC": 0.01}
    mock_client.create_limit_order.return_value = {"success": True, "dry_run": False}

    bot = SpreadScalperBot(client=mock_client, profit_target_pct=0.010)
    res = bot.run_single_iteration()

    assert res["state"] == "PLACED_PROFIT_TAKE_SELL"
    assert res["sell_price"] == 101.00  # 1% above $100
    mock_client.create_limit_order.assert_called_once()


def test_scalper_bot_cycles_to_buy_when_holding_usdc():
    mock_client = MagicMock()
    mock_client.list_orders.return_value = []
    mock_client.get_product.return_value = {"price": "100.00"}
    mock_client.get_balances_summary.return_value = {"SOL": 0.0, "USDC": 2.50}
    mock_client.get_orderbook.return_value = {
        "pricebook": {"bids": [{"price": "99.95", "size": "10.0"}]}
    }
    mock_client.create_limit_order.return_value = {"success": True, "dry_run": False}

    bot = SpreadScalperBot(client=mock_client)
    res = bot.run_single_iteration()

    assert res["state"] == "PLACED_PASSIVE_BUY"
    assert res["buy_price"] == 99.95
    mock_client.create_limit_order.assert_called_once()
