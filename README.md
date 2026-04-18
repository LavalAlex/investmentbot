# InvestmentBot — BTC/ETH Paper Trading System

Pullback continuation strategy on BTC/USDT and ETH/USDT.
Read-only market data via Binance. No real orders are placed.

**Current phase:** Phase 2 — Paper Trading

---

## Project structure

```
├── paper_monitor.py        # monitor loop (entry signal scanner + paper engine)
├── config.py               # loads credentials from .env
├── fetch_history.py        # downloads historical OHLCV data from Binance
├── reset_paper_logs.py     # resets paper_state.json and clears daily logs
│
├── core/                   # trading engine
│   ├── exchange.py         # Binance CCXT connector (read-only)
│   ├── indicators_v2.py    # EMA, slope, Kaufman Efficiency Ratio
│   ├── logger_v2.py        # logger setup + log_open / log_close helpers
│   ├── paper_engine.py     # paper position management (JSON persistence)
│   ├── strategy_pullback.py# all signal and filter logic (EXP002)
│   └── trade_logic.py      # SL/TP calculation and exit detection
│
├── backtest/               # experiment runners
│   ├── backtest_v2.py      # baseline framework (EXP001)
│   └── backtest_exp002.py … backtest_exp010.py
│
├── api/
│   └── main.py             # FastAPI server — also starts the monitor on launch
│
├── experiments/            # research notes and experiment results (markdown)
├── archive/                # deprecated v1 code (not used)
│
├── data/                   # historical CSVs and backtest JSONs (gitignored)
├── logs/                   # daily paper trading logs (gitignored)
└── paper_state.json        # live paper trading state (gitignored)
```

---

## Setup

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create `.env` in project root

```bash
BINANCE_API_KEY=your_key_here
BINANCE_SECRET=your_secret_here
```

The Binance key only needs **read permissions** — no trading access required.

---

## Running

### Deploy (monitor + API in one command)

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

This starts the FastAPI server **and** launches the paper trading monitor automatically in a background thread. The monitor scans BTC/USDT and ETH/USDT every 30 seconds and appends to a daily log file.

### Monitor only (no API)

```bash
# single scan then exit
python paper_monitor.py

# continuous loop
python paper_monitor.py --loop
```

### Reset paper trading state

Run this before starting a new paper trading session. **Stop the monitor first.**

```bash
python reset_paper_logs.py
```

---

## Deploy to Google Cloud (GCE)

Google Compute Engine is recommended over Cloud Run for this project because the monitor is a long-running stateful process. Cloud Run scales to zero and has an ephemeral filesystem — logs and paper state would be lost on restart.

### 1. Build and push the image

```bash
# Authenticate
gcloud auth configure-docker

# Build and tag  (replace PROJECT_ID)
docker build -t gcr.io/PROJECT_ID/investmentbot .
docker push gcr.io/PROJECT_ID/investmentbot
```

### 2. Create the VM (first time only)

```bash
gcloud compute instances create-with-container investmentbot \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --container-image=gcr.io/PROJECT_ID/investmentbot \
  --container-env=BINANCE_API_KEY=your_key,BINANCE_SECRET=your_secret \
  --container-mount-host-path=mount-path=/app/logs,host-path=/var/investmentbot/logs \
  --container-mount-host-path=mount-path=/app/paper_state.json,host-path=/var/investmentbot/paper_state.json \
  --tags=http-server
```

The host-path mounts keep logs and state on the VM's persistent disk — they survive container restarts and redeployments.

### 3. Open the API port

```bash
gcloud compute firewall-rules create allow-investmentbot \
  --allow tcp:8080 \
  --target-tags http-server
```

The API is then reachable at `http://EXTERNAL_IP:8080`.

### 4. Redeploy after code changes

```bash
docker build -t gcr.io/PROJECT_ID/investmentbot .
docker push gcr.io/PROJECT_ID/investmentbot

gcloud compute instances update-container investmentbot \
  --zone=us-central1-a \
  --container-image=gcr.io/PROJECT_ID/investmentbot
```

The container restarts automatically. Logs and state on the host disk are preserved.

### 5. Check logs from your machine

```bash
# SSH into the VM
gcloud compute ssh investmentbot --zone=us-central1-a

# Tail the current day's log
tail -f /var/investmentbot/logs/paper_$(date -u +%Y%m%d).log
```

---

## API endpoints

Base URL: `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs`

---

### `GET /status`

Current equity, trade statistics, open positions, and last scan timestamp.

```bash
curl http://localhost:8000/status
```

```json
{
  "equity": 10000.00,
  "return_pct": 0.00,
  "total_pnl": 0,
  "total_trades": 0,
  "wins": 0,
  "losses": 0,
  "win_rate_pct": null,
  "profit_factor": null,
  "open_positions": {},
  "last_scan": "2026-04-18T13:08:18+00:00"
}
```

---

### `GET /logs/latest`

Last scan block from the most recent log file — signals fired, position status, and daily summary.

```bash
curl http://localhost:8000/logs/latest
```

```json
{
  "file": "paper_20260418.log",
  "last_scan": "[SCAN] 2026-04-18T13:08:18+00:00\n..."
}
```

---

### `GET /logs/download`

Download log file(s) for a specific day or date range.

**Single day** — returns a `.txt` file:
```bash
curl "http://localhost:8000/logs/download?date=2026-04-18" -o log.txt
```

**Date range** — returns a `.zip` if more than one file exists:
```bash
curl "http://localhost:8000/logs/download?from=2026-04-15&to=2026-04-18" -o logs.zip
```

---

## Backtesting

### Fetch historical data

Downloads OHLCV data from Binance and saves CSVs to `data/`:

```bash
python fetch_history.py
```

### Run an experiment

```bash
python backtest/backtest_exp002.py   # EXP002 — validated baseline
python backtest/backtest_exp009.py   # EXP009 — BTC longs only
```

Results are saved to `data/backtest_*.json` and `data/equity_curve_*.csv`.

---

## Strategy summary (EXP002 + EXP007 + EXP009)

**Family:** Pullback continuation
**Timeframes:** 1h (trend context) + 15m (entry trigger)
**Assets:** BTC/USDT (longs only), ETH/USDT (longs and shorts)
**Risk:** 1% of equity per trade, R:R = 2:1

Entry requires all filters to pass:

| Filter | Description |
|---|---|
| EMA20 slope 1h | Trend direction (up or down) |
| EMA50 strength | Trend must be moving, price ≥ 0.5% from EMA50 |
| Structural pullback | 1h bar touched EMA20 within 0.2% without collapsing |
| 15m trigger candle | Candle direction confirms trend continuation |
| Body ratio ≥ 60% | Rejects dojis and indecision candles |
| Range floor ≥ 0.1% | Rejects compressed / near-zero volatility conditions |
| Kaufman ER ≥ 0.15 | Rejects choppy, non-directional markets |
| SL distance ≥ 0.15% | Rejects compressed trigger candles (EXP007) |

---

## Logs

Daily log files are written to `logs/paper_YYYYMMDD.log` (UTC dates).
A new file is created automatically at midnight UTC without restarting the monitor.

Log format:
```
[SCAN]  2026-04-18T13:08:18+00:00
[OPEN]  LONG  | ts=... | entry=84500.00 | sl=84000.00 | tp=85500.00
[STATUS] LONG BTC/USDT | entry=84500.00 | current=84800.00 | progress_to_tp=+60.0%
[CLOSE] LONG  | entry=84500.00 | exit=85500.00 | reason=TP | net=+100.00 USD
```
