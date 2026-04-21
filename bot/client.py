"""
BinanceFuturesClient — Integration Layer

The ONLY module that communicates with the Binance Futures Testnet REST API.
Handles:
  - HMAC-SHA256 request signing
  - Session management with auth headers
  - Exchange filter fetching (stepSize / tickSize / minQty)
  - Order placement
  - Typed exception mapping (APIError, AuthenticationError, NetworkError)

No business logic lives here — only raw API communication.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from bot.config import settings
from bot.exceptions import APIError, AuthenticationError, NetworkError
from bot.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data containers for exchange filter data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SymbolFilters:
    """
    Exchange-imposed precision rules for a trading symbol.

    Attributes:
        step_size: Minimum quantity increment (e.g., "0.001" for BTCUSDT).
        tick_size: Minimum price increment (e.g., "0.10" for BTCUSDT).
        min_qty:   Minimum allowed order quantity.
        min_price: Minimum allowed order price.
    """
    step_size: str
    tick_size: str
    min_qty: str
    min_price: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class BinanceFuturesClient:
    """
    HTTP client for the Binance Futures Testnet REST API.

    All authenticated requests are signed with HMAC-SHA256.
    API credentials are loaded exclusively from environment variables
    via bot.config.settings — never from CLI arguments.

    Usage:
        client = BinanceFuturesClient()
        filters = client.get_exchange_info("BTCUSDT")
        response = client.place_order({...})
    """

    def __init__(self) -> None:
        settings.validate()  # Fail fast if credentials are missing
        self._session = requests.Session()
        self._session.headers.update(self._build_headers())
        logger.debug("BinanceFuturesClient initialised. base_url=%s", settings.base_url)

    # ── Public API ─────────────────────────────────────────────────────────

    def get_exchange_info(self, symbol: str) -> SymbolFilters:
        """
        Fetch LOT_SIZE and PRICE_FILTER exchange filters for a symbol.

        These filters define the allowed step_size for quantity and
        tick_size for price. Sending values that violate these rules
        causes Binance to reject the order with error -1111.

        Args:
            symbol: Trading symbol in uppercase (e.g., "BTCUSDT").

        Returns:
            SymbolFilters with step_size, tick_size, min_qty, min_price.

        Raises:
            APIError: If the symbol is not found or the API returns an error.
            NetworkError: On connection/timeout failures.
        """
        logger.debug("[EXCHANGE INFO] Fetching filters for symbol=%s", symbol)

        url = f"{settings.base_url}/fapi/v1/exchangeInfo"
        try:
            response = self._session.get(
                url,
                params={"symbol": symbol},
                timeout=settings.request_timeout,
            )
        except requests.Timeout:
            raise NetworkError(
                f"Request timed out after {settings.request_timeout}s while fetching "
                f"exchange info for {symbol}. Check your internet connection."
            )
        except requests.ConnectionError as exc:
            raise NetworkError(
                f"Could not connect to Binance API: {exc}. "
                f"Verify the base URL ({settings.base_url}) and your network."
            )

        data = self._handle_response(response)

        # Parse the symbols array for the requested symbol
        symbols: list[dict] = data.get("symbols", [])
        symbol_data = next((s for s in symbols if s["symbol"] == symbol), None)

        if symbol_data is None:
            raise APIError(
                f"Symbol '{symbol}' not found on Binance Futures Testnet. "
                f"Check the symbol name (must be uppercase, e.g., BTCUSDT)."
            )

        filters_raw: list[dict] = symbol_data.get("filters", [])
        filters_by_type = {f["filterType"]: f for f in filters_raw}

        lot_size   = filters_by_type.get("LOT_SIZE", {})
        price_filter = filters_by_type.get("PRICE_FILTER", {})

        result = SymbolFilters(
            step_size  = lot_size.get("stepSize", "0.001"),
            tick_size  = price_filter.get("tickSize", "0.1"),
            min_qty    = lot_size.get("minQty", "0.001"),
            min_price  = price_filter.get("minPrice", "0.1"),
        )

        logger.debug(
            "[EXCHANGE INFO] symbol=%s stepSize=%s tickSize=%s minQty=%s",
            symbol, result.step_size, result.tick_size, result.min_qty,
        )
        return result

    def place_order(self, payload: dict) -> dict:
        """
        Place an order on Binance Futures Testnet.

        The payload should already have quantity and price rounded to the
        correct precision by OrderManager before calling this method.

        Args:
            payload: Order parameters (symbol, side, type, quantity, etc.)
                     Do NOT include timestamp or signature — this method adds them.

        Returns:
            Raw Binance API response dict with order details.

        Raises:
            APIError: On Binance-level errors (invalid symbol, bad qty, etc.).
            AuthenticationError: On invalid API key or signature.
            NetworkError: On connection/timeout failures.
        """
        url = f"{settings.base_url}/fapi/v1/order"
        signed_params = self._sign(payload)

        # Log the request — quantity/symbol/side only, never credentials
        logger.info(
            "[ORDER REQUEST]  symbol=%s | side=%s | type=%s | quantity=%s%s",
            payload.get("symbol"),
            payload.get("side"),
            payload.get("type"),
            payload.get("quantity"),
            f" | price={payload['price']}" if "price" in payload else "",
        )
        logger.debug("[API CALL] POST /fapi/v1/order | params=%s", self._sanitise_params(signed_params))

        try:
            response = self._session.post(
                url,
                params=signed_params,
                timeout=settings.request_timeout,
            )
        except requests.Timeout:
            raise NetworkError(
                f"Order request timed out after {settings.request_timeout}s. "
                f"The order may or may not have been placed. Check your position on the testnet."
            )
        except requests.ConnectionError as exc:
            raise NetworkError(f"Network connection failed while placing order: {exc}")

        data = self._handle_response(response)

        logger.info(
            "[ORDER RESPONSE] orderId=%s | status=%s | executedQty=%s | avgPrice=%s",
            data.get("orderId"),
            data.get("status"),
            data.get("executedQty", "0"),
            data.get("avgPrice", "N/A"),
        )
        logger.debug("[API RESPONSE] status=%s | body=%s", response.status_code, data)

        return data

    # ── Private helpers ────────────────────────────────────────────────────

    def _build_headers(self) -> dict[str, str]:
        """Build session headers. API key is set here; never logged."""
        return {
            "X-MBX-APIKEY": settings.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _sign(self, params: dict) -> dict:
        """
        Add timestamp and HMAC-SHA256 signature to a parameter dict.

        Binance requires:
          1. A 'timestamp' field (milliseconds since epoch).
          2. A 'recvWindow' field (tolerance for clock drift in ms).
          3. A 'signature' field: HMAC-SHA256(secret, query_string).

        Args:
            params: The original order/request parameters.

        Returns:
            A new dict with timestamp, recvWindow, and signature added.
        """
        signed = dict(params)
        signed["timestamp"] = int(time.time() * 1000)
        signed["recvWindow"] = settings.recv_window

        query_string = urlencode(signed)
        signature = hmac.new(
            settings.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        signed["signature"] = signature
        return signed

    def _handle_response(self, response: requests.Response) -> dict:
        """
        Parse a Binance API response and raise typed exceptions on errors.

        Binance error format:  {"code": -1121, "msg": "Invalid symbol."}

        Args:
            response: The raw requests.Response object.

        Returns:
            Parsed JSON body as a dict.

        Raises:
            AuthenticationError: On HTTP 401 or 403.
            APIError: On other non-2xx HTTP status codes.
        """
        try:
            data: dict = response.json()
        except ValueError:
            raise APIError(
                f"Binance returned a non-JSON response (HTTP {response.status_code}): "
                f"{response.text[:200]}",
                status=response.status_code,
            )

        if response.status_code in (401, 403):
            code = data.get("code")
            msg  = data.get("msg", "Authentication failed.")
            raise AuthenticationError(
                f"Authentication failed: {msg} "
                f"→ Verify your BINANCE_API_KEY and BINANCE_API_SECRET in .env.",
                code=code,
                status=response.status_code,
            )

        if not response.ok:
            code = data.get("code")
            msg  = data.get("msg", f"HTTP {response.status_code} error.")
            raise APIError(
                message=self._friendly_api_error(code, msg),
                code=code,
                status=response.status_code,
            )

        return data

    @staticmethod
    def _friendly_api_error(code: int | None, msg: str) -> str:
        """
        Map common Binance error codes to human-readable messages.
        Falls back to the raw Binance message for unknown codes.
        """
        known_errors: dict[int, str] = {
            -1100: f"Illegal characters in parameter: {msg}",
            -1102: f"Mandatory parameter missing: {msg}",
            -1111: f"Precision exceeds allowed limit — quantity or price has too many decimal places. ({msg})",
            -1115: f"Invalid 'timeInForce' value: {msg}",
            -1116: f"Invalid order type: {msg}",
            -1117: f"Invalid order side (must be BUY or SELL): {msg}",
            -1121: f"Invalid symbol — not found on Binance Futures Testnet: {msg}",
            -2010: f"Insufficient balance to place this order: {msg}",
            -2011: f"Order does not exist (cannot cancel/query): {msg}",
            -4061: f"Order quantity is below minimum: {msg}",
        }
        return known_errors.get(code, msg) if code else msg  # type: ignore[arg-type]

    @staticmethod
    def _sanitise_params(params: dict) -> dict:
        """
        Return a copy of params with the signature value redacted.
        Used exclusively for debug logging — never logs the actual signature.
        """
        safe = dict(params)
        if "signature" in safe:
            safe["signature"] = "[REDACTED]"
        return safe
