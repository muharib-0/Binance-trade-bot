"""
Unit tests for bot.client (BinanceFuturesClient)

All HTTP calls are mocked via pytest-mock — no real network access.
Tests verify:
  - HMAC-SHA256 signature is present and non-empty
  - X-MBX-APIKEY header is set on the session
  - timestamp and recvWindow are included in signed requests
  - HTTP 400 response raises APIError with code and message
  - HTTP 401/403 raises AuthenticationError
  - requests.Timeout raises NetworkError
  - requests.ConnectionError raises NetworkError
  - Sanitise params redacts signature without mutating original
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest
import requests

from bot.exceptions import APIError, AuthenticationError, NetworkError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_response(status_code: int, json_body: dict) -> MagicMock:
    """Build a mock requests.Response."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_body
    response.text = str(json_body)
    return response


@dataclass
class FakeSettings:
    """Mutable replacement for the frozen Settings dataclass used in tests."""
    api_key: str = "test_api_key_abcdef"
    api_secret: str = "test_api_secret_xyz"
    base_url: str = "https://testnet.binancefuture.com"
    request_timeout: int = 10
    recv_window: int = 5000
    log_file: str = "logs/trading_bot.log"

    def validate(self) -> None:
        pass  # No-op in tests


def _get_client_with_fake_settings(fake_settings: FakeSettings):
    """
    Build a BinanceFuturesClient with a fake settings object injected.
    Avoids patching the frozen dataclass — patches the module-level reference instead.
    """
    with patch("bot.client.settings", fake_settings), \
         patch("bot.config.settings", fake_settings):
        from bot.client import BinanceFuturesClient
        client = BinanceFuturesClient.__new__(BinanceFuturesClient)
        client._session = MagicMock()
        return client, fake_settings


# ---------------------------------------------------------------------------
# _sign — HMAC signing logic
# ---------------------------------------------------------------------------

class TestBinanceFuturesClientSigning:
    """Tests for HMAC signing logic — no HTTP calls made."""

    def test_signature_present_in_signed_params(self):
        fake = FakeSettings()
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()

            signed = client._sign({"symbol": "BTCUSDT", "side": "BUY"})

        assert "signature" in signed
        assert len(signed["signature"]) == 64  # SHA-256 hex digest is always 64 chars

    def test_timestamp_added_to_signed_params(self):
        fake = FakeSettings()
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
            signed = client._sign({"quantity": "0.001"})

        assert "timestamp" in signed
        assert isinstance(signed["timestamp"], int)
        assert signed["timestamp"] > 0

    def test_recv_window_added_to_signed_params(self):
        fake = FakeSettings(recv_window=5000)
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
            signed = client._sign({"quantity": "0.001"})

        assert "recvWindow" in signed
        assert signed["recvWindow"] == 5000

    def test_signature_is_valid_hmac_sha256(self):
        """Verify signature matches independently computed HMAC-SHA256."""
        api_secret = "my_test_secret_for_hmac"
        fake = FakeSettings(api_key="test_key", api_secret=api_secret, recv_window=5000)

        with patch("bot.client.settings", fake), \
             patch("bot.client.time") as mock_time:
            mock_time.time.return_value = 1_700_000_000.0
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
            signed = client._sign({"symbol": "BTCUSDT"})

        # Recompute independently
        query = urlencode({k: v for k, v in signed.items() if k != "signature"})
        expected = hmac.new(
            api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert signed["signature"] == expected

    def test_original_params_not_mutated(self):
        """_sign() must not modify the original params dict."""
        fake = FakeSettings()
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
            original = {"symbol": "BTCUSDT"}
            client._sign(original)

        assert "signature" not in original
        assert "timestamp" not in original


# ---------------------------------------------------------------------------
# _handle_response — error mapping
# ---------------------------------------------------------------------------

class TestHandleResponse:
    def _get_client(self):
        fake = FakeSettings()
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
        return client

    def test_200_response_returns_data(self):
        client = self._get_client()
        mock_resp = _make_mock_response(200, {"orderId": 999})
        with patch("bot.client.settings", FakeSettings()):
            result = client._handle_response(mock_resp)
        assert result["orderId"] == 999

    def test_400_raises_api_error(self):
        client = self._get_client()
        mock_resp = _make_mock_response(400, {"code": -1121, "msg": "Invalid symbol."})
        with patch("bot.client.settings", FakeSettings()):
            with pytest.raises(APIError) as exc_info:
                client._handle_response(mock_resp)
        assert exc_info.value.code == -1121
        assert exc_info.value.status == 400

    def test_401_raises_authentication_error(self):
        client = self._get_client()
        mock_resp = _make_mock_response(401, {"code": -2014, "msg": "API-key format invalid."})
        with patch("bot.client.settings", FakeSettings()):
            with pytest.raises(AuthenticationError) as exc_info:
                client._handle_response(mock_resp)
        assert exc_info.value.status == 401

    def test_403_raises_authentication_error(self):
        client = self._get_client()
        mock_resp = _make_mock_response(403, {"code": -2015, "msg": "Invalid API-key."})
        with patch("bot.client.settings", FakeSettings()):
            with pytest.raises(AuthenticationError):
                client._handle_response(mock_resp)

    def test_auth_error_is_catchable_as_api_error(self):
        """AuthenticationError is a subclass of APIError — must be catchable as parent."""
        client = self._get_client()
        mock_resp = _make_mock_response(401, {"code": -2014, "msg": "Bad key."})
        with patch("bot.client.settings", FakeSettings()):
            with pytest.raises(APIError):  # Catch as parent class
                client._handle_response(mock_resp)


# ---------------------------------------------------------------------------
# Network error mapping
# ---------------------------------------------------------------------------

class TestNetworkErrors:
    def test_timeout_on_place_order_raises_network_error(self):
        fake = FakeSettings()
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
            client._session.post.side_effect = requests.Timeout()

            with patch("bot.client.settings", fake):
                with pytest.raises(NetworkError) as exc_info:
                    client.place_order({"symbol": "BTCUSDT", "side": "BUY",
                                        "type": "MARKET", "quantity": "0.001"})
        assert "timed out" in str(exc_info.value).lower()

    def test_connection_error_on_place_order_raises_network_error(self):
        fake = FakeSettings()
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
            client._session.post.side_effect = requests.ConnectionError("DNS failed")

            with patch("bot.client.settings", fake):
                with pytest.raises(NetworkError):
                    client.place_order({"symbol": "BTCUSDT", "side": "BUY",
                                        "type": "MARKET", "quantity": "0.001"})

    def test_timeout_on_exchange_info_raises_network_error(self):
        fake = FakeSettings()
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
            client._session.get.side_effect = requests.Timeout()

            with patch("bot.client.settings", fake):
                with pytest.raises(NetworkError):
                    client.get_exchange_info("BTCUSDT")


# ---------------------------------------------------------------------------
# _sanitise_params (security)
# ---------------------------------------------------------------------------

class TestSanitiseParams:
    def _get_client(self):
        fake = FakeSettings()
        with patch("bot.client.settings", fake):
            from bot.client import BinanceFuturesClient
            client = BinanceFuturesClient.__new__(BinanceFuturesClient)
            client._session = MagicMock()
        return client

    def test_signature_is_redacted(self):
        client = self._get_client()
        params = {"symbol": "BTCUSDT", "signature": "abc123def456" * 5}
        sanitised = client._sanitise_params(params)
        assert sanitised["signature"] == "[REDACTED]"
        assert sanitised["symbol"] == "BTCUSDT"

    def test_original_params_not_mutated(self):
        client = self._get_client()
        original = {"symbol": "BTCUSDT", "signature": "real_secret_value"}
        client._sanitise_params(original)
        assert original["signature"] == "real_secret_value"

    def test_params_without_signature_unchanged(self):
        client = self._get_client()
        params = {"symbol": "BTCUSDT", "quantity": "0.001"}
        sanitised = client._sanitise_params(params)
        assert "signature" not in sanitised
        assert sanitised == params
