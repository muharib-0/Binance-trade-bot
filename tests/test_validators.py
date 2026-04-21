"""
Unit tests for bot.validators

These tests are 100% pure — no mocking, no network calls, no file I/O.
They validate every branch of the validation logic including edge cases
around LIMIT price requirements and MARKET price warnings.
"""

from __future__ import annotations

import pytest

from bot.validators import (
    ValidationResult,
    validate_all,
    validate_order_type,
    validate_price,
    validate_quantity,
    validate_side,
    validate_symbol,
)


# ---------------------------------------------------------------------------
# validate_symbol
# ---------------------------------------------------------------------------

class TestValidateSymbol:
    def test_valid_symbol_uppercased(self):
        r = ValidationResult()
        assert validate_symbol("btcusdt", r) == "BTCUSDT"
        assert r.is_valid

    def test_already_uppercase(self):
        r = ValidationResult()
        assert validate_symbol("ETHUSDT", r) == "ETHUSDT"
        assert r.is_valid

    def test_strips_whitespace(self):
        r = ValidationResult()
        assert validate_symbol("  BTCUSDT  ", r) == "BTCUSDT"
        assert r.is_valid

    def test_empty_string_fails(self):
        r = ValidationResult()
        result = validate_symbol("", r)
        assert result == ""
        assert not r.is_valid
        assert len(r.errors) == 1

    def test_none_fails(self):
        r = ValidationResult()
        result = validate_symbol(None, r)
        assert result == ""
        assert not r.is_valid

    def test_special_characters_fail(self):
        r = ValidationResult()
        result = validate_symbol("BTC-USDT", r)
        assert result == ""
        assert not r.is_valid
        assert "invalid characters" in r.errors[0].lower()


# ---------------------------------------------------------------------------
# validate_side
# ---------------------------------------------------------------------------

class TestValidateSide:
    def test_buy_uppercase(self):
        r = ValidationResult()
        assert validate_side("BUY", r) == "BUY"
        assert r.is_valid

    def test_sell_lowercase_normalised(self):
        r = ValidationResult()
        assert validate_side("sell", r) == "SELL"
        assert r.is_valid

    def test_mixed_case_normalised(self):
        r = ValidationResult()
        assert validate_side("Buy", r) == "BUY"
        assert r.is_valid

    def test_invalid_side_long(self):
        r = ValidationResult()
        result = validate_side("LONG", r)
        assert result == ""
        assert not r.is_valid
        assert "BUY" in r.errors[0] or "SELL" in r.errors[0]

    def test_empty_side_fails(self):
        r = ValidationResult()
        validate_side("", r)
        assert not r.is_valid

    def test_none_side_fails(self):
        r = ValidationResult()
        validate_side(None, r)
        assert not r.is_valid


# ---------------------------------------------------------------------------
# validate_order_type
# ---------------------------------------------------------------------------

class TestValidateOrderType:
    def test_market_valid(self):
        r = ValidationResult()
        assert validate_order_type("MARKET", r) == "MARKET"
        assert r.is_valid

    def test_limit_valid(self):
        r = ValidationResult()
        assert validate_order_type("LIMIT", r) == "LIMIT"
        assert r.is_valid

    def test_lowercase_normalised(self):
        r = ValidationResult()
        assert validate_order_type("limit", r) == "LIMIT"
        assert r.is_valid

    def test_invalid_type_stop(self):
        r = ValidationResult()
        result = validate_order_type("STOP", r)
        assert result == ""
        assert not r.is_valid

    def test_empty_type_fails(self):
        r = ValidationResult()
        validate_order_type("", r)
        assert not r.is_valid


# ---------------------------------------------------------------------------
# validate_quantity
# ---------------------------------------------------------------------------

class TestValidateQuantity:
    def test_valid_float_string(self):
        r = ValidationResult()
        assert validate_quantity("0.001", r) == pytest.approx(0.001)
        assert r.is_valid

    def test_valid_float(self):
        r = ValidationResult()
        assert validate_quantity(0.5, r) == pytest.approx(0.5)
        assert r.is_valid

    def test_valid_integer(self):
        r = ValidationResult()
        assert validate_quantity(1, r) == pytest.approx(1.0)
        assert r.is_valid

    def test_zero_fails(self):
        r = ValidationResult()
        result = validate_quantity(0, r)
        assert result is None
        assert not r.is_valid
        assert "greater than zero" in r.errors[0]

    def test_negative_fails(self):
        r = ValidationResult()
        result = validate_quantity(-1.5, r)
        assert result is None
        assert not r.is_valid

    def test_non_numeric_string_fails(self):
        r = ValidationResult()
        result = validate_quantity("abc", r)
        assert result is None
        assert not r.is_valid
        assert "numeric" in r.errors[0].lower()

    def test_none_fails(self):
        r = ValidationResult()
        result = validate_quantity(None, r)
        assert result is None
        assert not r.is_valid

    def test_empty_string_fails(self):
        r = ValidationResult()
        result = validate_quantity("", r)
        assert result is None
        assert not r.is_valid


# ---------------------------------------------------------------------------
# validate_price
# ---------------------------------------------------------------------------

class TestValidatePrice:
    def test_limit_with_valid_price(self):
        r = ValidationResult()
        p = validate_price("60000.50", "LIMIT", r)
        assert p == pytest.approx(60000.50)
        assert r.is_valid
        assert not r.errors

    def test_limit_without_price_fails(self):
        r = ValidationResult()
        p = validate_price(None, "LIMIT", r)
        assert p is None
        assert not r.is_valid
        assert "--price" in r.errors[0]

    def test_limit_with_empty_price_fails(self):
        r = ValidationResult()
        p = validate_price("", "LIMIT", r)
        assert p is None
        assert not r.is_valid

    def test_limit_with_zero_price_fails(self):
        r = ValidationResult()
        p = validate_price(0, "LIMIT", r)
        assert p is None
        assert not r.is_valid
        assert "greater than zero" in r.errors[0]

    def test_limit_with_negative_price_fails(self):
        r = ValidationResult()
        p = validate_price(-100.0, "LIMIT", r)
        assert p is None
        assert not r.is_valid

    def test_limit_with_nonnumeric_price_fails(self):
        r = ValidationResult()
        p = validate_price("sixty-thousand", "LIMIT", r)
        assert p is None
        assert not r.is_valid

    def test_market_without_price_ok(self):
        r = ValidationResult()
        p = validate_price(None, "MARKET", r)
        assert p is None
        assert r.is_valid
        assert not r.warnings  # No warning when price is simply absent

    def test_market_with_price_warns(self):
        """Providing a price for MARKET is a warning, not an error."""
        r = ValidationResult()
        p = validate_price(60000.0, "MARKET", r)
        assert p is None            # Price is still excluded for MARKET
        assert r.is_valid           # Not an error
        assert len(r.warnings) == 1
        assert "ignored" in r.warnings[0].lower()


# ---------------------------------------------------------------------------
# validate_all (integration)
# ---------------------------------------------------------------------------

class TestValidateAll:
    def test_valid_market_order(self):
        result = validate_all(
            symbol="BTCUSDT", side="BUY", order_type="MARKET",
            quantity="0.001", price=None,
        )
        assert result.is_valid
        assert result.symbol == "BTCUSDT"
        assert result.side == "BUY"
        assert result.order_type == "MARKET"
        assert result.quantity == pytest.approx(0.001)
        assert result.price is None
        assert not result.errors

    def test_valid_limit_order(self):
        result = validate_all(
            symbol="ETHUSDT", side="SELL", order_type="LIMIT",
            quantity="0.5", price="3000.00",
        )
        assert result.is_valid
        assert result.price == pytest.approx(3000.00)
        assert not result.errors

    def test_limit_without_price_fails(self):
        result = validate_all(
            symbol="BTCUSDT", side="BUY", order_type="LIMIT",
            quantity="0.001", price=None,
        )
        assert not result.is_valid
        assert any("--price" in e for e in result.errors)

    def test_multiple_errors_collected(self):
        """All validation errors should be collected in a single pass."""
        result = validate_all(
            symbol="", side="LONG", order_type="STOP",
            quantity="-1", price=None,
        )
        assert not result.is_valid
        # Should have errors for symbol, side, order_type, and quantity
        assert len(result.errors) >= 3

    def test_market_with_price_generates_warning_not_error(self):
        result = validate_all(
            symbol="BTCUSDT", side="BUY", order_type="MARKET",
            quantity="0.001", price=65000.0,
        )
        assert result.is_valid        # Still valid
        assert len(result.warnings) == 1
        assert not result.errors

    def test_lowercase_inputs_normalised(self):
        result = validate_all(
            symbol="btcusdt", side="buy", order_type="market",
            quantity="0.001", price=None,
        )
        assert result.is_valid
        assert result.symbol == "BTCUSDT"
        assert result.side == "BUY"
        assert result.order_type == "MARKET"
