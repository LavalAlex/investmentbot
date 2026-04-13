"""
EXP002-v2 — Pullback Continuation + Quality Filters

Strategy family : pullback continuation (same as EXP001)
Entry logic     : 1h trend via EMA20 slope → structured pullback to EMA20 → 15m trigger candle
Exit logic      : SL at trigger candle extreme, TP at 2× risk (R:R = 2:1)
Filters added   :
  1. Trend strength  — EMA50 normalized slope + price distance from EMA50
  2. Pullback quality — 1h bar's intrabar extreme must have reached EMA20
  3. Candle quality   — 15m trigger candle body ≥ 60% of range
  4. Range floor      — 5-bar avg 15m range ≥ 0.1% of price
Position sizing : 1% equity risk per trade (unchanged)
"""

import json
import pandas as pd

from strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend,
    is_trend_strong,
    is_pullback_quality,
    is_entry_trigger,
    is_candle_quality,
    is_range_sufficient,
)
from trade_logic import calculate_sl_tp, check_exit
from logger_v2 import setup_logger, log_open, log_close
from backtest_v2 import load_data, compute_metrics, print_summary, save_results

# ── Config ───────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 10_000.0
RISK_PCT        = 0.01
MIN_RISK_PRICE  = 1.0


# ── Execution loop ────────────────────────────────────────────────────────────

def run_backtest(path_1h: str, path_15m: str, label: str = 'in_sample') -> dict:
    log_file = f'logs/exp002_{label}.log'
    logger = setup_logger(f'exp002_{label}', log_file=log_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"EXP002-v2  |  {label.upper()}")
    logger.info(f"1h data  : {path_1h}")
    logger.info(f"15m data : {path_15m}")
    logger.info(f"{'='*60}\n")

    df_1h, df_15m = load_data(path_1h, path_15m)
    df_1h_prep    = prepare_1h(df_1h)
    df_15m_prep   = prepare_15m(df_15m)
    df            = align_1h_to_15m(df_15m_prep, df_1h_prep)

    equity       = INITIAL_CAPITAL
    position     = None
    trades       = []
    equity_curve = []

    # Counters for filter diagnostics
    rejected = {'trend': 0, 'pullback': 0, 'candle': 0, 'range': 0, 'no_signal': 0}

    for _, row in df.iterrows():
        ts = row['open_time']

        # ── Check exit if in a position ───────────────────────────────────
        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result

                if position['direction'] == 'long':
                    pnl = (exit_price - position['entry']) * position['qty']
                else:
                    pnl = (position['entry'] - exit_price) * position['qty']

                equity += pnl
                log_close(logger, position['direction'], position['entry'], exit_price, reason, pnl, equity)

                trades.append({
                    'open_ts':   position['open_ts'],
                    'close_ts':  str(ts),
                    'direction': position['direction'],
                    'entry':     position['entry'],
                    'exit':      exit_price,
                    'sl':        position['sl'],
                    'tp':        position['tp'],
                    'reason':    reason,
                    'pnl':       round(pnl, 4),
                    'equity':    round(equity, 4),
                })
                position = None

            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # ── Check entry — all filters must pass ──────────────────────────
        trend = get_trend(row)
        if trend is None:
            rejected['no_signal'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_trend_strong(row):
            rejected['trend'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_pullback_quality(row, trend):
            rejected['pullback'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_entry_trigger(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_candle_quality(row, trend):
            rejected['candle'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_range_sufficient(row):
            rejected['range'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # Signal confirmed — size and open trade
        entry     = row['close']
        direction = 'long' if trend == 'up' else 'short'

        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_price = abs(entry - sl)
        if risk_price < MIN_RISK_PRICE:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_usd = equity * RISK_PCT
        qty      = risk_usd / risk_price

        position = {
            'direction': direction,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       qty,
            'open_ts':   str(ts),
        }

        log_open(logger, direction, ts, entry, sl, tp)
        equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})

    # Force-close any open position at last bar price
    if position is not None:
        last_row   = df.iloc[-1]
        exit_price = last_row['close']
        if position['direction'] == 'long':
            pnl = (exit_price - position['entry']) * position['qty']
        else:
            pnl = (position['entry'] - exit_price) * position['qty']
        equity += pnl
        log_close(logger, position['direction'], position['entry'], exit_price, 'END', pnl, equity)
        trades.append({
            'open_ts':   position['open_ts'],
            'close_ts':  str(last_row['open_time']),
            'direction': position['direction'],
            'entry':     position['entry'],
            'exit':      exit_price,
            'sl':        position['sl'],
            'tp':        position['tp'],
            'reason':    'END',
            'pnl':       round(pnl, 4),
            'equity':    round(equity, 4),
        })

    metrics = compute_metrics(trades, INITIAL_CAPITAL, equity)
    print_summary(logger, metrics, label)

    # Log filter rejection breakdown
    logger.info(f"Filter rejections:")
    logger.info(f"  No trend signal  : {rejected['no_signal']}")
    logger.info(f"  Trend strength   : {rejected['trend']}")
    logger.info(f"  Pullback quality : {rejected['pullback']}")
    logger.info(f"  Candle quality   : {rejected['candle']}")
    logger.info(f"  Range floor      : {rejected['range']}")

    return {
        'label':        label,
        'metrics':      metrics,
        'trades':       trades,
        'equity_curve': equity_curve,
        'rejected':     rejected,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    is_result = run_backtest(
        path_1h='data/BTCUSDT_1h_last_200d.csv',
        path_15m='data/BTCUSDT_15m_last_180d.csv',
        label='in_sample',
    )
    save_results(is_result, 'exp002v2_in_sample')

    oos_result = run_backtest(
        path_1h='data/BTCUSDT_1h_oos_200d.csv',
        path_15m='data/BTCUSDT_15m_oos_180d.csv',
        label='out_of_sample',
    )
    save_results(oos_result, 'exp002v2_out_of_sample')
