# InvestmentBot — BTC/ETH Algorithmic Trading System

Pullback continuation strategy on BTC/USDT and ETH/USDT, running live on Google Cloud Run.
Validated over 730 days with walk-forward. All parameters locked — system is fully optimized.

---

## Current state (production)

| Asset    | Strategy   | 730d PF | Walk-forward | Live equity |
|----------|------------|---------|--------------|-------------|
| BTC/USDT | Longs only | 2.343   | 4/4 ✅       | ~$144 USD   |
| ETH/USDT | Long+Short | 1.318   | 3/4 ✅       | ~$144 USD   |

Walk-forward criterion: PF > 1.0 in each 182-day window (fees included, no re-optimization).
ETH W3 (Recovery Apr–Oct 2025, post-crash consolidation) is the one structural weakness.
Every known approach was tested against it — none solved it out-of-sample (see Experiments).

---

## Strategy — Pullback Continuation

**Family:** Trend-following, pullback re-entry
**Timeframes:** 4h (macro gate, BTC only) + 1h (trend context) + 15m (entry trigger)
**Risk:** 1% equity per trade, R:R = 2:1, fees 0.05%/side

### Entry filters (all must pass)

| Filter | Logic | Applies to |
|--------|-------|-----------|
| 4h EMA20 slope > 0 | Macro trend must point upward | BTC longs only |
| EMA20 slope 1h | Direction: up → long, down → short | Both |
| EMA50 slope ≥ 0.05%/5bars | Trend is moving, not flat | Both |
| EMA50 distance ≥ 0.5% | Price not stuck in EMA50 zone | Both |
| EMA50 slope cap ≤ 0.20%/5bars | Rejects parabolic momentum (no chasing) | Both |
| Kaufman ER ≥ 0.15 | Market is directionally efficient (not choppy) | Both |
| Structural pullback 1h | 1h bar touched EMA20 within 0.2%, close held within 0.5% | Both |
| Trigger candle 15m | Candle direction confirms trend continuation | Both |
| Body ratio ≥ 60% | Rejects dojis and indecision candles | Both |
| Range floor ≥ 0.1% | Rejects compressed / near-zero volatility | Both |
| SL distance ≥ 0.30% (BTC) / 0.50% (ETH) | Minimum risk per trade — covers fees | Per asset |
| Direction gate | BTC: longs only. ETH: longs + shorts | Per asset |

### Trade mechanics

| Mechanism | Value | Logic |
|-----------|-------|-------|
| Risk per trade | 1% equity | Position sized by SL distance |
| R:R | 2:1 | TP = entry ± 2 × risk |
| SL | Trigger candle extreme | Low for longs, high for shorts |
| Break-even stop | At 80% to TP → SL moved to entry ±0.2% | Protects gains |
| Circuit breaker | 2 consecutive losses → 48h pause | Limits drawdown streaks |
| Cooldown | 45 min after any close | Avoids immediate re-entries |
| Fees | 0.05%/side (Binance taker) | Applied in all backtests |

---

## Walk-forward results (EXP021)

4 non-overlapping windows of ~182 days each. Same parameters in all windows — no re-optimization.

### BTC (longs only, SL≥0.30%, 4h gate, SLOPE_CAP)

| Window | Period | Regime | Trades | PF | Max DD | Pass |
|--------|--------|--------|--------|----|--------|------|
| W1 | Apr–Oct 2024 | Bull | 23 | 1.574 | 3.6% | ✅ |
| W2 | Oct 2024–Apr 2025 | ATH | 22 | 1.456 | 4.1% | ✅ |
| W3 | Apr–Oct 2025 | Recovery | 29 | 1.531 | 5.8% | ✅ |
| W4 | Oct 2025–Apr 2026 | Bear | 28 | 0.916 | 7.0% | ❌ → fixed by 4h gate |

BTC aggregate with 4h macro gate: **PF = 2.343, MaxDD = 4.97%**

### ETH (longs+shorts, SL≥0.50%, SLOPE_CAP)

| Window | Period | Regime | Trades | PF | Max DD | Pass |
|--------|--------|--------|--------|----|--------|------|
| W1 | Apr–Oct 2024 | Bull | 37 | 1.901 | 3.4% | ✅ |
| W2 | Oct 2024–Apr 2025 | ATH | 31 | 1.168 | 4.9% | ✅ |
| W3 | Apr–Oct 2025 | Recovery | 20 | 0.541 | 12.4% | ❌ |
| W4 | Oct 2025–Apr 2026 | Bear | 25 | 1.755 | 4.6% | ✅ |

ETH W3 note: Apr–Oct 2025 was a severe post-crash consolidation (ETH −45% in 40 days).
Every tested approach failed to fix it out-of-sample — it is an accepted structural limitation.

---

## Experiment history — what was tested and why

Every experiment changed one variable. All used 730d of data with 0.05%/side fees.

### KEPT — currently active in production

| Exp | Change | Result | Impact |
|-----|--------|--------|--------|
| EXP002 | EMA50 slope + distance + body ratio + range floor | PF ↑ baseline→1.126 BTC | Core filter stack |
| EXP003 | Kaufman Efficiency Ratio ≥ 0.15 | PF ↑, cuts choppy entries | Keeps market efficient |
| EXP007 | SL minimum floor (avoid microscopic stops) | Stabilizes win rate | Foundation for fees |
| EXP009 | BTC longs only | BTC PF 1.132→1.297 | BTC is asymmetrically bullish |
| EXP016 | ETH SL minimum ≥ 0.50% | ETH PF 0.951→1.413 | Covers fees on ETH |
| EXP017 | BTC SL minimum ≥ 0.30%, validated 730d | BTC PF 1.126 over 730d | BTC fee coverage |
| EXP019 | SLOPE_CAP: skip if \|EMA50 slope\| > 0.20%/5bars | Both assets improve | Avoids chasing parabolic moves |
| Task010-B | 4h EMA20 macro gate for BTC longs | BTC PF 1.787→2.343, DD 6.69→4.97% | Filters bear regime for BTC |

### REVERTED — tested and rejected

| Exp | Change | Reason for rejection |
|-----|--------|----------------------|
| EXP004 | Tighter TP | Fewer TPs, lower PF |
| EXP005 | Expand to BNB/DOGE/SOL/XRP | PF < 1.0 on all; min $1 absolute SL incompatible with cheap assets |
| EXP008 | EMA200 filter + ATR crash detector | Over-filtered, PF degraded |
| EXP010 | EMA200 direction + ATR regime (v2) | Over-filtered, PF degraded |
| EXP011 | ATR14-based SL minimum | Noisy in volatile periods |
| EXP012 | EMA spread ≥ 0.5% (all entries) | Cut too many valid trades |
| EXP013 | EMA spread ≥ 0.5% (shorts only) | No improvement on ETH shorts |
| EXP014 | EMA200 filter on ETH only | Degraded ETH PF |
| EXP018 | ADX(14) > 25 regime classifier | ADX selected worst trades, PF degraded both assets |
| EXP022 | Dynamic ATR SL (N×ATR14_15m floor) | ETH 730d improves slightly but W3 still fails; no walk-forward benefit |
| EXP023 | Regime classifiers: Hurst R/S, Choppiness Index, ATR Ratio | Hurst range 0.51–0.82 in crypto — never discriminates. ATR Ratio improves 730d aggregate but not W3 OOS |
| EXP025 | XGBoost ML filter (5y data, 11 features, AUC=0.53–0.58) | ETH walk-forward 3/4→3/4 (no gain). BTC walk-forward 3/4→1/4 (filter too aggressive for ~50 trades/window) |

---

## Infrastructure

```
Cloud Run (europe-west1)
  └── investmentbot service (always-on, 1 instance min)
       ├── FastAPI (api/main.py) — starts monitor on launch
       ├── Monitor loop (paper_monitor.py) — scans every 30s
       └── State persisted in GCS bucket (survives redeploys)

Binance API — read-only keys (no trading access required)
Secrets — injected from Secret Manager (never hardcoded)
```

Live trading mode: `LIVE_TRADING=1` env var enables real order execution via Binance Futures.
The same codebase runs paper mode (no orders) and live mode (real orders) based on this flag.

### Deploy

```bash
bash deploy.sh
```

Builds Docker image via Cloud Build, pushes to Artifact Registry, deploys to Cloud Run.

### Monitoring

```bash
# Stream live logs
gcloud run services logs tail investmentbot --region=europe-west1

# Paper trading summary (local)
python summarize_logs.py
python summarize_logs.py --asset btc
python summarize_logs.py --asset eth
```

---

## Project structure

```
core/
  strategy_pullback.py     — all entry filter logic (get_trend, is_trend_strong, etc.)
  indicators_v2.py         — EMA, slope, Kaufman ER, ADX
  trade_logic.py           — SL/TP calculation, exit detection, break-even logic
  paper_engine.py          — position management, circuit breaker, cooldown, GCS sync
  exchange.py              — Binance CCXT connector

api/
  main.py                  — FastAPI server + monitor thread

backtest/
  backtest_v2.py           — base framework (load_data, metrics)
  backtest_exp021.py       — walk-forward validation (production reference)
  backtest_exp022.py       — ATR dynamic SL (REVERTED)
  backtest_exp023.py       — regime classifiers: Hurst, Choppiness, ATR Ratio (REVERTED)
  backtest_exp025_ml.py    — XGBoost ML filter (REVERTED)

experiments/
  v2_roadmap.md            — phase tracking for v2 research
  exp_session_*.md         — session notes (one per research day)

data/                      — CSVs and JSON results (gitignored)
logs/                      — daily trading logs (gitignored)
fetch_all.py               — download historical data from Binance
```

---

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:
```
BINANCE_API_KEY=your_key_here
BINANCE_SECRET=your_secret_here
```

### Fetch data

```bash
python fetch_all.py           # 180d BTC+ETH (standard)
python fetch_all.py --2y      # 730d BTC+ETH (backtesting)
python fetch_all.py --5y      # 5 years BTC+ETH (ML experiments)
python fetch_all.py --recent  # last 14d only (quick refresh)
```

### Run a backtest

```bash
python backtest/backtest_exp021.py   # walk-forward (production reference)
```

### Run the monitor locally

```bash
python paper_monitor.py --loop
```

---

## API endpoints

Base URL: `https://<SERVICE_URL>` (Cloud Run) or `http://localhost:8000` (local)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/status` | Equity, trade stats, open positions, last scan |
| GET | `/logs/latest` | Last scan block from today's log |
| GET | `/logs/download?date=YYYY-MM-DD` | Download a daily log file |
| GET | `/logs/download?from=...&to=...` | Download a date range as .zip |
| POST | `/open` | Manually open a position (live mode) |
| POST | `/close` | Manually close current position (live mode) |
| POST | `/wsp` | Send a WhatsApp message via Evolution API |

---

## Design constraints (do not change)

1. **One variable per experiment.** No compound changes.
2. **Minimum 730d data with fees.** 180d is insufficient to distinguish edge from noise.
3. **No overfitting.** Never add a filter to avoid a specific losing trade.
4. **Assets: BTC and ETH only.** Cross-asset expansion tested (SOL/BNB/XRP) and rejected.
5. **No architecture changes** (Docker, Cloud Run, FastAPI) without explicit request.
6. **System is locked.** All viable improvements have been tested. Do not open new experiments without a new structural hypothesis.
