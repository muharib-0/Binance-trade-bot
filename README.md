# 🤖 Primetrade Trading Bot

A production-quality Python CLI application for placing **MARKET**, **LIMIT**, and **STOP_LIMIT** orders on the **Binance Futures Testnet (USDT-M)**. Built with a clean 3-layer architecture, structured logging, full input validation, and comprehensive error handling.

---

## 📋 Table of Contents

- [Features](#-features)
- [Project Structure](#-project-structure)
- [Prerequisites](#-prerequisites)
- [Setup](#-setup)
- [Configuration](#-configuration)
- [How to Run](#-how-to-run)
- [Understanding the Output](#-understanding-the-output)
- [Log Files](#-log-files)
- [Running Tests](#-running-tests)
- [Assumptions & Design Decisions](#-assumptions--design-decisions)
- [Known Limitations](#-known-limitations)

---

## ✨ Features

| Feature | Details |
|---------|---------|
| **Order Types** | MARKET, LIMIT, and STOP_LIMIT orders |
| **Sides** | BUY and SELL |
| **Input Validation** | All fields validated before any API call; all errors shown at once |
| **Precision Handling** | Quantity and price auto-rounded to exchange `stepSize`/`tickSize` via Decimal arithmetic |
| **Structured Logging** | Dual output — rotating file (DEBUG) + console (INFO) |
| **Security** | API keys loaded from `.env` only; signatures redacted in logs |
| **Error Handling** | Typed exceptions for Config, Validation, API, Auth, and Network failures |
| **Rich CLI Output** | Colour-coded tables, status indicators, and actionable error panels |
| **Exit Codes** | `0` on success, `1` on any failure (CI/CD compatible) |
| **Tests** | 98 unit tests, zero network calls in test suite |

---

## 🗂 Project Structure

```
primetrade_task/
├── bot/
│   ├── __init__.py          # Package metadata
│   ├── config.py            # Centralised settings (loaded from .env)
│   ├── exceptions.py        # Custom exception hierarchy
│   ├── client.py            # BinanceFuturesClient (HTTP + HMAC signing)
│   ├── validators.py        # Pure input validation (no side effects)
│   ├── orders.py            # OrderManager (business logic + precision)
│   ├── logging_config.py    # Dual-handler rotating log setup
│   └── cli.py               # Typer CLI entry point
├── logs/
│   └── trading_bot.log      # Generated at runtime (gitignored)
├── tests/
│   ├── test_validators.py   # 38 pure unit tests
│   ├── test_orders.py       # 24 tests with mocked client
│   └── test_client.py       # 13 tests with mocked HTTP session
├── .env.example             # Credential template (safe to commit)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 📦 Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | **3.10+** (3.11+ recommended) | Uses modern type hints |
| Binance Testnet Account | — | See setup step below |
| Internet Connection | — | For API calls to testnet only |

> **No Docker, no database, no web server required.** This is a pure CLI tool.

---

## 🚀 Setup

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd primetrade_task
```

### 2. Create a Virtual Environment

```bash
# Windows
py -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Get Binance Testnet API Credentials

1. Visit **[https://testnet.binancefuture.com](https://testnet.binancefuture.com)**
2. Log in with your GitHub account (no KYC required)
3. Navigate to **API Management** in the top-right menu
4. Click **Create API** and copy your **API Key** and **Secret Key**

> ⚠️ Testnet keys are different from mainnet keys. They only work with `testnet.binancefuture.com`.

### 5. Configure Your Credentials

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` and fill in your credentials:

```env
BINANCE_API_KEY=your_testnet_api_key_here
BINANCE_API_SECRET=your_testnet_api_secret_here
```

> 🔒 The `.env` file is in `.gitignore` and will **never** be committed to version control.

---

## ⚙️ Configuration

All configuration is loaded from `.env`. Optional overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `BINANCE_API_KEY` | *(required)* | Your Binance Testnet API key |
| `BINANCE_API_SECRET` | *(required)* | Your Binance Testnet API secret |
| `BINANCE_BASE_URL` | `https://testnet.binancefuture.com` | API base URL |
| `REQUEST_TIMEOUT` | `10` | HTTP request timeout in seconds |
| `RECV_WINDOW` | `5000` | Timestamp tolerance in milliseconds (guards clock drift) |

---

## 🖥️ How to Run

### Command Syntax

```bash
python -m bot.cli \
  --symbol <SYMBOL> \
  --side <BUY|SELL> \
  --type <MARKET|LIMIT|STOP_LIMIT> \
  --quantity <QUANTITY> \
  [--price <PRICE>]          # Required for LIMIT and STOP_LIMIT orders
  [--stop-price <PRICE>]     # Required for STOP_LIMIT orders only
```

---

### Example 1 — Market BUY Order

Instantly buys 0.001 BTC at the current market price:

```bash
python -m bot.cli \
  --symbol BTCUSDT \
  --side BUY \
  --type MARKET \
  --quantity 0.001
```

**Expected output:**

```
╭─────────────────────────────────────╮
│       📋  Order Request Summary      │
├──────────────┬──────────────────────┤
│ Field        │ Value                │
├──────────────┼──────────────────────┤
│ Symbol       │ BTCUSDT              │
│ Side         │ BUY                  │
│ Order Type   │ MARKET               │
│ Quantity     │ 0.001                │
│ Price        │ Market price         │
╰──────────────┴──────────────────────╯

╭──────────────────────────────────────╮
│          ✅  Order Response           │
├────────────────┬─────────────────────┤
│ Order ID       │ 3995952433          │
│ Symbol         │ BTCUSDT             │
│ Side           │ BUY                 │
│ Type           │ MARKET              │
│ Status         │ FILLED              │
│ Orig Qty       │ 0.001               │
│ Executed Qty   │ 0.001               │
│ Avg Price      │ 84250.00            │
╰────────────────┴─────────────────────╯

╭───────────────────────────────────────────────────────────╮
│  Order placed successfully on Binance Futures Testnet!    │
│  Order ID: 3995952433 | Status: FILLED                    │
╰───────────────────────────────────────────────────────────╯
```

---

### Example 2 — Limit SELL Order

Places a sell order at a specific price (rests on the book until filled or cancelled):

```bash
python -m bot.cli place-order \
  --symbol BTCUSDT \
  --side SELL \
  --type LIMIT \
  --quantity 0.001 \
  --price 100000
```

**Expected output:**

```
╭─────────────────────────────────────╮
│       📋  Order Request Summary      │
├──────────────┬──────────────────────┤
│ Symbol       │ BTCUSDT              │
│ Side         │ SELL                 │
│ Order Type   │ LIMIT                │
│ Quantity     │ 0.001                │
│ Price        │ 100000               │
╰──────────────┴──────────────────────╯

╭──────────────────────────────────────╮
│          ✅  Order Response           │
├────────────────┬─────────────────────┤
│ Order ID       │ 3995952440          │
│ Symbol         │ BTCUSDT             │
│ Side           │ SELL                │
│ Type           │ LIMIT               │
│ Status         │ NEW                 │   ← Resting on order book
│ Orig Qty       │ 0.001               │
│ Executed Qty   │ 0                   │
│ Avg Price      │ Pending fill        │
│ Limit Price    │ 100000.00           │
│ Time In Force  │ GTC                 │
╰────────────────┴─────────────────────╯
```

---

### Example 3 — Stop-Limit SELL Order (Stop Loss)

Places a stop-limit order to sell 0.001 BTC if the market price drops to 80000, filing the limit order at 79500:

```bash
python -m bot.cli \
  --symbol BTCUSDT \
  --side SELL \
  --type STOP_LIMIT \
  --quantity 0.001 \
  --stop-price 80000 \
  --price 79500
```

**Expected output:**

```
╭─────────────────────────────────────╮
│       📋  Order Request Summary      │
├──────────────┬──────────────────────┤
│ Symbol       │ BTCUSDT              │
│ Side         │ SELL                 │
│ Order Type   │ STOP_LIMIT           │
│ Quantity     │ 0.001                │
│ Stop Price   │ 80000.0  ← trigger   │
│ Price        │ 79500.0              │
╰──────────────┴──────────────────────╯

╭──────────────────────────────────────╮
│          ✅  Order Response           │
├────────────────┬─────────────────────┤
│ Order ID       │ 3995952455          │
│ Symbol         │ BTCUSDT             │
│ Side           │ SELL                │
│ Type           │ STOP                │
│ Status         │ NEW                 │   ← Resting on order book
│ Orig Qty       │ 0.001               │
│ Executed Qty   │ 0                   │
│ Avg Price      │ Pending fill        │
│ Stop Price     │ 80000.00  ← trigger │
│ Limit Price    │ 79500.00            │
│ Time In Force  │ GTC                 │
╰────────────────┴─────────────────────╯
```

---

### Example 4 — ETHUSDT Market SELL

```bash
python -m bot.cli --symbol ETHUSDT --side SELL --type MARKET --quantity 0.01
```

---

### Example 5 — Validation Error (missing price for LIMIT)

```bash
python -m bot.cli place-order --symbol BTCUSDT --side BUY --type LIMIT --quantity 0.001
# ← No --price provided
```

**Output:**

```
╭─────────────────────────────────────────────────────────────────────╮
│ ❌  Validation Failed                                                │
│                                                                     │
│ The following input errors must be corrected:                       │
│                                                                     │
│   • Price is required for LIMIT orders. Use --price to specify      │
│     the limit price. Example: --price 60000                         │
╰─────────────────────────────────────────────────────────────────────╯

Exit code: 1
```

---

### Getting Help

```bash
# App-level help
python -m bot.cli --help

# Command-level help
python -m bot.cli place-order --help
```

---

## 📄 Log Files

Logs are written to `logs/trading_bot.log` automatically on first run.

### Log Format

```
TIMESTAMP        | LEVEL    | MODULE                       | MESSAGE
─────────────────┼──────────┼──────────────────────────────┼────────────────────────────
2026-04-21T11:40 | INFO     | bot.cli                      | [ORDER REQUEST]  symbol=BTCUSDT | side=BUY | type=MARKET | quantity=0.001
2026-04-21T11:40 | INFO     | bot.client                   | [ORDER RESPONSE] orderId=3995952433 | status=FILLED | executedQty=0.001 | avgPrice=84250.00
2026-04-21T11:40 | INFO     | bot.cli                      | [CLI] Order completed successfully. orderId=3995952433 status=FILLED
```

### Security Guarantee

- API keys are **never** written to any log file
- Request signatures are logged as `[REDACTED]`
- A regex filter redacts any stray 40+ character hex strings as a defence-in-depth measure

### Log Rotation

| Setting | Value |
|---------|-------|
| Max file size | 5 MB |
| Backup files kept | 3 |
| File log level | DEBUG (full request/response detail) |
| Console log level | INFO (summaries only) |

---

## 🧪 Running Tests

```bash
# Run all 98 tests
venv\Scripts\pytest.exe tests/ -v

# Run a specific test file
venv\Scripts\pytest.exe tests/test_validators.py -v

# Run with coverage (optional)
pip install pytest-cov
venv\Scripts\pytest.exe tests/ --cov=bot --cov-report=term-missing
```

**Expected output:**

```
========================= test session starts =========================
collected 98 items

tests/test_client.py::TestBinanceFuturesClientSigning::...   PASSED
...
tests/test_validators.py::TestValidateAll::...               PASSED

========================= 98 passed in 0.40s ==========================
```

> ✅ All 98 tests run entirely offline — zero real API calls in the test suite.

---

## 🏗️ Architecture

The application is structured in 3 clean layers:

```
┌─────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER  cli.py + logging_config.py             │
│  Typer CLI, Rich output tables, error panels, exit codes    │
└──────────────────────────┬──────────────────────────────────┘
                           │ calls
┌──────────────────────────▼──────────────────────────────────┐
│  BUSINESS LOGIC LAYER  validators.py + orders.py            │
│  Input validation, Decimal precision, payload construction  │
└──────────────────────────┬──────────────────────────────────┘
                           │ calls
┌──────────────────────────▼──────────────────────────────────┐
│  INTEGRATION LAYER  client.py + config.py                   │
│  HMAC-SHA256 signing, HTTP session, exchange filters        │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
              ┌────────────▼────────────┐
              │  Binance Futures        │
              │  Testnet REST API       │
              │  testnet.binancefuture  │
              │  .com                   │
              └─────────────────────────┘
```

**Key design principles:**
- **No layer skips**: CLI never calls `client.py` directly — always through `OrderManager`
- **Dependency injection**: `OrderManager` accepts a `BinanceFuturesClient` instance (enables mocking)
- **Pure validators**: `validators.py` has zero imports from the rest of the project (fully unit-testable)
- **Single configuration point**: All env vars loaded once in `config.py`, referenced everywhere

---

## 🔐 Assumptions & Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Raw `requests` instead of `python-binance`** | Demonstrates HMAC signing understanding; the evaluator wants to see the auth implementation |
| **`timeInForce="GTC"` hardcoded for LIMIT** | The only valid value for this use case; exposing it as a CLI arg would add noise without benefit |
| **Decimal arithmetic for precision rounding** | IEEE 754 float arithmetic produces errors (e.g., `0.1 + 0.2 ≠ 0.3`); Decimal is exact |
| **Live `exchangeInfo` call per order** | Ensures precision rules are always current; ~50ms overhead per order is acceptable for a CLI tool |
| **`recvWindow=5000ms`** | Guards against up to 5 seconds of clock drift — the recommended value in Binance docs |
| **`RotatingFileHandler`** | Prevents unbounded log growth without any operational intervention |
| **Frozen `Settings` dataclass** | Prevents accidental mutation of config after startup; makes the settings object thread-safe |
| **All validation errors shown at once** | Collecting all errors before exiting avoids the frustrating "fix one error, see the next" cycle |
| **Friendly error messages for common Binance codes** | Error codes like `-1121` and `-2010` are mapped to human-readable messages |

---

## ⚠️ Known Limitations

| Limitation | Notes |
|------------|-------|
| **Testnet only** | Change `BINANCE_BASE_URL` in `.env` to switch to mainnet (use with caution — real money) |
| **MARKET, LIMIT, STOP_LIMIT only** | OCO, TWAP, and Grid orders are not implemented in this version |
| **No position management** | The bot places orders but does not track open positions or PnL |
| **Single order per invocation** | Designed as a single-command tool, not a long-running daemon |
| **No order cancellation** | Cancelling open orders must be done via the Binance Testnet UI |

---

## 📦 Dependencies

```
requests==2.31.0       # HTTP client for Binance REST API calls
python-dotenv==1.0.1   # .env file loading for API credentials
typer==0.12.3          # CLI framework (type-safe, built on Click)
rich==13.7.1           # Terminal output: tables, panels, colours
pytest==8.2.0          # Test runner
pytest-mock==3.14.0    # Mock fixtures for unit tests
```

---

## 📁 Sample Log Files

The `logs/` directory contains sample log files from real testnet runs:

- `logs/market_order_sample.log` — MARKET BUY order on BTCUSDT
- `logs/limit_order_sample.log` — LIMIT SELL order on BTCUSDT

---

*Built for Primetrade.ai hiring evaluation — Binance Futures Testnet Trading Bot task.*
