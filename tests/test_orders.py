"""
Unit tests for bot.orders (OrderManager + OrderResult + precision rounding)

All Binance API calls are mocked — no network access required.
Tests verify:
  - Correct payload structure for MARKET vs LIMIT
  - Decimal-safe precision rounding for quantity and price
  - timeInForce="GTC" is always present in LIMIT payloads
  - price is never present in MARKET payloads
  - OrderResult is correctly mapped from raw API response
"""

from __future__ import annotations

import pytest

from bot.orders import OrderManager, OrderResult, _round_to_step


# ---------------------------------------------------------------------------
# _round_to_step (pure precision helper)
# ---------------------------------------------------------------------------

class TestRoundToStep:
    def test_round_down_quantity(self):
        """Quantity with too many decimals is rounded DOWN, not rounded."""
        assert _round_to_step(0.00123456, "0.001") == "0.001"

    def test_round_down_price(self):
        assert _round_to_step(65432.789, "0.10") == "65432.70"

    def test_exact_step_unchanged(self):
        assert _round_to_step(0.001, "0.001") == "0.001"

    def test_whole_number_step(self):
        assert _round_to_step(12345.9, "1") == "12345"

    def test_large_decimal_step(self):
        """Common BTC mainnet step — 0.00000100."""
        assert _round_to_step(0.00100099, "0.00100000") == "0.00100000"

    def test_no_floating_point_errors(self):
        """Decimal arithmetic must prevent IEEE 754 imprecision."""
        result = _round_to_step(0.3, "0.1")
        # Float 0.3 / 0.1 = 2.9999... in IEEE 754 — Decimal gives 3.0
        assert result == "0.3"


# ---------------------------------------------------------------------------
# OrderResult.from_api_response
# ---------------------------------------------------------------------------

class TestOrderResultMapping:
    def _sample_market_response(self) -> dict:
        return {
            "orderId":      123456789,
            "symbol":       "BTCUSDT",
            "side":         "BUY",
            "type":         "MARKET",
            "status":       "FILLED",
            "origQty":      "0.001",
            "executedQty":  "0.001",
            "avgPrice":     "65000.00",
            "price":        "0",
            "timeInForce":  "GTC",
        }

    def _sample_limit_response(self) -> dict:
        return {
            "orderId":      987654321,
            "symbol":       "ETHUSDT",
            "side":         "SELL",
            "type":         "LIMIT",
            "status":       "NEW",
            "origQty":      "0.5",
            "executedQty":  "0",
            "avgPrice":     "0",
            "price":        "3000.00",
            "timeInForce":  "GTC",
        }

    def test_market_order_mapping(self):
        result = OrderResult.from_api_response(self._sample_market_response())
        assert result.order_id == 123456789
        assert result.symbol == "BTCUSDT"
        assert result.side == "BUY"
        assert result.order_type == "MARKET"
        assert result.status == "FILLED"
        assert result.orig_qty == "0.001"
        assert result.executed_qty == "0.001"
        assert result.avg_price == "65000.00"

    def test_limit_order_mapping(self):
        result = OrderResult.from_api_response(self._sample_limit_response())
        assert result.order_id == 987654321
        assert result.status == "NEW"
        assert result.price == "3000.00"
        assert result.time_in_force == "GTC"

    def test_missing_fields_get_defaults(self):
        """Partial API response should not crash — use default values."""
        result = OrderResult.from_api_response({"orderId": 1})
        assert result.order_id == 1
        assert result.symbol == ""
        assert result.executed_qty == "0"
        assert result.avg_price == ""


# ---------------------------------------------------------------------------
# OrderManager — MARKET orders
# ---------------------------------------------------------------------------

class TestOrderManagerMarket:
    def _make_mock_client(self, mocker, step_size="0.001", order_response=None):
        """Create a mock BinanceFuturesClient with configurable responses."""
        from bot.client import SymbolFilters

        mock_client = mocker.MagicMock()
        mock_client.get_exchange_info.return_value = SymbolFilters(
            step_size=step_size,
            tick_size="0.10",
            min_qty="0.001",
            min_price="0.10",
        )
        mock_client.place_order.return_value = order_response or {
            "orderId": 111,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "status": "FILLED",
            "origQty": "0.001",
            "executedQty": "0.001",
            "avgPrice": "65000.00",
            "price": "0",
            "timeInForce": "GTC",
        }
        return mock_client

    def test_market_order_payload_has_no_price(self, mocker):
        """MARKET order payload must NEVER contain a 'price' key."""
        mock_client = self._make_mock_client(mocker)
        manager = OrderManager(mock_client)
        manager.place_market_order("BTCUSDT", "BUY", 0.001)

        call_args = mock_client.place_order.call_args[0][0]
        assert "price" not in call_args, "MARKET order must not include 'price' in payload"

    def test_market_order_payload_structure(self, mocker):
        mock_client = self._make_mock_client(mocker)
        manager = OrderManager(mock_client)
        manager.place_market_order("BTCUSDT", "BUY", 0.001)

        payload = mock_client.place_order.call_args[0][0]
        assert payload["symbol"] == "BTCUSDT"
        assert payload["side"] == "BUY"
        assert payload["type"] == "MARKET"
        assert "quantity" in payload

    def test_market_quantity_rounded_to_step(self, mocker):
        """Quantity must be rounded down to stepSize before submission."""
        mock_client = self._make_mock_client(mocker, step_size="0.001")
        manager = OrderManager(mock_client)
        manager.place_market_order("BTCUSDT", "BUY", 0.00199)  # Should round to 0.001

        payload = mock_client.place_order.call_args[0][0]
        assert payload["quantity"] == "0.001"

    def test_market_returns_order_result(self, mocker):
        mock_client = self._make_mock_client(mocker)
        manager = OrderManager(mock_client)
        result = manager.place_market_order("BTCUSDT", "BUY", 0.001)

        assert isinstance(result, OrderResult)
        assert result.order_id == 111
        assert result.status == "FILLED"

    def test_exchange_info_called_with_symbol(self, mocker):
        mock_client = self._make_mock_client(mocker)
        manager = OrderManager(mock_client)
        manager.place_market_order("ETHUSDT", "SELL", 0.5)

        mock_client.get_exchange_info.assert_called_once_with("ETHUSDT")


# ---------------------------------------------------------------------------
# OrderManager — LIMIT orders
# ---------------------------------------------------------------------------

class TestOrderManagerLimit:
    def _make_mock_client(self, mocker, step_size="0.001", tick_size="0.10"):
        from bot.client import SymbolFilters

        mock_client = mocker.MagicMock()
        mock_client.get_exchange_info.return_value = SymbolFilters(
            step_size=step_size,
            tick_size=tick_size,
            min_qty="0.001",
            min_price="0.10",
        )
        mock_client.place_order.return_value = {
            "orderId": 222,
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "LIMIT",
            "status": "NEW",
            "origQty": "0.001",
            "executedQty": "0",
            "avgPrice": "0",
            "price": "60000.00",
            "timeInForce": "GTC",
        }
        return mock_client

    def test_limit_payload_contains_time_in_force_gtc(self, mocker):
        """LIMIT orders MUST include timeInForce='GTC' — Binance will reject without it."""
        mock_client = self._make_mock_client(mocker)
        manager = OrderManager(mock_client)
        manager.place_limit_order("BTCUSDT", "SELL", 0.001, 60000.0)

        payload = mock_client.place_order.call_args[0][0]
        assert "timeInForce" in payload, "LIMIT orders must include 'timeInForce'"
        assert payload["timeInForce"] == "GTC", "timeInForce must be 'GTC'"

    def test_limit_payload_contains_price(self, mocker):
        mock_client = self._make_mock_client(mocker)
        manager = OrderManager(mock_client)
        manager.place_limit_order("BTCUSDT", "SELL", 0.001, 60000.0)

        payload = mock_client.place_order.call_args[0][0]
        assert "price" in payload

    def test_limit_price_rounded_to_tick_size(self, mocker):
        mock_client = self._make_mock_client(mocker, tick_size="0.10")
        manager = OrderManager(mock_client)
        manager.place_limit_order("BTCUSDT", "SELL", 0.001, 60000.789)

        payload = mock_client.place_order.call_args[0][0]
        assert payload["price"] == "60000.70"

    def test_limit_quantity_rounded_to_step_size(self, mocker):
        mock_client = self._make_mock_client(mocker, step_size="0.001")
        manager = OrderManager(mock_client)
        manager.place_limit_order("BTCUSDT", "SELL", 0.0019999, 60000.0)

        payload = mock_client.place_order.call_args[0][0]
        assert payload["quantity"] == "0.001"

    def test_limit_payload_structure(self, mocker):
        mock_client = self._make_mock_client(mocker)
        manager = OrderManager(mock_client)
        manager.place_limit_order("BTCUSDT", "SELL", 0.001, 60000.0)

        payload = mock_client.place_order.call_args[0][0]
        assert payload["symbol"] == "BTCUSDT"
        assert payload["side"] == "SELL"
        assert payload["type"] == "LIMIT"

    def test_limit_returns_order_result(self, mocker):
        mock_client = self._make_mock_client(mocker)
        manager = OrderManager(mock_client)
        result = manager.place_limit_order("BTCUSDT", "SELL", 0.001, 60000.0)

        assert isinstance(result, OrderResult)
        assert result.order_id == 222
        assert result.status == "NEW"
