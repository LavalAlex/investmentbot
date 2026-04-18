"""
EXP004-v2 — Pullback Continuation + Quality Filters + Tighter TP (1.5R)

Strategy family : pullback continuation (unchanged from EXP002)
Entry logic     : identical to EXP002
Exit logic      : SL at trigger candle extreme, TP at 1.5× risk (R:R = 1.5:1)
                  Hypothesis: tighter TP converts some SL trades to TP exits,
                  increasing win rate enough to offset the lower reward.
Filters         : identical to EXP002 (all 4 quality filters retained)
Position sizing : 1% equity risk per trade (unchanged)

EXP004 change (one modification):
  TP_MULT = 1.5  (was 2.0 in EXP001/002/003)

Simulation results before implementation (EXP002 trades):
  IS:  41 SL→TP conversions (+82R), 160 TP trades earn 1.5R not 2R (−80R), net +22.5R
  OOS: 24 SL→TP conversions (+48R), 153 TP trades earn 1.5R not 2R (−76.5R), net −14R
  IS/OOS asymmetry signals possible overfitting of exit parameter to IS period.
"""

import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend,
    is_trend_strong,
    is_pullback_quality,
    is_entry_trigger,
    is_candle_quality,
    is_range_sufficient,
)
from core.trade_logic import check_exit
from core.logger_v2 import setup_logger, log_open, log_close
from backtest.backtest_v2 import load_data, compute_metrics, print_summary, save_results

# ── Config ───────────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 10_000.0
RISK_PCT        = 0.01
MIN_RISK_PRICE  = 1.0
TP_MULT         = 1.5   # EXP004 change: was 2.0


def calculate_sl_tp_exp004(
    entry: float,
    direction: str,
    candle_low: float,
    candle_high: float,
) -> tuple[float, float] | tuple[None, None]:
    """SL at trigger candle extreme. TP at TP_MULT × risk (1.5:1)."""
    if direction == 'long':
        sl = candle_low
        risk = entry - sl
        if risk <= 0:
            return None, None
        tp = entry + TP_MULT * risk
    else:
        sl = candle_high
        risk = sl - entry
        if risk <= 0:
            return None, None
        tp = entry - TP_MULT * risk
    return sl, tp


# ── Execution loop ────────────────────────────────────────────────────────────

def run_backtest(path_1h: str, path_15m: str, label: str = 'in_sample') -> dict:
    log_file = f'logs/exp004_{label}.log'
    logger = setup_logger(f'exp004_{label}', log_file=log_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"EXP004-v2  |  {label.upper()}")
    logger.info(f"TP multiplier : {TP_MULT}x  (EXP002 baseline was 2.0x)")
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

    rejected = {'no_signal': 0, 'trend': 0, 'pullback': 0, 'candle': 0, 'range': 0}

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

        # ── Check entry — EXP002 filters ─────────────────────────────────
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

        sl, tp = calculate_sl_tp_exp004(entry, direction, row['low'], row['high'])
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
    save_results(is_result, 'exp004v2_in_sample')

    oos_result = run_backtest(
        path_1h='data/BTCUSDT_1h_oos_200d.csv',
        path_15m='data/BTCUSDT_15m_oos_180d.csv',
        label='out_of_sample',
    )
    save_results(oos_result, 'exp004v2_out_of_sample')
