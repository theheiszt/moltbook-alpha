"""
Unit tests for Scheduled-Task Resilience, Cadence Advancement, and Circuit Breakers.
"""

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from ops.trading.scalper_bot import SpreadScalperBot


def test_circuit_breaker_trips_after_3_consecutive_failures():
    mock_client = MagicMock()
    mock_client.list_orders.side_effect = RuntimeError("Coinbase API gateway 502 connection drop")

    with tempfile.TemporaryDirectory() as tmpdir:
        trades_log = Path(tmpdir) / "trades.json"
        bot = SpreadScalperBot(client=mock_client, max_consecutive_failures=3, trades_log_path=trades_log)

        # Iteration 1: Failure 1
        res1 = bot.step(interval_seconds=15)
        assert res1["state"] == "ITERATION_FAILED"
        assert res1["consecutive_failures"] == 1
        assert not bot.circuit_broken

        # Iteration 2: Failure 2
        res2 = bot.step(interval_seconds=15)
        assert res2["state"] == "ITERATION_FAILED"
        assert res2["consecutive_failures"] == 2
        assert not bot.circuit_broken

        # Iteration 3: Failure 3 -> Trips Circuit Breaker
        res3 = bot.step(interval_seconds=15)
        assert res3["state"] == "CIRCUIT_BROKEN"
        assert res3["consecutive_failures"] == 3
        assert bot.circuit_broken
        assert "Exceeded max consecutive failures" in bot.circuit_broken_reason

        # Iteration 4: Fast-fails immediately without hitting client again
        mock_client.list_orders.reset_mock()
        res4 = bot.step(interval_seconds=15)
        assert res4["state"] == "CIRCUIT_BROKEN"
        mock_client.list_orders.assert_not_called()

        # Audit event recorded in trades log
        assert trades_log.exists()
        with open(trades_log, "r", encoding="utf-8") as f:
            events = json.load(f)
        assert any(e.get("event") == "CIRCUIT_BREAKER_TRIPPED" for e in events)


def test_circuit_breaker_resets_on_success():
    mock_client = MagicMock()
    # Fails twice, then succeeds
    mock_client.list_orders.side_effect = [
        RuntimeError("Transient error 1"),
        RuntimeError("Transient error 2"),
        [],  # No open orders
    ]
    mock_client.get_product.return_value = {"price": "100.00"}
    mock_client.get_balances_summary.return_value = {"SOL": 0.05, "USDC": 0.0}
    mock_client.create_limit_order.return_value = {"success": True}

    with tempfile.TemporaryDirectory() as tmpdir:
        trades_log = Path(tmpdir) / "trades.json"
        bot = SpreadScalperBot(client=mock_client, max_consecutive_failures=3, trades_log_path=trades_log)

        res1 = bot.step(interval_seconds=15)
        assert res1["state"] == "ITERATION_FAILED"
        assert bot.consecutive_failures == 1

        res2 = bot.step(interval_seconds=15)
        assert res2["state"] == "ITERATION_FAILED"
        assert bot.consecutive_failures == 2

        res3 = bot.step(interval_seconds=15)
        assert res3["state"] == "PLACED_PROFIT_TAKE_SELL"
        # Reset to 0 on success
        assert bot.consecutive_failures == 0
        assert not bot.circuit_broken


def test_circuit_breaker_manual_reset():
    mock_client = MagicMock()
    mock_client.list_orders.side_effect = RuntimeError("Fatal error")

    with tempfile.TemporaryDirectory() as tmpdir:
        trades_log = Path(tmpdir) / "trades.json"
        bot = SpreadScalperBot(client=mock_client, max_consecutive_failures=1, trades_log_path=trades_log)

        res1 = bot.step(interval_seconds=15)
        assert res1["state"] == "CIRCUIT_BROKEN"
        assert bot.circuit_broken

        bot.reset_circuit_breaker()
        assert not bot.circuit_broken
        assert bot.consecutive_failures == 0
        assert bot.circuit_broken_reason is None


def test_guaranteed_cadence_advancement():
    mock_client = MagicMock()
    mock_client.list_orders.side_effect = RuntimeError("Failure")

    with tempfile.TemporaryDirectory() as tmpdir:
        trades_log = Path(tmpdir) / "trades.json"
        bot = SpreadScalperBot(client=mock_client, trades_log_path=trades_log)

        start = time.time()
        bot.step(interval_seconds=30)
        assert bot.next_run_epoch is not None
        assert bot.next_run_epoch >= start + 29.0


def test_daily_spend_cap_enforcement():
    mock_client = MagicMock()
    mock_client.list_orders.return_value = []
    mock_client.get_product.return_value = {"price": "100.00"}
    mock_client.get_balances_summary.return_value = {"SOL": 0.0, "USDC": 10.0}

    with tempfile.TemporaryDirectory() as tmpdir:
        trades_log = Path(tmpdir) / "trades.json"
        # Pre-seed trades log with $148.50 in BUY orders within the last 2 hours
        now_iso = datetime.now(timezone.utc).isoformat()
        preloaded_events = [
            {
                "timestamp": now_iso,
                "event": "PLACED_PASSIVE_BUY",
                "buy_price": 99.00,
                "size": 1.5,  # 99 * 1.5 = $148.50
            }
        ]
        with open(trades_log, "w", encoding="utf-8") as f:
            json.dump(preloaded_events, f)

        # Daily spend cap is $150.00. Current spend = $148.50.
        # An attempted buy of $2.70 would exceed $150.00 ($151.20)
        bot = SpreadScalperBot(
            client=mock_client,
            daily_spend_cap_usd=150.00,
            trades_log_path=trades_log,
        )

        res = bot.step(interval_seconds=15)
        assert res["state"] == "PAUSED_DAILY_SPEND_CAP"
        assert res["rolling_24h_spend_usd"] == 148.50
        assert res["daily_spend_cap_usd"] == 150.00
        mock_client.create_limit_order.assert_not_called()
