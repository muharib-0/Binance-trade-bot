"""
OrderManager — Business Logic Layer

Orchestrates the full order lifecycle for MARKET, LIMIT, and STOP_LIMIT orders:
  1. Fetch symbol exchange filters from Binance (stepSize, tickSize)
  2. Round quantity/price to the correct precision using Decimal arithmetic
  3. Build the correct order payload per order type
  4. Submit to Binance via BinanceFuturesClient
  5. Return a clean, typed OrderResult

Binance Futures API order type mapping:
  MARKET     -> type="MARKET"  (our name = Binance name)
  LIMIT      -> type="LIMIT"   (our name = Binance name)
  STOP_LIMIT -> type="STOP"    (Binance Futures uses STOP for stop-limit;
                                STOP_LIMIT is a Spot-only type)

This layer knows about order logic. It knows nothing about HTTP, CLI, or logging format.

Usage:
    client = BinanceFuturesClient()
    manager = OrderManager(client)
    result = manager.place_market_order("BTCUSDT", "BUY", 0.001)
    result = manager.place_limit_order("BTCUSDT", "SELL", 0.001, 60000.0)
    result = manager.place_stop_limit_order("BTCUSDT", "SELL", 0.001, 60000.0, stop_price=58000.0)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from bot.client import BinanceFuturesClient
from bot.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class OrderResult:
    """
    Clean, typed representation of a Binance order response.

    Only contains the fields that matter for output — not the full
    raw response (which has 20+ fields most users never need).

    Attributes:
        order_id:     Unique Binance order ID.
        symbol:       Trading symbol (e.g., "BTCUSDT").
        side:         "BUY" or "SELL".
        order_type:   "MARKET", "LIMIT", or "STOP" (Binance Futures name for Stop-Limit).
        status:       Order status (e.g., "NEW", "FILLED", "PARTIALLY_FILLED").
        orig_qty:     Original requested quantity (string, as returned by Binance).
        executed_qty: Quantity that has been filled so far.
        avg_price:    Average fill price (empty string if not yet filled).
        price:        Limit price (empty for MARKET orders).
        stop_price:   Trigger price (set for STOP orders, empty for MARKET/LIMIT).
        time_in_force: "GTC" for LIMIT/STOP_LIMIT, empty for MARKET.
    """
    order_id: int
    symbol: str
    side: str
    order_type: str
    status: str
    orig_qty: str
    executed_qty: str
    avg_price: str
    price: str
    stop_price: str
    time_in_force: str

    @classmethod
    def from_api_response(cls, data: dict) -> "OrderResult":
        """
        Construct an OrderResult from the raw Binance API response dict.

        Args:
            data: Raw dict from client.place_order().

        Returns:
            Populated OrderResult instance.
        """
        return cls(
            order_id      = data.get("orderId", 0),
            symbol        = data.get("symbol", ""),
            side          = data.get("side", ""),
            order_type    = data.get("type", ""),
            status        = data.get("status", ""),
            orig_qty      = data.get("origQty", "0"),
            executed_qty  = data.get("executedQty", "0"),
            avg_price     = data.get("avgPrice", ""),
            price         = data.get("price", ""),
            stop_price    = data.get("stopPrice", ""),
            time_in_force = data.get("timeInForce", ""),
        )


# ---------------------------------------------------------------------------
# Precision helpers
# ---------------------------------------------------------------------------

def _round_to_step(value: float, step: str) -> str:
    """
    Round a float value DOWN to the nearest step increment.

    Uses Python's Decimal module to avoid floating-point arithmetic
    errors (e.g., 0.1 + 0.2 ≠ 0.3 in IEEE 754 floats).

    Args:
        value: The raw quantity or price as a float.
        step:  The exchange-imposed step size as a string (e.g., "0.001").

    Returns:
        String representation of the rounded value, matching step precision.

    Examples:
        _round_to_step(0.00123456, "0.001")  → "0.001"
        _round_to_step(65432.789,  "0.10")   → "65432.70"
    """
    d_value = Decimal(str(value))
    d_step  = Decimal(step)
    rounded = (d_value / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step
    # Quantize to match exact decimal places of the step
    return str(rounded.quantize(d_step))


# ---------------------------------------------------------------------------
# OrderManager
# ---------------------------------------------------------------------------

class OrderManager:
    """
    Orchestrates order placement for all supported order types.

    Accepts a BinanceFuturesClient instance (dependency injection),
    which makes this class fully testable by passing a mock client.

    Args:
        client: Initialised BinanceFuturesClient instance.
    """

    def __init__(self, client: BinanceFuturesClient) -> None:
        self._client = client

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> OrderResult:
        """
        Place a MARKET order — executes immediately at the best available price.

        Key differences from LIMIT:
          - No price field in the payload (Binance rejects it if included)
          - No timeInForce field required

        Args:
            symbol:   Uppercase trading symbol (e.g., "BTCUSDT").
            side:     "BUY" or "SELL".
            quantity: Desired quantity (will be rounded to stepSize).

        Returns:
            OrderResult with the placed order details.
        """
        logger.debug(
            "[ORDER MANAGER] Building MARKET order: symbol=%s side=%s quantity=%s",
            symbol, side, quantity,
        )

        # Fetch exchange filters to ensure quantity meets precision rules
        filters = self._client.get_exchange_info(symbol)
        rounded_qty = _round_to_step(quantity, filters.step_size)

        logger.debug(
            "[PRECISION] quantity: raw=%s → rounded=%s (stepSize=%s)",
            quantity, rounded_qty, filters.step_size,
        )

        payload = {
            "symbol":   symbol,
            "side":     side,
            "type":     "MARKET",
            "quantity": rounded_qty,
            # NOTE: 'price' is intentionally excluded from MARKET orders
        }

        raw_response = self._client.place_order(payload)
        return OrderResult.from_api_response(raw_response)

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
    ) -> OrderResult:
        """
        Place a LIMIT order — rests on the order book until filled or cancelled.

        Key differences from MARKET:
          - Price is required and rounded to tickSize precision
          - timeInForce="GTC" (Good Till Cancelled) is always included
            This is required by Binance for LIMIT orders and is the correct
            default for this use case.

        Args:
            symbol:   Uppercase trading symbol (e.g., "BTCUSDT").
            side:     "BUY" or "SELL".
            quantity: Desired quantity (will be rounded to stepSize).
            price:    Desired limit price (will be rounded to tickSize).

        Returns:
            OrderResult with the placed order details (status will be "NEW"
            if the order is resting on the book).
        """
        logger.debug(
            "[ORDER MANAGER] Building LIMIT order: symbol=%s side=%s quantity=%s price=%s",
            symbol, side, quantity, price,
        )

        # Fetch exchange filters for precision on both quantity and price
        filters = self._client.get_exchange_info(symbol)
        rounded_qty   = _round_to_step(quantity, filters.step_size)
        rounded_price = _round_to_step(price, filters.tick_size)

        logger.debug(
            "[PRECISION] quantity: raw=%s → rounded=%s (stepSize=%s) | "
            "price: raw=%s → rounded=%s (tickSize=%s)",
            quantity, rounded_qty, filters.step_size,
            price, rounded_price, filters.tick_size,
        )

        payload = {
            "symbol":      symbol,
            "side":        side,
            "type":        "LIMIT",
            "quantity":    rounded_qty,
            "price":       rounded_price,
            "timeInForce": "GTC",   # ← Critical: required for all LIMIT orders
        }

        raw_response = self._client.place_order(payload)
        return OrderResult.from_api_response(raw_response)

    def place_stop_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_price: float,
    ) -> OrderResult:
        """
        Place a STOP_LIMIT order on Binance Futures.

        How it works:
          1. When the market price reaches `stop_price` (the trigger),
             Binance automatically places a LIMIT order at `price`.
          2. The limit order then fills if the market moves through `price`.

        Binance API mapping:
          Our type "STOP_LIMIT" → Binance type "STOP"
          (Binance Futures uses "STOP" for stop-limit orders;
           "STOP_LIMIT" is a Spot-only type name)

        Common use cases:
          - SELL stop-limit: protect a long position (stop-loss)
              stop_price < current_price (triggers as price drops)
              Example: current=84000, stop_price=80000, price=79500
          - BUY stop-limit: enter on a breakout
              stop_price > current_price (triggers as price rises)
              Example: current=84000, stop_price=86000, price=86500

        Args:
            symbol:     Uppercase trading symbol (e.g., "BTCUSDT").
            side:       "BUY" or "SELL".
            quantity:   Desired quantity (rounded to stepSize).
            price:      Limit fill price (rounded to tickSize).
            stop_price: Market trigger price (rounded to tickSize).

        Returns:
            OrderResult with status "NEW" (queued, awaiting trigger).
        """
        logger.debug(
            "[ORDER MANAGER] Building STOP_LIMIT order: symbol=%s side=%s "
            "quantity=%s price=%s stop_price=%s",
            symbol, side, quantity, price, stop_price,
        )

        filters = self._client.get_exchange_info(symbol)
        rounded_qty        = _round_to_step(quantity,   filters.step_size)
        rounded_price      = _round_to_step(price,      filters.tick_size)
        rounded_stop_price = _round_to_step(stop_price, filters.tick_size)

        logger.debug(
            "[PRECISION] qty: %s->%s (step=%s) | price: %s->%s (tick=%s) | "
            "stopPrice: %s->%s (tick=%s)",
            quantity, rounded_qty, filters.step_size,
            price, rounded_price, filters.tick_size,
            stop_price, rounded_stop_price, filters.tick_size,
        )

        payload = {
            "symbol":      symbol,
            "side":        side,
            "type":        "STOP",                  # Binance Futures stop-limit type
            "quantity":    rounded_qty,
            "price":       rounded_price,            # Limit price (fills here)
            "stopPrice":   rounded_stop_price,       # Trigger price
            "timeInForce": "GTC",
        }

        raw_response = self._client.place_order(payload)
        return OrderResult.from_api_response(raw_response)
