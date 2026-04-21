"""
Input validators for the Primetrade Trading Bot.

All functions here are PURE — they make no API calls, have no side effects,
and never print or log. They receive raw strings/floats and return a
ValidationResult describing what's valid, invalid, or just a warning.

This design means validators are 100% unit-testable without any mocking.

Supported order types: MARKET, LIMIT, STOP_LIMIT

Usage:
    result = validate_all(symbol="BTCUSDT", side="buy", order_type="LIMIT",
                          quantity="0.001", price=60000, stop_price=None)
    if not result.is_valid:
        for error in result.errors:
            print(error)
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """
    Structured output from the validation layer.

    Attributes:
        is_valid:   True only if there are zero errors (warnings are allowed).
        errors:     Hard failures — execution must be blocked.
        warnings:   Soft notices — execution can continue, but user should know.
        symbol:     Normalised (uppercased) symbol value.
        side:       Normalised (uppercased) side value.
        order_type: Normalised (uppercased) order type.
        quantity:   Parsed float quantity (None if invalid).
        price:      Parsed float limit price (None if not provided or invalid).
        stop_price: Parsed float trigger price for STOP_LIMIT (None otherwise).
    """
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Normalised values (populated by validate_all)
    symbol: str = ""
    side: str = ""
    order_type: str = ""
    quantity: float | None = None
    price: float | None = None
    stop_price: float | None = None

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Individual validators (pure functions)
# ---------------------------------------------------------------------------

def validate_symbol(symbol: str | None, result: ValidationResult) -> str:
    """
    Validate and normalise a trading symbol.

    Rules:
        - Must be non-empty
        - Must be alphanumeric (no spaces, dashes, dots)
        - Normalised to uppercase

    Returns:
        Uppercased symbol string, or "" on failure.
    """
    if not symbol or not symbol.strip():
        result.add_error("Symbol is required. Example: BTCUSDT")
        return ""

    normalised = symbol.strip().upper()

    if not normalised.isalnum():
        result.add_error(
            f"Symbol '{normalised}' contains invalid characters. "
            f"Use only letters and numbers (e.g., BTCUSDT, ETHUSDT)."
        )
        return ""

    return normalised


def validate_side(side: str | None, result: ValidationResult) -> str:
    """
    Validate and normalise the order side.

    Rules:
        - Must be "BUY" or "SELL" (case-insensitive)

    Returns:
        Uppercased side string ("BUY" or "SELL"), or "" on failure.
    """
    valid_sides = {"BUY", "SELL"}

    if not side or not side.strip():
        result.add_error(f"Side is required. Must be one of: {', '.join(valid_sides)}")
        return ""

    normalised = side.strip().upper()

    if normalised not in valid_sides:
        result.add_error(
            f"Invalid side '{side}'. Must be one of: {', '.join(valid_sides)}"
        )
        return ""

    return normalised


def validate_order_type(order_type: str | None, result: ValidationResult) -> str:
    """
    Validate and normalise the order type.

    Rules:
        - Must be "MARKET", "LIMIT", or "STOP_LIMIT" (case-insensitive)

    Returns:
        Uppercased order type, or "" on failure.
    """
    valid_types = {"MARKET", "LIMIT", "STOP_LIMIT"}

    if not order_type or not order_type.strip():
        result.add_error(
            f"Order type is required. Must be one of: {', '.join(sorted(valid_types))}"
        )
        return ""

    normalised = order_type.strip().upper()

    if normalised not in valid_types:
        result.add_error(
            f"Invalid order type '{order_type}'. "
            f"Must be one of: {', '.join(sorted(valid_types))}"
        )
        return ""

    return normalised


def validate_quantity(quantity: str | float | None, result: ValidationResult) -> float | None:
    """
    Validate the order quantity.

    Rules:
        - Must be provided and non-empty
        - Must be parseable as a positive float
        - Must be > 0

    Returns:
        Parsed float quantity, or None on failure.
    """
    if quantity is None or str(quantity).strip() == "":
        result.add_error("Quantity is required and must be a positive number. Example: 0.001")
        return None

    try:
        qty = float(quantity)
    except (ValueError, TypeError):
        result.add_error(
            f"Invalid quantity '{quantity}'. Must be a numeric value. Example: 0.001"
        )
        return None

    if qty <= 0:
        result.add_error(f"Quantity must be greater than zero. Got: {qty}")
        return None

    return qty


def validate_price(
    price: str | float | None,
    order_type: str,
    result: ValidationResult,
) -> float | None:
    """
    Validate the order limit price relative to the order type.

    Rules:
        - MARKET orders:     price must be absent (warning if provided)
        - LIMIT orders:      price is REQUIRED, must be a positive float
        - STOP_LIMIT orders: price is REQUIRED (this is the limit fill price,
                             distinct from the trigger stop_price)

    Args:
        price:      The raw price value from user input.
        order_type: The normalised order type string.
        result:     The ValidationResult to mutate with errors/warnings.

    Returns:
        Parsed float price for LIMIT/STOP_LIMIT, None for MARKET or on failure.
    """
    normalised_type = order_type.upper() if order_type else ""

    if normalised_type == "MARKET":
        if price is not None and str(price).strip() != "":
            result.add_warning(
                f"Price '{price}' is ignored for MARKET orders — "
                f"the order will execute at the best available market price."
            )
        return None

    if normalised_type in ("LIMIT", "STOP_LIMIT"):
        label = "limit price" if normalised_type == "STOP_LIMIT" else "price"
        if price is None or str(price).strip() == "":
            result.add_error(
                f"--price is required for {normalised_type} orders "
                f"(this is the {label} at which the order fills). "
                f"Example: --price 60000"
            )
            return None

        try:
            p = float(price)
        except (ValueError, TypeError):
            result.add_error(
                f"Invalid price '{price}'. Must be a numeric value. Example: 60000.50"
            )
            return None

        if p <= 0:
            result.add_error(f"Price must be greater than zero. Got: {p}")
            return None

        return p

    # Unknown order type — price validation deferred to validate_order_type
    return None


def validate_stop_price(
    stop_price: str | float | None,
    order_type: str,
    result: ValidationResult,
) -> float | None:
    """
    Validate the stop (trigger) price for STOP_LIMIT orders.

    The stop_price is the market trigger price. When the market reaches
    stop_price, Binance places a limit order at the specified price.

    Rules:
        - STOP_LIMIT orders: stop_price is REQUIRED, must be a positive float
        - All other types:   stop_price must be absent (warning if provided)

    Args:
        stop_price: The raw stop price value from user input.
        order_type: The normalised order type string.
        result:     The ValidationResult to mutate with errors/warnings.

    Returns:
        Parsed float stop_price for STOP_LIMIT, None otherwise.
    """
    normalised_type = order_type.upper() if order_type else ""

    if normalised_type == "STOP_LIMIT":
        if stop_price is None or str(stop_price).strip() == "":
            result.add_error(
                "--stop-price is required for STOP_LIMIT orders. "
                "This is the trigger price that activates the limit order. "
                "Example: --stop-price 58000"
            )
            return None

        try:
            sp = float(stop_price)
        except (ValueError, TypeError):
            result.add_error(
                f"Invalid stop price '{stop_price}'. Must be a numeric value. Example: 58000"
            )
            return None

        if sp <= 0:
            result.add_error(f"Stop price must be greater than zero. Got: {sp}")
            return None

        return sp

    # For non-STOP_LIMIT types, stop_price is not applicable
    if stop_price is not None and str(stop_price).strip() != "":
        result.add_warning(
            f"--stop-price '{stop_price}' is ignored for {normalised_type or 'this'} orders."
        )
    return None


# ---------------------------------------------------------------------------
# Aggregate validator
# ---------------------------------------------------------------------------

def validate_all(
    symbol: str | None,
    side: str | None,
    order_type: str | None,
    quantity: str | float | None,
    price: str | float | None,
    stop_price: str | float | None = None,
) -> ValidationResult:
    """
    Run all validators and return a single consolidated ValidationResult.

    All validators are always run (even if earlier ones fail) so the user
    sees ALL validation errors at once, not one at a time.

    Args:
        symbol:     Raw symbol string from CLI.
        side:       Raw side string from CLI ("BUY" / "SELL").
        order_type: Raw order type string ("MARKET" / "LIMIT" / "STOP_LIMIT").
        quantity:   Raw quantity from CLI.
        price:      Raw limit price from CLI (required for LIMIT and STOP_LIMIT).
        stop_price: Raw trigger price from CLI (required for STOP_LIMIT only).

    Returns:
        ValidationResult with normalised values and any errors/warnings.
    """
    result = ValidationResult()

    result.symbol     = validate_symbol(symbol, result)
    result.side       = validate_side(side, result)
    result.order_type = validate_order_type(order_type, result)
    result.quantity   = validate_quantity(quantity, result)

    # Price and stop_price validation depend on order_type
    effective_type = result.order_type or (order_type or "")
    result.price      = validate_price(price, effective_type, result)
    result.stop_price = validate_stop_price(stop_price, effective_type, result)

    return result
