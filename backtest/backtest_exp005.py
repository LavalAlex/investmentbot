"""
EXP005-v2 — Cross-Asset Generalization Test

Strategy : EXP002-v2 pullback continuation (unchanged)
Purpose  : Validate whether the system edge generalizes beyond BTC/USDT.

Rules:
  - Zero parameter changes. Strategy, filters, sizing identical to EXP002.
  - Same timeframes (1h context + 15m entry).
  - Same IS window: Sep 2025 – Mar 2026 (data availability constraint for all assets).
  - No OOS data available for alt-coins; OOS generalization not testable here.

Assets tested:
  BTC/USDT (reference — EXP002 result reproduced for direct comparison)
  ETH/USDT
  SOL/USDT
  BNB/USDT
  XRP/USDT
  DOGE/USDT

Decision criteria:
  "Robust system"    → majority of assets PF > 1, consistent metrics
  "BTC-specific edge" → only BTC profitable, alt-coins systematically fail
"""

import json
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
from core.trade_logic import calculate_sl_tp, check_exit
from core.logger_v2 import setup_logger, log_open, log_close
from backtest.backtest_v2 import load_data, compute_metrics, print_summary, save_results

# ── Config (identical to EXP002) ─────────────────────────────────────────────
INITIAL_CAPITAL = 10_000.0
RISK_PCT        = 0.01
MIN_RISK_PRICE  = 1.0


# ── Per-asset backtest (identical logic to EXP002) ───────────────────────────

def run_backtest(path_1h: str, path_15m: str, asset: str) -> dict:
    label    = f'{asset}_in_sample'
    log_file = f'logs/exp005_{asset}.log'
    logger   = setup_logger(f'exp005_{asset}', log_file=log_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"EXP005-v2  |  {asset}  |  IN-SAMPLE")
    logger.info(f"Strategy   : EXP002-v2 (unchanged)")
    logger.info(f"1h data    : {path_1h}")
    logger.info(f"15m data   : {path_15m}")
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

        # Entry checks — EXP002 filters
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
        'asset':        asset,
        'label':        label,
        'metrics':      metrics,
        'trades':       trades,
        'equity_curve': equity_curve,
        'rejected':     rejected,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

ASSETS = [
    ('BTC',  'data/BTCUSDT_1h_last_200d.csv',  'data/BTCUSDT_15m_last_180d.csv'),
    ('ETH',  'data/ETHUSDT_1h_last_200d.csv',  'data/ETHUSDT_15m_last_180d.csv'),
    ('SOL',  'data/SOLUSDT_1h_last_200d.csv',  'data/SOLUSDT_15m_last_180d.csv'),
    ('BNB',  'data/BNBUSDT_1h_last_200d.csv',  'data/BNBUSDT_15m_last_180d.csv'),
    ('XRP',  'data/XRPUSDT_1h_last_200d.csv',  'data/XRPUSDT_15m_last_180d.csv'),
    ('DOGE', 'data/DOGEUSDT_1h_last_200d.csv', 'data/DOGEUSDT_15m_last_180d.csv'),
]

if __name__ == '__main__':
    summary = []

    for asset, path_1h, path_15m in ASSETS:
        result  = run_backtest(path_1h, path_15m, asset)
        save_results(result, f'exp005v2_{asset}')
        m = result['metrics']
        summary.append({
            'asset':       asset,
            'trades':      m['total_trades'],
            'win_rate':    m.get('win_rate_pct', 0.0),
            'return_pct':  m.get('total_return_pct', 0.0),
            'max_dd_pct':  m.get('max_drawdown_pct', 0.0),
            'pf':          m.get('profit_factor', 0.0),
            'expectancy':  m.get('expectancy_usd', 0.0),
            'long_pnl':    m.get('long_pnl', 0.0),
            'short_pnl':   m.get('short_pnl', 0.0),
        })

    # ── Cross-asset summary table ─────────────────────────────────────────
    df_summary = pd.DataFrame(summary)

    print(f"\n{'='*75}")
    print(f"EXP005-v2  |  CROSS-ASSET SUMMARY  |  IS: Sep 2025 – Mar 2026")
    print(f"Strategy   : EXP002-v2 unchanged (no parameter tuning)")
    print(f"{'='*75}")
    print(df_summary.to_string(index=False))
    print(f"{'='*75}")

    profitable = df_summary[df_summary['pf'] > 1.0]
    losing     = df_summary[df_summary['pf'] <= 1.0]

    print(f"\nPF > 1.0 : {len(profitable)}/{len(df_summary)} assets  [{', '.join(profitable['asset'].tolist())}]")
    print(f"PF <= 1.0: {len(losing)}/{len(df_summary)} assets  [{', '.join(losing['asset'].tolist())}]")

    pf_vals = df_summary['pf'].tolist()
    print(f"\nPF range : {min(pf_vals):.3f} – {max(pf_vals):.3f}  |  median: {sorted(pf_vals)[len(pf_vals)//2]:.3f}")

    if len(profitable) >= 4:
        verdict = "ROBUST SYSTEM — edge generalizes across assets"
    elif len(profitable) >= 2:
        verdict = "PARTIAL GENERALIZATION — edge works on some but not all assets"
    else:
        verdict = "BTC-SPECIFIC EDGE — system does not generalize"
    print(f"\nVerdict: {verdict}")
    print(f"{'='*75}\n")

    # Save summary
    df_summary.to_csv('data/exp005v2_cross_asset_summary.csv', index=False)
    with open('data/exp005v2_cross_asset_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    print("Saved: data/exp005v2_cross_asset_summary.csv")
    print("Saved: data/exp005v2_cross_asset_summary.json")
