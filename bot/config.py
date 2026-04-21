"""
Centralised configuration for the Primetrade Trading Bot.

All settings are loaded once at import time from environment variables.
The .env file is loaded automatically via python-dotenv.

Usage:
    from bot.config import settings
    print(settings.BASE_URL)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from bot.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Load .env from project root (two levels up from this file)
# ---------------------------------------------------------------------------
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)


# ---------------------------------------------------------------------------
# Settings dataclass — single source of truth for all config values
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    """Immutable settings loaded from environment variables."""

    # Binance API credentials
    api_key: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))

    # Binance Futures Testnet base URL
    base_url: str = field(
        default_factory=lambda: os.getenv(
            "BINANCE_BASE_URL", "https://testnet.binancefuture.com"
        )
    )

    # Request timeout in seconds — prevents hanging indefinitely
    request_timeout: int = field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT", "10"))
    )

    # recvWindow in milliseconds — guards against timestamp drift (max 60_000)
    recv_window: int = field(
        default_factory=lambda: int(os.getenv("RECV_WINDOW", "5000"))
    )

    # Log file path
    log_file: str = field(
        default_factory=lambda: os.getenv(
            "LOG_FILE",
            str(Path(__file__).resolve().parent.parent / "logs" / "trading_bot.log"),
        )
    )

    def validate(self) -> None:
        """
        Validate that all required settings are present.

        Raises:
            ConfigurationError: If API key or secret is missing.
        """
        missing: list[str] = []

        if not self.api_key:
            missing.append("BINANCE_API_KEY")
        if not self.api_secret:
            missing.append("BINANCE_API_SECRET")

        if missing:
            raise ConfigurationError(
                f"Missing required environment variable(s): {', '.join(missing)}\n"
                f"  → Copy .env.example to .env and fill in your Binance Testnet credentials.\n"
                f"  → Get credentials at: https://testnet.binancefuture.com"
            )


# ---------------------------------------------------------------------------
# Singleton settings instance — import this everywhere
# ---------------------------------------------------------------------------
settings = Settings()
