"""
CLI entry point for the Primetrade Trading Bot.

Provides the 'place-order' command using Typer + Rich for a polished
command-line experience.

Usage:
    # Market order
    python -m bot.cli place-order --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001

    # Limit order
    python -m bot.cli place-order --symbol BTCUSDT --side SELL --type LIMIT --quantity 0.001 --price 60000

    # Help
    python -m bot.cli --help
    python -m bot.cli place-order --help
"""

from __future__ import annotations

import sys
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from bot.client import BinanceFuturesClient
from bot.exceptions import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    NetworkError,
)
from bot.logging_config import get_logger
from bot.orders import OrderManager, OrderResult
from bot.validators import validate_all

# ---------------------------------------------------------------------------
# Typer app setup
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="trading-bot",
    help=(
        "Primetrade Trading Bot — Place orders on Binance Futures Testnet (USDT-M).\n\n"
        "Requires BINANCE_API_KEY and BINANCE_API_SECRET in a .env file.\n"
        "Copy .env.example to .env and fill in your testnet credentials."
    ),
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Rich output helpers
# ---------------------------------------------------------------------------

def _print_request_summary(
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float],
    stop_price: Optional[float] = None,
) -> None:
    """Print a formatted table summarising the order before submission."""
    table = Table(
        title="📋  Order Request Summary",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold white",
        border_style="cyan",
    )
    table.add_column("Field",  style="dim", width=16)
    table.add_column("Value",  style="bold white")

    table.add_row("Symbol",     symbol)
    table.add_row("Side",       f"[green]{side}[/green]" if side == "BUY" else f"[red]{side}[/red]")
    table.add_row("Order Type", order_type)
    table.add_row("Quantity",   str(quantity))
    if stop_price is not None:
        table.add_row("Stop Price",  f"[yellow]{stop_price}[/yellow]  ← trigger")
    table.add_row("Price",      f"{price}" if price is not None else "[dim]Market price[/dim]")

    console.print()
    console.print(table)


def _print_order_response(result: OrderResult) -> None:
    """Print a formatted table with the Binance order response fields."""
    table = Table(
        title="✅  Order Response",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold green",
        title_style="bold green",
        border_style="green",
    )
    table.add_column("Field",   style="dim", width=18)
    table.add_column("Value",   style="bold white")

    status_colour = {
        "FILLED":           "green",
        "NEW":              "yellow",
        "PARTIALLY_FILLED": "yellow",
        "CANCELED":         "red",
        "REJECTED":         "red",
        "EXPIRED":          "red",
    }.get(result.status, "white")

    avg_price_display = (
        result.avg_price
        if result.avg_price and result.avg_price not in ("0", "0.00000000", "")
        else "[dim]Pending fill[/dim]"
    )

    table.add_row("Order ID",     str(result.order_id))
    table.add_row("Symbol",       result.symbol)
    table.add_row("Side",         result.side)
    table.add_row("Type",         result.order_type)
    table.add_row("Status",       f"[{status_colour}]{result.status}[/{status_colour}]")
    table.add_row("Orig Qty",     result.orig_qty)
    table.add_row("Executed Qty", result.executed_qty)
    table.add_row("Avg Price",    avg_price_display)
    if result.stop_price and result.stop_price not in ("0", "0.00000000", ""):
        table.add_row("Stop Price",   f"[yellow]{result.stop_price}[/yellow]  ← trigger")
    if result.price and result.price not in ("0", "0.00000000", ""):
        table.add_row("Limit Price",   result.price)
    if result.time_in_force:
        table.add_row("Time In Force", result.time_in_force)

    console.print()
    console.print(table)
    console.print()


def _print_warnings(warnings: list[str]) -> None:
    """Print non-fatal warnings in a yellow panel."""
    if warnings:
        warning_text = "\n".join(f"⚠  {w}" for w in warnings)
        console.print(
            Panel(warning_text, title="Warnings", border_style="yellow", title_align="left")
        )


def _print_error(title: str, message: str, hint: Optional[str] = None) -> None:
    """Print a red error panel to stderr."""
    body = f"[bold red]{message}[/bold red]"
    if hint:
        body += f"\n\n[dim]{hint}[/dim]"
    err_console.print()
    err_console.print(
        Panel(body, title=f"❌  {title}", border_style="red", title_align="left")
    )
    err_console.print()


def _print_validation_errors(errors: list[str], warnings: list[str]) -> None:
    """Print all validation errors at once — never one-by-one."""
    error_lines = "\n".join(f"  • {e}" for e in errors)
    err_console.print()
    err_console.print(
        Panel(
            f"[bold red]The following input errors must be corrected:[/bold red]\n\n{error_lines}",
            title="❌  Validation Failed",
            border_style="red",
            title_align="left",
        )
    )
    _print_warnings(warnings)
    err_console.print()


# ---------------------------------------------------------------------------
# CLI Command
# ---------------------------------------------------------------------------

@app.command()
def place_order(
    symbol: str = typer.Option(
        ...,
        "--symbol", "-s",
        help="Trading symbol, e.g. BTCUSDT, ETHUSDT",
        show_default=False,
    ),
    side: str = typer.Option(
        ...,
        "--side",
        help="Order side: BUY or SELL",
        show_default=False,
    ),
    order_type: str = typer.Option(
        ...,
        "--type", "-t",
        help="Order type: MARKET (instant fill) or LIMIT (at a specific price)",
        show_default=False,
    ),
    quantity: float = typer.Option(
        ...,
        "--quantity", "-q",
        help="Order quantity, e.g. 0.001 for BTC",
        show_default=False,
    ),
    price: Optional[float] = typer.Option(
        None,
        "--price", "-p",
        help="Limit price -- required for LIMIT and STOP_LIMIT orders, ignored for MARKET",
        show_default=False,
    ),
    stop_price: Optional[float] = typer.Option(
        None,
        "--stop-price",
        help="Trigger price -- required for STOP_LIMIT orders only. "
             "When market hits this price, a limit order at --price is placed.",
        show_default=False,
    ),
)  -> None:
    """
    Place a MARKET, LIMIT, or STOP_LIMIT order on Binance Futures Testnet (USDT-M).

    \b
    Examples:
      Market BUY:
        python -m bot.cli --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001

      Limit SELL:
        python -m bot.cli --symbol BTCUSDT --side SELL --type LIMIT --quantity 0.001 --price 60000

      Stop-Limit SELL (stop-loss on a long):
        python -m bot.cli --symbol BTCUSDT --side SELL --type STOP_LIMIT \
          --quantity 0.001 --stop-price 80000 --price 79500

    \b
    Credentials:
      Set BINANCE_API_KEY and BINANCE_API_SECRET in your .env file.
      Copy .env.example to .env and fill in your testnet credentials.
    """
    logger.debug(
        "[CLI] place-order called: symbol=%s side=%s type=%s quantity=%s price=%s stop_price=%s",
        symbol, side, order_type, quantity, price, stop_price,
    )

    # ── Step 1: Validate all inputs ──────────────────────────────────────
    validation = validate_all(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        stop_price=stop_price,
    )

    if not validation.is_valid:
        _print_validation_errors(validation.errors, validation.warnings)
        logger.warning("[CLI] Validation failed: %s", validation.errors)
        sys.exit(1)

    # Show warnings even on success (e.g., price ignored for MARKET)
    _print_warnings(validation.warnings)

    # ── Step 2: Print pre-submission summary ─────────────────────────────
    _print_request_summary(
        symbol     = validation.symbol,
        side       = validation.side,
        order_type = validation.order_type,
        quantity   = validation.quantity,   # type: ignore[arg-type]
        price      = validation.price,
        stop_price = validation.stop_price,
    )

    # ── Step 3: Place the order ──────────────────────────────────────────
    try:
        client  = BinanceFuturesClient()
        manager = OrderManager(client)

        if validation.order_type == "MARKET":
            result = manager.place_market_order(
                symbol   = validation.symbol,
                side     = validation.side,
                quantity = validation.quantity,  # type: ignore[arg-type]
            )
        elif validation.order_type == "LIMIT":
            result = manager.place_limit_order(
                symbol   = validation.symbol,
                side     = validation.side,
                quantity = validation.quantity,  # type: ignore[arg-type]
                price    = validation.price,     # type: ignore[arg-type]
            )
        else:  # STOP_LIMIT
            result = manager.place_stop_limit_order(
                symbol     = validation.symbol,
                side       = validation.side,
                quantity   = validation.quantity,   # type: ignore[arg-type]
                price      = validation.price,      # type: ignore[arg-type]
                stop_price = validation.stop_price,  # type: ignore[arg-type]
            )

    except ConfigurationError as exc:
        _print_error(
            title="Configuration Error",
            message=str(exc),
            hint="Run: cp .env.example .env  — then add your Binance Testnet API credentials.",
        )
        logger.error("[CLI] ConfigurationError: %s", exc)
        sys.exit(1)

    except AuthenticationError as exc:
        _print_error(
            title="Authentication Failed",
            message=str(exc),
            hint=(
                "Double-check your BINANCE_API_KEY and BINANCE_API_SECRET in .env.\n"
                "Make sure you're using Testnet credentials from https://testnet.binancefuture.com"
            ),
        )
        logger.error("[CLI] AuthenticationError: %s", exc)
        sys.exit(1)

    except APIError as exc:
        _print_error(
            title="Binance API Error",
            message=str(exc),
            hint="Check the symbol, quantity, and price. See logs/trading_bot.log for full details.",
        )
        logger.error("[CLI] APIError code=%s status=%s: %s", exc.code, exc.status, exc)
        sys.exit(1)

    except NetworkError as exc:
        _print_error(
            title="Network Error",
            message=str(exc),
            hint="Check your internet connection and verify the base URL in .env.",
        )
        logger.error("[CLI] NetworkError: %s", exc)
        sys.exit(1)

    except Exception as exc:  # noqa: BLE001
        _print_error(
            title="Unexpected Error",
            message=f"An unexpected error occurred: {exc}",
            hint="Please check logs/trading_bot.log for the full stack trace.",
        )
        logger.exception("[CLI] Unexpected error: %s", exc)
        sys.exit(1)

    # ── Step 4: Print success response ───────────────────────────────────
    _print_order_response(result)
    console.print(
        Panel(
            f"[bold green]Order placed successfully on Binance Futures Testnet![/bold green]\n"
            f"[dim]Order ID: {result.order_id} | Status: {result.status}[/dim]",
            border_style="green",
            title_align="left",
        )
    )
    logger.info(
        "[CLI] Order completed successfully. orderId=%s status=%s",
        result.order_id, result.status,
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
