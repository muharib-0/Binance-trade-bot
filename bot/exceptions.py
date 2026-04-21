"""
Custom exception hierarchy for the Primetrade Trading Bot.

All exceptions inherit from TradingBotError so callers can catch the
base class when they want to handle any bot-related failure, or catch
specific subclasses for fine-grained handling.
"""


class TradingBotError(Exception):
    """Base exception for all trading bot errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ConfigurationError(TradingBotError):
    """
    Raised when required configuration is missing or invalid.

    Examples:
        - BINANCE_API_KEY not set in .env
        - BINANCE_API_SECRET not set in .env
        - BASE_URL is malformed
    """


class ValidationError(TradingBotError):
    """
    Raised when user-supplied CLI input fails validation.

    Attributes:
        errors:   List of hard validation failures (block execution).
        warnings: List of soft warnings (execution continues).
    """

    def __init__(self, message: str, errors: list[str] | None = None, warnings: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors: list[str] = errors or []
        self.warnings: list[str] = warnings or []


class APIError(TradingBotError):
    """
    Raised when the Binance API returns a non-2xx response with an error body.

    Attributes:
        code:    Binance error code (e.g., -1121 for invalid symbol).
        message: Human-readable error message from Binance.
        status:  HTTP status code.
    """

    def __init__(self, message: str, code: int | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status

    def __str__(self) -> str:
        parts = [self.message]
        if self.code is not None:
            parts.append(f"(Binance code: {self.code})")
        if self.status is not None:
            parts.append(f"[HTTP {self.status}]")
        return " ".join(parts)


class AuthenticationError(APIError):
    """
    Raised on HTTP 401/403 responses — bad API key or invalid signature.

    This is a subclass of APIError so it can be caught by either handler.
    """


class NetworkError(TradingBotError):
    """
    Raised on transport-level failures before a response is received.

    Examples:
        - Connection timeout
        - DNS resolution failure
        - SSL certificate error
    """
