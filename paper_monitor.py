"""
Paper Trading Monitor — Phase 2 (EXP016A + EXP017-B)

Dual-asset live signal scanner + paper trading engine.

Assets:
  BTC/USDT — longs only  (EXP009 + EXP017-B: SL≥0.30%)
  ETH/USDT — longs+shorts (EXP016A: SL≥0.50%)

Timeframes: 15m (entry trigger) + 1h (trend context)
Strategy  : EXP002 pullback continuation
Risk      : 1% equity per trade (fixed, same as backtest)

Usage:
    python paper_monitor.py           → single scan, then exit
    python paper_monitor.py --loop    → continuous loop (every SCAN_INTERVAL seconds)

Log files: logs/btc_YYYYMMDD.log  and  logs/eth_YYYYMMDD.log
State files: btc_state.json  and  eth_state.json
"""

import argparse
import time
from datetime import datetime, timezone

import pandas as pd

from core.exchange import create_exchange, create_futures_exchange, create_public_exchange, fetch_ohlcv
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
from core.live_engine import LiveEngine
from core.logger_v2 import setup_logger, log_open, log_close
from core.notifier import notify_trade_open, notify_trade_close

# ── Per-asset configuration ───────────────────────────────────────────────────

ASSETS_CONFIG = {
    'BTC/USDT': {
        'state_file':      'btc_state.json',
        'log_prefix':      'btc',
        'min_sl_dist_pct': 0.0030,  # EXP017-B: SL≥0.30% (viable over 730d)
        'longs_only':      True,    # EXP009: BTC longs only
        'label':           'BTC/USDT (EXP009+EXP017-B, SL≥0.30%, longs only)',
    },
    'ETH/USDT': {
        'state_file':      'eth_state.json',
        'log_prefix':      'eth',
        'min_sl_dist_pct': 0.0050,  # EXP016A: SL≥0.50% (viable over 180d)
        'longs_only':      False,
        'label':           'ETH/USDT (EXP016A, SL≥0.50%, longs+shorts)',
    },
}

CANDLE_LIMIT_1H  = 260
CANDLE_LIMIT_15M = 150
RISK_PCT         = 0.01
MIN_RISK_PRICE   = 1.0
SCAN_INTERVAL    = 30    # seconds between full scans

# Task004 TIME-B: only enter trades in 07:00–21:00 UTC (skip Asian session)
TIME_B_START_UTC = 7
TIME_B_END_UTC   = 21

# Task002 DYN-B: scale position size inversely with ATR ratio (1h)
DYN_SCALE_MIN = 0.6
DYN_SCALE_MAX = 1.2

# Task007 ETH-SHORT-C: ETH shorts require volume >= 1.0× mean(50 bars) on 15m
ETH_SHORT_VOL_MIN_RATIO = 1.0


# ── Per-asset scan ────────────────────────────────────────────────────────────

def scan_asset(
    exchange,
    asset: str,
    cfg: dict,
    engine,
    logger,
    last_candle_ts: dict,
) -> None:
    min_sl_dist_pct = cfg['min_sl_dist_pct']
    longs_only      = cfg['longs_only']

    df_1h_raw  = fetch_ohlcv(exchange, asset, '1h',  CANDLE_LIMIT_1H)
    df_15m_raw = fetch_ohlcv(exchange, asset, '15m', CANDLE_LIMIT_15M)

    if df_1h_raw.empty or df_15m_raw.empty:
        logger.info(f"[{asset}] Data fetch failed — skipping.")
        return

    df_1h_raw  = df_1h_raw.iloc[:-1]
    df_15m_raw = df_15m_raw.iloc[:-1]

    if len(df_1h_raw) < 60 or len(df_15m_raw) < 10:
        logger.info(f"[{asset}] Insufficient closed candles — skipping.")
        return

    df_1h_raw  = df_1h_raw.reset_index().rename(columns={'timestamp': 'open_time'})
    df_15m_raw = df_15m_raw.reset_index().rename(columns={'timestamp': 'open_time'})

    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)

    if df.empty:
        logger.info(f"[{asset}] Alignment produced empty frame — skipping.")
        return

    row         = df.iloc[-1]
    candle_time = str(row['open_time'])

    # ── Check exit for any open position first ────────────────────────────────
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
            notify_trade_close(
                asset, trade['direction'], trade['entry'], trade['exit'],
                trade['reason'], trade['pnl'], engine.equity,
            )
        else:
            engine.log_status(logger, asset, row['close'], row['high'], row['low'])

        last_candle_ts[asset] = candle_time
        return

    # ── Dedup ─────────────────────────────────────────────────────────────────
    if last_candle_ts.get(asset) == candle_time:
        return

    last_candle_ts[asset] = candle_time

    # ── Entry filters ─────────────────────────────────────────────────────────
    trend = get_trend(row)
    if trend is None:
        return

    # BTC: longs only (EXP009)
    if longs_only and trend != 'up':
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

    # EXP019 — SLOPE_CAP: skip when EMA50 is in parabolic momentum (>0.20%/5bars)
    slope_pct = row.get('ema50_slope_pct')
    if slope_pct is not None and not pd.isna(slope_pct) and abs(slope_pct) > 0.20:
        logger.info(
            f"[{asset}] SKIP slope_cap ema50_slope={slope_pct:.3f}% > 0.20%"
        )
        return

    # Task004 TIME-B: skip Asian session (00:00–07:00 UTC) and late US (21:00–24:00 UTC)
    candle_ts = pd.Timestamp(row['open_time'])
    hour_utc  = candle_ts.hour if candle_ts.tzinfo is None else candle_ts.tz_convert('UTC').hour
    if not (TIME_B_START_UTC <= hour_utc < TIME_B_END_UTC):
        logger.info(f"[{asset}] SKIP time_b hour={hour_utc:02d}UTC outside 07–21")
        return

    # ── Size and open paper position ──────────────────────────────────────────
    entry     = row['close']
    direction = 'long' if trend == 'up' else 'short'

    # Task007 ETH-SHORT-C: require volume >= 1.0× mean(50 bars) for ETH shorts
    if asset == 'ETH/USDT' and direction == 'short':
        vol       = row.get('volume')
        vol_m50   = row.get('vol_mean50')
        if vol is not None and vol_m50 is not None and not pd.isna(vol_m50) and vol_m50 > 0:
            vol_ratio = vol / vol_m50
            if vol_ratio < ETH_SHORT_VOL_MIN_RATIO:
                logger.info(
                    f"[{asset}] SKIP eth_short_vol vol_ratio={vol_ratio:.2f} < {ETH_SHORT_VOL_MIN_RATIO}"
                )
                return

    sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
    if sl is None:
        return

    risk_price = abs(entry - sl)
    if risk_price < MIN_RISK_PRICE:
        return

    if risk_price / entry < min_sl_dist_pct:
        logger.info(
            f"[{asset}] SKIP sl_dist={risk_price/entry*100:.3f}% "
            f"< {min_sl_dist_pct*100:.2f}% (SL filter)"
        )
        return

    # Task002 DYN-B: scale risk inversely with ATR ratio (quieter market → larger size)
    atr_ratio = row.get('atr_ratio')
    if atr_ratio is not None and not pd.isna(atr_ratio) and atr_ratio > 0:
        raw_scale = 1.0 / atr_ratio
        dyn_scale = max(DYN_SCALE_MIN, min(DYN_SCALE_MAX, raw_scale))
    else:
        dyn_scale = 1.0
    risk_usd = engine.equity * RISK_PCT * dyn_scale
    qty      = risk_usd / risk_price

    opened = engine.open_position(
        asset=asset,
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        qty=qty,
        ts=candle_time,
        risk_usd=risk_usd,
        logger=logger,
    )
    if opened is not False:
        log_open(logger, asset, direction, candle_time, entry, sl, tp)
        notify_trade_open(asset, direction, entry, sl, tp, risk_usd, dyn_scale)
    logger.info(
        f"[{asset}] dyn_scale={dyn_scale:.2f}  risk_usd={risk_usd:.2f}  hour={hour_utc:02d}UTC"
    )


# ── Scan loop ─────────────────────────────────────────────────────────────────

def run_scan(
    exchange,
    engines: dict,
    loggers: dict,
    last_candle_ts: dict,
    live: bool = False,
) -> None:
    """
    Scan all assets. engines and loggers are dicts keyed by asset symbol.
    """
    ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    label_suffix = 'LIVE TRADING SUMMARY' if live else 'PAPER TRADING SUMMARY'
    for asset, cfg in ASSETS_CONFIG.items():
        engine = engines[asset]
        logger = loggers[asset]
        logger.info(f"\n[SCAN] {ts}")
        try:
            scan_asset(exchange, asset, cfg, engine, logger, last_candle_ts)
        except Exception as e:
            logger.info(f"[{asset}] ERROR: {e}")
        engine.print_summary(logger, label=f"{asset} {label_suffix}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='InvestmentBot Paper Trading Monitor')
    parser.add_argument(
        '--loop',
        action='store_true',
        help=f'Run continuously, scanning every {SCAN_INTERVAL}s',
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Use LiveEngine (real Binance Futures orders) instead of PaperEngine',
    )
    parser.add_argument(
        '--testnet',
        action='store_true',
        help='Use Binance Futures testnet (only effective with --live)',
    )
    args = parser.parse_args()

    log_date   = datetime.now(timezone.utc).strftime('%Y%m%d')
    log_prefix = 'live_monitor' if args.live else 'paper_monitor'

    loggers = {
        asset: setup_logger(
            f'{log_prefix}_{cfg["log_prefix"]}',
            log_file=f'logs/{cfg["log_prefix"]}_{log_date}.log',
            mode='a',
        )
        for asset, cfg in ASSETS_CONFIG.items()
    }

    if args.live:
        exchange = create_futures_exchange(testnet=args.testnet)
        suffix   = '_live_testnet' if args.testnet else '_live'
        engines  = {
            asset: LiveEngine(
                exchange=exchange,
                symbol=asset + ':USDT',  # 'BTC/USDT' → 'BTC/USDT:USDT'
                state_file=cfg['state_file'].replace('.json', f'{suffix}.json'),
                testnet=args.testnet,
            )
            for asset, cfg in ASSETS_CONFIG.items()
        }
    else:
        exchange = create_public_exchange()
        engines  = {
            asset: PaperEngine(state_file=cfg['state_file'])
            for asset, cfg in ASSETS_CONFIG.items()
        }
    last_candle_ts: dict = {}

    if not args.loop:
        run_scan(exchange, engines, loggers, last_candle_ts, live=args.live)
        return

    mode_label = 'LIVE' + (' (TESTNET)' if args.testnet else '') if args.live else 'PAPER'
    for asset, cfg in ASSETS_CONFIG.items():
        loggers[asset].info(f"[MONITOR] Started [{mode_label}] — {cfg['label']}")
        loggers[asset].info(
            f"[MONITOR] Risk: {RISK_PCT*100:.0f}%  |  SL_min: {cfg['min_sl_dist_pct']*100:.2f}%  |  Interval: {SCAN_INTERVAL}s"
        )

    while True:
        current_date = datetime.now(timezone.utc).strftime('%Y%m%d')
        if current_date != log_date:
            log_date = current_date
            for asset, cfg in ASSETS_CONFIG.items():
                loggers[asset] = setup_logger(
                    f'{log_prefix}_{cfg["log_prefix"]}',
                    log_file=f'logs/{cfg["log_prefix"]}_{log_date}.log',
                    mode='a',
                )
                loggers[asset].info(f"[MONITOR] Log rotated — new day: {log_date}")

        run_scan(exchange, engines, loggers, last_candle_ts, live=args.live)
        time.sleep(SCAN_INTERVAL)


if __name__ == '__main__':
    main()
