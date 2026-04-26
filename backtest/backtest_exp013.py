"""
EXP013  —  EMA spread filter applied only to SHORT signals

Hypothesis:
    EXP012 confirmed that the EMA20/EMA50 spread filter (>= 0.5%) would have
    blocked all 7 avoidable losing trades in live paper trading (Apr 19-24 2026),
    but at the cost of also damaging ETH longs and BTC longs in backtesting.

    The root asymmetry: a small EMA20/EMA50 spread can mean two things:
      (a) Sideways range — bad for both directions, but ESPECIALLY for shorts,
          because genuine downtrends require sustained bearish structure.
      (b) Early uptrend after consolidation — good for longs (BTC pullback
          entries happen precisely here), irrelevant for shorts.

    Fix: apply the spread filter ONLY to short signals.
      if direction == 'short' and |EMA20-EMA50|/EMA50 < 0.5%: skip

    This preserves all long entries (BTC and ETH) while filtering out ETH
    shorts in ranging/consolidating markets — exactly the failure pattern
    observed in live trading.

Baseline    : EXP009 (current production stack)
  BTC longs : 99 trades | WR=39.4% | PF=1.297 | Return=+18.45% | MaxDD=7.78%
  ETH both  : 207 trades | WR=41.1% | PF=1.375 | Return=+57.95% | MaxDD=10.76%

Parameter:
  MIN_EMA_SPREAD_PCT = 0.5  (only enforced for short entries)

Change scope: one new conditional entry filter. SL/TP unchanged.

Decision criteria:
  KEEP if:
    - ETH PF improves
    - BTC PF maintained (filter doesn't touch longs)
    - MaxDD does not worsen on either asset
    - Trade count >= 70% of baseline on ETH
  REVERT if PF drops or MaxDD worsens
"""

import json
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend, is_trend_strong, is_pullback_quality,
    is_entry_trigger, is_candle_quality,
    is_range_sufficient, is_market_efficient,
)
from core.trade_logic import calculate_sl_tp, check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
MIN_RISK_PRICE   = 1.0
MIN_SL_DIST_PCT  = 0.0015

MIN_EMA_SPREAD_PCT = 0.5   # enforced on shorts only


def is_short_spread_sufficient(row) -> bool:
    ema20 = row.get('ema20')
    ema50 = row.get('ema50')
    if pd.isna(ema20) or pd.isna(ema50) or ema50 == 0:
        return False
    return abs(ema20 - ema50) / ema50 * 100 >= MIN_EMA_SPREAD_PCT


def run(path_1h: str, path_15m: str, asset: str, longs_only: bool) -> dict:
    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)

    equity     = INITIAL_CAPITAL
    position   = None
    trades     = []
    peak       = equity
    rej_spread = 0

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                pnl = 2.0 * position['risk_used'] if reason == 'TP' else -position['risk_used']
                equity += pnl
                peak = max(peak, equity)
                trades.append({
                    'open_time':  position['open_time'],
                    'close_time': row['open_time'],
                    'direction':  position['direction'],
                    'entry':      position['entry'],
                    'exit':       exit_price,
                    'sl':         position['sl'],
                    'tp':         position['tp'],
                    'reason':     reason,
                    'pnl':        round(pnl, 4),
                    'equity':     round(equity, 4),
                })
                position = None
            continue

        trend = get_trend(row)
        if trend is None:
            continue
        if longs_only and trend != 'up':
            continue
        if not is_trend_strong(row):
            continue
        if not is_pullback_quality(row, trend):
            continue
        if not is_entry_trigger(row, trend):
            continue
        if not is_candle_quality(row, trend):
            continue
        if not is_range_sufficient(row):
            continue
        if not is_market_efficient(row):
            continue

        direction = 'long' if trend == 'up' else 'short'

        # EXP013: spread filter on shorts only
        if direction == 'short' and not is_short_spread_sufficient(row):
            rej_spread += 1
            continue

        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None:
            continue
        if abs(entry - sl) / entry < MIN_SL_DIST_PCT:
            continue

        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'risk_used': equity * RISK_PCT,
        }

    return {'trades': trades, 'final_equity': equity, 'rej_spread': rej_spread}


def metrics(trades: list) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    wins         = df[df['pnl'] > 0]
    loss         = df[df['pnl'] <= 0]
    gross_profit = wins['pnl'].sum()
    gross_loss   = abs(loss['pnl'].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    eq = INITIAL_CAPITAL
    for pnl in df['pnl']:
        eq += pnl
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        max_dd = max(max_dd, dd)
    total_ret = (df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    longs  = df[df['direction'] == 'long']
    shorts = df[df['direction'] == 'short']

    def pf_side(g):
        w = g[g['pnl'] > 0]; l = abs(g[g['pnl'] <= 0]['pnl'].sum())
        return round(w['pnl'].sum() / l, 3) if l > 0 else float('inf')

    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(total_ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'long_trades':    len(longs),
        'short_trades':   len(shorts),
        'long_pf':        pf_side(longs) if len(longs) else 0,
        'short_pf':       pf_side(shorts) if len(shorts) else 0,
    }


def monthly(trades: list) -> list:
    if not trades:
        return []
    df = pd.DataFrame(trades)
    df['month'] = pd.to_datetime(df['open_time']).dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        wins = g[g['pnl'] > 0]
        gl   = abs(g[g['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        pf   = gp / gl if gl > 0 else float('inf')
        rows.append({
            'month': str(month), 'trades': len(g),
            'win_rate_pct': round(len(wins) / len(g) * 100, 1),
            'net_pnl': round(g['pnl'].sum(), 2),
            'profit_factor': round(pf, 3),
        })
    return rows


BASELINE = {
    'BTC': {
        'total_trades': 99, 'win_rate_pct': 39.4, 'return_pct': 18.45,
        'max_dd_pct': 7.78, 'profit_factor': 1.297, 'expectancy_usd': 18.63,
        'monthly': {
            '2025-09': -100.00, '2025-10': 278.74, '2025-11': -697.14,
            '2025-12': 272.77,  '2026-01': 999.21, '2026-02': 92.45, '2026-03': 998.52,
        },
    },
    'ETH': {
        'total_trades': 207, 'win_rate_pct': 41.1, 'return_pct': 57.95,
        'max_dd_pct': 10.76, 'profit_factor': 1.375, 'expectancy_usd': 27.99,
        'monthly': {
            '2025-09': -299.90, '2025-10': 1971.19, '2025-11': 561.32,
            '2025-12': -279.11, '2026-01': 814.04,  '2026-02': 2459.05, '2026-03': 568.01,
        },
    },
}


def print_report(asset: str, result: dict, m: dict, mo: list) -> None:
    b = BASELINE[asset]
    print(f"\n{'='*70}")
    print(f"EXP013  |  {asset}  |  EMA spread filter on SHORTS only (min {MIN_EMA_SPREAD_PCT}%)")
    print(f"{'='*70}")

    print(f"\n{'Metric':<25} {'EXP009 base':>13} {'EXP013':>13} {'Delta':>10}")
    print(f"{'-'*63}")
    fields = [
        ('Trades',        'total_trades',   '{:d}'),
        ('Win rate %',    'win_rate_pct',    '{:.1f}'),
        ('Return %',      'return_pct',      '{:+.2f}'),
        ('Max DD %',      'max_dd_pct',      '{:.2f}'),
        ('Profit factor', 'profit_factor',   '{:.3f}'),
        ('Expectancy $',  'expectancy_usd',  '{:+.2f}'),
    ]
    for label, key, fmt in fields:
        bv    = b[key]
        new   = m.get(key, 0)
        delta = new - bv
        sign  = '+' if delta >= 0 else ''
        print(f"  {label:<23} {fmt.format(bv):>13} {fmt.format(new):>13}  {sign}{fmt.format(delta):>8}")

    print(f"\n  Long  trades : {m.get('long_trades',0)}  |  PF = {m.get('long_pf',0):.3f}")
    print(f"  Short trades : {m.get('short_trades',0)}  |  PF = {m.get('short_pf',0):.3f}")
    n_new = m.get('total_trades', 0)
    print(f"  Shorts blocked by spread : {result['rej_spread']}")
    print(f"  Trade count vs baseline  : {n_new/b['total_trades']*100:.0f}% ({n_new}/{b['total_trades']})")

    print(f"\n── Monthly breakdown ────────────────────────────────────────────────")
    print(f"  {'Month':<10} {'Trades':>6} {'WR':>6} {'PnL':>10} {'PF':>7}  {'vs EXP009':>10}")
    print(f"  {'-'*60}")
    for row in mo:
        pf_str = f"{row['profit_factor']:.3f}" if row['profit_factor'] != float('inf') else "  inf"
        flag   = '  *' if row['profit_factor'] < 1.0 else ''
        base_pnl = b['monthly'].get(row['month'], 0.0)
        delta_pnl = row['net_pnl'] - base_pnl
        print(f"  {row['month']:<10} {row['trades']:>6} {row['win_rate_pct']:>5.1f}% {row['net_pnl']:>+9.2f}  {pf_str}{flag}  {delta_pnl:>+9.2f}")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    configs = [
        {'name': 'BTC', 'path_1h': 'data/BTCUSDT_1h_last_200d.csv',
         'path_15m': 'data/BTCUSDT_15m_last_180d.csv', 'longs_only': True},
        {'name': 'ETH', 'path_1h': 'data/ETHUSDT_1h_last_200d.csv',
         'path_15m': 'data/ETHUSDT_15m_last_180d.csv', 'longs_only': False},
    ]

    all_results = {}
    for cfg in configs:
        print(f"\nRunning {cfg['name']}...")
        result = run(cfg['path_1h'], cfg['path_15m'], cfg['name'], cfg['longs_only'])
        m  = metrics(result['trades'])
        mo = monthly(result['trades'])
        print_report(cfg['name'], result, m, mo)
        all_results[cfg['name']] = {
            'metrics': m, 'monthly': mo,
            'final_equity': result['final_equity'],
            'rej_spread':   result['rej_spread'],
        }

    out_path = 'data/backtest_exp013.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to {out_path}")
