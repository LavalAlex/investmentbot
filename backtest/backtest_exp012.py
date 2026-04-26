"""
EXP012  —  EMA20/EMA50 spread filter (range detector)

Hypothesis:
    EXP011 proved that widening the SL does not solve the problem: the
    strategy fires entries in ranging/consolidating markets and pays the
    R:R price (2× TP far away, SL close) regardless of SL width.

    The real failure mode observed in live paper trading (Apr 23–24 2026,
    ETH/USDT): 6 consecutive SL hits while ETH traded in a ~45 USD range
    (~2%). The 1h EMA20 slope was negative (signaling "down"), but EMA20
    and EMA50 were tightly compressed — both EMAs nearly overlapping.

    When EMA20 ≈ EMA50, the market has no structural directional separation:
    the short-term momentum is aligned with the long-term trend only because
    both are flat, not because a genuine trend is in force.

    Filter: require abs(EMA20 - EMA50) / EMA50 >= MIN_EMA_SPREAD_PCT.
    If the gap is smaller, price is in consolidation and the pullback
    strategy has no structural edge.

    Threshold selection:
      - ETH spread distribution: median 0.80%, 25th pct = 0.34%
      - BTC spread distribution: median 0.52%, 25th pct = 0.25%
      - 0.5% chosen: filters the bottom ~22-34% of bars (tight ranges)
        while preserving the 66-78% with genuine trend separation.

Baseline    : EXP009 (current production stack, pre-EXP010/011)
  BTC longs : 99 trades | WR=39.4% | PF=1.297 | Return=+18.45% | MaxDD=7.78%
  ETH both  : 207 trades | WR=41.1% | PF=1.375 | Return=+57.95% | MaxDD=10.76%

Parameter:
  MIN_EMA_SPREAD_PCT = 0.5   (require |EMA20-EMA50|/EMA50 >= 0.5%)

Change scope: one new entry filter.  SL/TP and all other filters unchanged.

Decision criteria:
  KEEP if:
    - PF improves on both assets
    - MaxDD does not worsen
    - Trade count >= 70% of baseline (not over-filtering)
    - Win rate improves
  REVERT if PF drops or MaxDD worsens
  CONDITIONAL if improvement is asset-specific
"""

import json
import pandas as pd
import numpy as np

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

# ── Config ────────────────────────────────────────────────────────────────────
INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
MIN_RISK_PRICE   = 1.0
MIN_SL_DIST_PCT  = 0.0015       # EXP007 floor

# ── EXP012 parameter ──────────────────────────────────────────────────────────
MIN_EMA_SPREAD_PCT = 0.5        # |EMA20 - EMA50| / EMA50 must be >= 0.5%


def is_ema_spread_sufficient(row) -> bool:
    """
    Returns True when EMA20 and EMA50 are sufficiently separated,
    indicating a structured trend rather than flat consolidation.
    """
    ema20 = row.get('ema20')
    ema50 = row.get('ema50')
    if pd.isna(ema20) or pd.isna(ema50) or ema50 == 0:
        return False
    spread_pct = abs(ema20 - ema50) / ema50 * 100
    return spread_pct >= MIN_EMA_SPREAD_PCT


def run(path_1h: str, path_15m: str, asset: str, longs_only: bool) -> dict:
    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)

    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)

    equity   = INITIAL_CAPITAL
    position = None
    trades   = []
    peak     = equity
    rej_spread = 0

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        # ── Manage open position ──────────────────────────────────────────────
        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                risk_used = position['risk_used']
                pnl = 2.0 * risk_used if reason == 'TP' else -risk_used
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

        if position is not None:
            continue

        # ── Entry logic ───────────────────────────────────────────────────────
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

        # ── EXP012: EMA spread filter ─────────────────────────────────────────
        if not is_ema_spread_sufficient(row):
            rej_spread += 1
            continue

        # ── SL/TP (unchanged from EXP009) ─────────────────────────────────────
        entry = row['close']
        sl, tp = calculate_sl_tp(entry, trend, row['low'], row['high'])
        if sl is None:
            continue
        if abs(entry - sl) / entry < MIN_SL_DIST_PCT:
            continue

        risk_used = equity * RISK_PCT

        position = {
            'open_time': row['open_time'],
            'direction': trend,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'risk_used': risk_used,
        }

    return {'trades': trades, 'final_equity': equity, 'rej_spread': rej_spread}


def metrics(trades: list) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
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
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(total_ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
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
    print(f"EXP012  |  {asset}  |  EMA spread filter (min {MIN_EMA_SPREAD_PCT}%)")
    print(f"{'='*70}")

    print(f"\n{'Metric':<25} {'EXP009 base':>13} {'EXP012':>13} {'Delta':>10}")
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

    n_baseline = b['total_trades']
    n_new      = m.get('total_trades', 0)
    pct_kept   = n_new / n_baseline * 100 if n_baseline else 0
    print(f"\n  Blocked by spread filter : {result['rej_spread']} candles")
    print(f"  Trade count vs baseline  : {pct_kept:.0f}% ({n_new}/{n_baseline})")

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

    out_path = 'data/backtest_exp012.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to {out_path}")
