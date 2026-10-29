"""
Unit tests for Autonomous CLOB Spread Scalper Bot (ops/trading/scalper_bot.py).
"""

import tempfile
from pathlib import Path
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

    with tempfile.TemporaryDirectory() as tmpdir:
        bot = SpreadScalperBot(
            client=mock_client,
            profit_target_pct=0.010,
            trades_log_path=Path(tmpdir) / "trades.json",
        )
        res = bot.run_single_iteration()

        assert res["state"] == "PLACED_PROFIT_TAKE_SELL"
        assert res["sell_price"] == 101.00  # 1% above $100
        assert res["current_price"] == 100.00
        assert res["sol_balance"] == 0.05
        mock_client.create_limit_order.assert_called_once()


def test_scalper_bot_enforces_entry_cost_basis_floor_on_sell():
    """
    If SOL dips to $95.00 after a $101.79 BUY fill, the bot must anchor its
    profit-take SELL to $101.79 * 1.01 ($102.81) rather than selling at a loss ($95.95).
    """
    mock_client = MagicMock()

    def side_effect_list_orders(product_id, order_status):
        if order_status == ["OPEN"]:
            return []
        if order_status == ["FILLED"]:
            return [{"side": "BUY", "average_filled_price": "101.79"}]
        return []

    mock_client.list_orders.side_effect = side_effect_list_orders
    mock_client.get_product.return_value = {"price": "95.00"}
    mock_client.get_balances_summary.return_value = {"SOL": 0.0265252, "USDC": 0.03}
    mock_client.create_limit_order.return_value = {"success": True, "dry_run": True}

    with tempfile.TemporaryDirectory() as tmpdir:
        bot = SpreadScalperBot(
            client=mock_client,
            profit_target_pct=0.010,
            trades_log_path=Path(tmpdir) / "trades.json",
        )
        res = bot.run_single_iteration(dry_run=True)

        assert res["state"] == "PLACED_PROFIT_TAKE_SELL"
        assert res["entry_anchor_price"] == 101.79
        assert res["sell_price"] == 102.81


def test_scalper_bot_cancels_stale_passive_buy():
    """
    If an open passive BUY order drifts >0.5% below current market price,
    the bot cancels it so the next cycle can re-peg to the top of the book.
    """
    mock_client = MagicMock()
    mock_client.list_orders.return_value = [
        {
            "order_id": "stale-buy-999",
            "side": "BUY",
            "status": "OPEN",
            "order_configuration": {
                "limit_limit_gtc": {
                    "limit_price": "98.00",
                    "base_size": "0.025",
                }
            },
        }
    ]
    mock_client.get_product.return_value = {"price": "100.00"}
    mock_client.get_balances_summary.return_value = {"SOL": 0.0, "USDC": 2.50}
    mock_client.cancel_orders.return_value = {"results": [{"success": True}]}

    with tempfile.TemporaryDirectory() as tmpdir:
        bot = SpreadScalperBot(
            client=mock_client,
            max_bid_drift_pct=0.005,
            trades_log_path=Path(tmpdir) / "trades.json",
        )
        res = bot.run_single_iteration(dry_run=False)

        assert res["state"] == "CANCELLED_STALE_BUY"
        assert res["order_id"] == "stale-buy-999"
        mock_client.cancel_orders.assert_called_once_with(["stale-buy-999"])


def test_scalper_bot_cycles_to_buy_when_holding_usdc():
    mock_client = MagicMock()
    mock_client.list_orders.return_value = []
    mock_client.get_product.return_value = {"price": "100.00"}
    mock_client.get_balances_summary.return_value = {"SOL": 0.0, "USDC": 2.50}
    mock_client.get_orderbook.return_value = {
        "pricebook": {
            "bids": [{"price": "99.95", "size": "15.0"}],
            "asks": [{"price": "100.05", "size": "10.0"}],
        }
    }
    mock_client.create_limit_order.return_value = {"success": True, "dry_run": False}

    with tempfile.TemporaryDirectory() as tmpdir:
        bot = SpreadScalperBot(
            client=mock_client,
            trades_log_path=Path(tmpdir) / "trades.json",
        )
        res = bot.run_single_iteration()

        assert res["state"] == "PLACED_PASSIVE_BUY"
        assert res["buy_price"] == 99.95
        assert res["current_price"] == 100.00
        mock_client.create_limit_order.assert_called_once()
