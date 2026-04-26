"""
ETH/USDT Paper Trading Monitor — Phase 2 (EXP016A)

Single-asset live signal scanner + paper trading engine.

Asset     : ETH/USDT (longs + shorts)
Timeframes: 15m (entry trigger) + 1h (trend context)
Strategy  : EXP002 pullback continuation — EXP016A: SL≥0.50% (fee/edge fix)
Risk      : 1% equity per trade (fixed, same as backtest)

Usage:
    python paper_monitor.py           → single scan, then exit
    python paper_monitor.py --loop    → continuous loop (every SCAN_INTERVAL seconds)

No real orders are placed. Paper simulation only.

Log format:
    [OPEN]   ETH/USDT LONG  | ts=... | entry=... | sl=... | tp=...
    [STATUS] LONG ETH/USDT  | entry=... | current=... | progress_to_tp=...% | time_in_trade=...
    [CLOSE]  ETH/USDT LONG  | entry=... | exit=... | reason=TP/SL | fee=... | net=... | equity=...
"""

import argparse
import time
from datetime import datetime, timezone

from core.exchange import create_exchange, fetch_ohlcv
from core.strategy_pullback import (
    prepare_1h,
    prepare_15m,
    align_1h_to_15m,
    get_trend,
    is_trend_strong,
    is_pullback_quality,
    is_entry_trigger,
    is_candle_quality,
    is_range_sufficient,
    is_market_efficient,
)
from core.trade_logic import calculate_sl_tp
from core.paper_engine import PaperEngine
from core.logger_v2 import setup_logger, log_open, log_close

# ── Config ────────────────────────────────────────────────────────────────────
ASSET            = 'ETH/USDT'
CANDLE_LIMIT_1H  = 260   # EMA50 warmup (50) + slope lookback (5) + alignment buffer
CANDLE_LIMIT_15M = 150   # avg_range window (5) + alignment + buffer
RISK_PCT         = 0.01  # 1% equity risked per trade
MIN_RISK_PRICE   = 1.0   # minimum SL distance in USD (avoids degenerate sizing)
MIN_SL_DIST_PCT  = 0.0050  # EXP016A: SL≥0.50% cubre el fee Taker (0.05%/lado)
SCAN_INTERVAL    = 30    # seconds between full scans


# ── Per-asset scan ────────────────────────────────────────────────────────────

def scan_asset(
    exchange,
    asset: str,
    engine: PaperEngine,
    logger,
    last_candle_ts: dict,
) -> None:
    """Fetch, compute indicators, check EXP016A signal for ETH/USDT."""

    # ── Fetch closed candles ──────────────────────────────────────────────────
    df_1h_raw  = fetch_ohlcv(exchange, asset, '1h',  CANDLE_LIMIT_1H)
    df_15m_raw = fetch_ohlcv(exchange, asset, '15m', CANDLE_LIMIT_15M)

    if df_1h_raw.empty or df_15m_raw.empty:
        logger.info(f"[{asset}] Data fetch failed — skipping.")
        return

    # Drop last row: it is the currently-forming candle, not yet closed.
    df_1h_raw  = df_1h_raw.iloc[:-1]
    df_15m_raw = df_15m_raw.iloc[:-1]

    if len(df_1h_raw) < 60 or len(df_15m_raw) < 10:
        logger.info(f"[{asset}] Insufficient closed candles — skipping.")
        return

    # exchange.py returns timestamp as index; strategy modules expect open_time column
    df_1h_raw  = df_1h_raw.reset_index().rename(columns={'timestamp': 'open_time'})
    df_15m_raw = df_15m_raw.reset_index().rename(columns={'timestamp': 'open_time'})

    # ── Compute indicators ────────────────────────────────────────────────────
    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)

    if df.empty:
        logger.info(f"[{asset}] Alignment produced empty frame — skipping.")
        return

    row         = df.iloc[-1]
    candle_time = str(row['open_time'])

    # ── Check exit for any open position first (runs every scan, not just new candles) ──
    if engine.has_position(asset):
        trade = engine.check_and_close(asset, row)
        if trade is not None:
            log_close(
                logger,
                asset,
                trade['direction'],
                trade['entry'],
                trade['exit'],
                trade['reason'],
                trade['pnl'],
                engine.equity,
                fee_usd=trade.get('fee_usd', 0.0),
            )
        else:
            engine.log_status(logger, asset, row['close'], row['high'], row['low'])

        # After an exit, update seen candle and return — never enter same bar as exit
        last_candle_ts[asset] = candle_time
        return

    # ── Dedup: skip entry logic if this candle was already processed ──────────
    if last_candle_ts.get(asset) == candle_time:
        return

    last_candle_ts[asset] = candle_time

    # ── EXP016A entry filters (all must pass) ─────────────────────────────────
    trend = get_trend(row)
    if trend is None:
        return

    if not is_trend_strong(row):
        return

    if not is_pullback_quality(row, trend):
        return

    if not is_entry_trigger(row, trend):
        return

    if not is_candle_quality(row, trend):
        return

    if not is_range_sufficient(row):
        return

    if not is_market_efficient(row):
        return

    # ── Signal confirmed — size and open paper position ───────────────────────
    entry     = row['close']
    direction = 'long' if trend == 'up' else 'short'

    sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
    if sl is None:
        return

    risk_price = abs(entry - sl)
    if risk_price < MIN_RISK_PRICE:
        return

    # EXP016A: reject entries where SL < 0.50% — required to cover Taker fees
    if risk_price / entry < MIN_SL_DIST_PCT:
        logger.info(f"[{asset}] SKIP sl_dist={risk_price/entry*100:.3f}% < {MIN_SL_DIST_PCT*100:.2f}% (EXP016A)")
        return

    risk_usd = engine.equity * RISK_PCT
    qty      = risk_usd / risk_price

    engine.open_position(
        asset=asset,
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        qty=qty,
        ts=candle_time,
        risk_usd=risk_usd,
    )
    log_open(logger, asset, direction, candle_time, entry, sl, tp)


# ── Scan loop ─────────────────────────────────────────────────────────────────

def run_scan(exchange, engine: PaperEngine, logger, last_candle_ts: dict) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    logger.info(f"\n[SCAN] {ts}")
    try:
        scan_asset(exchange, ASSET, engine, logger, last_candle_ts)
    except Exception as e:
        logger.info(f"[{ASSET}] ERROR: {e}")
    engine.print_summary(logger)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='EXP002 Paper Trading Monitor')
    parser.add_argument(
        '--loop',
        action='store_true',
        help=f'Run continuously, scanning every {SCAN_INTERVAL}s',
    )
    args = parser.parse_args()

    log_date = datetime.now(timezone.utc).strftime('%Y%m%d')
    logger   = setup_logger(
        'paper_monitor',
        log_file=f'logs/eth_{log_date}.log',
        mode='a',   # append — restarts do not wipe the day's log
    )

    exchange         = create_exchange()
    engine           = PaperEngine()
    last_candle_ts: dict = {}

    if not args.loop:
        run_scan(exchange, engine, logger, last_candle_ts)
        return

    logger.info(f"[MONITOR] ETH/USDT paper trading started — EXP016A (SL≥0.50%)")
    logger.info(f"[MONITOR] Asset: {ASSET} | Risk: {RISK_PCT*100:.0f}% | SL_min: {MIN_SL_DIST_PCT*100:.2f}% | Interval: {SCAN_INTERVAL}s")

    while True:
        current_date = datetime.now(timezone.utc).strftime('%Y%m%d')
        if current_date != log_date:
            log_date = current_date
            logger = setup_logger(
                'paper_monitor',
                log_file=f'logs/eth_{log_date}.log',
                mode='a',
            )
            logger.info(f"[MONITOR] Log rotated — new day: {log_date}")

        run_scan(exchange, engine, logger, last_candle_ts)
        time.sleep(SCAN_INTERVAL)


if __name__ == '__main__':
    main()
