# Binance Signal Analysis System — Phase 1

Read-only market monitoring and signal analysis for Binance Spot. No orders are placed.

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Create a `.env` file in the project root:
   ```
   BINANCE_API_KEY=your_key_here
   BINANCE_SECRET=your_secret_here
   ```

## Running

**Single-run mode** — fetch, analyze, and write one snapshot per symbol, then exit:
```
python3 main.py
```

**Monitor mode** — loop continuously, writing a new snapshot each time a new candle closes:
```
python3 main.py --monitor
```

## Configuration (via `.env` or environment variables)

| Variable | Default | Description |
|---|---|---|
| `SYMBOLS` | `BTC/USDT` | Comma-separated Binance Spot symbols to monitor |
| `TIMEFRAME` | `1h` | Candle timeframe (e.g. `15m`, `1h`, `4h`, `1d`) |
| `CANDLE_LIMIT` | `100` | Number of candles to fetch per symbol |
| `MONITOR_INTERVAL_SECONDS` | `60` | Loop interval in monitor mode |
| `SNAPSHOT_DIR` | `logs` | Directory where JSON snapshots are written |

Example with multiple symbols and a 5-minute interval:
```
SYMBOLS=BTC/USDT,ETH/USDT MONITOR_INTERVAL_SECONDS=300 python3 main.py --monitor
```

## Output

Snapshots are written to `logs/` as JSON files named by symbol, timeframe, and candle close time:
```
logs/BTCUSDT_1h_20260321_140000.json
```

Each snapshot contains the signal (`BUY`, `SELL`, or `NO_TRADE`), confidence, trend, reasons, and risk notes.

---

## Historical data & backtesting (Stage A)

### Step 1 — Fetch historical data

Downloads the last 7 days of BTC/USDT 15m candles from Binance Spot and saves them locally:
```
python3 fetch_history.py
```

Output: `data/BTCUSDT_15m_last_7d.csv`

Fields saved: `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `quote_volume`, `trade_count`, `taker_buy_base_volume`, `taker_buy_quote_volume`

### Step 2 — Run the backtest

Runs the signal engine candle-by-candle over the saved dataset. No orders are placed.
```
python3 backtest.py
```

Or point to a different dataset:
```
python3 backtest.py --data data/BTCUSDT_15m_last_7d.csv
```

**Backtest rules:**
- Signal at candle `i` → execute at open of candle `i+1` (no lookahead bias)
- One open position at a time
- Enter on `BUY`; exit on `SELL` or `NO_TRADE`
- Open position at end of dataset is force-closed at last candle's close

**Output:** printed summary + `data/backtest_BTCUSDT_15m_last_7d.json` containing the full trade log and per-candle signal log.
