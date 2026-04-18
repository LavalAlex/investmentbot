"""
EXP008-v2  —  Macro Direction Filter for BTC Shorts

Hypothesis:
    BTC shorts fired when the macro trend is bullish generate most of the
    short-side losses. In Nov–Dec 2025 BTC was recovering/ranging upward
    while EXP002 was still issuing short signals on 1h EMA20 pullbacks —
    those are counter-trend fades against a higher-timeframe bull move.

    Restricting BTC shorts to macro-bearish conditions (close_1h < EMA200_1h)
    should improve short-side PF without harming the long side.

Intervention:
    Add a single gate before opening a short position:
      if direction == 'short' and close_1h > ema200_1h → reject.

    LONG trades are unchanged — no restriction applied.

Implementation:
    EMA200 is computed on the 1h series and merged into the aligned frame
    (same pattern as existing EMA50).
    The filter is applied inside the backtest loop, after EXP007 sl_dist check.

Baseline   : EXP007_180d (BTC, Sep 2025 – Mar 2026)
             193 trades | WR=36.3% | PF=1.132 | Return=+16.18% | MaxDD=18.53%
             LONG  99t PF=1.290 | SHORT 94t PF=0.982

Decision criteria:
    KEEP if:
      - BTC PF improves meaningfully (> 1.20)
      - Short PF >= 1.0 OR short trade count drops below 30% of baseline (acceptable if longs carry)
      - Total trade count not below 60% of baseline (still enough activity)
      - MaxDD improves or stays within 5pp of baseline
    REVERT if PF drops or long side is harmed
    CONDITIONAL if improvement is isolated to one market regime
"""

import json
import pandas as pd
import numpy as np

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
    is_market_efficient,
)
from core.trade_logic import calculate_sl_tp, check_exit
from core.logger_v2 import setup_logger, log_open, log_close
from backtest.backtest_v2 import load_data

# ── Config (identical to EXP007_180d) ────────────────────────────────────────
INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
MIN_RISK_PRICE   = 1.0
MIN_SL_DIST_PCT  = 0.0015   # EXP007

# ── EXP008 parameter ─────────────────────────────────────────────────────────
EMA200_PERIOD    = 200      # 1h EMA200 — macro trend reference


# ── Extend 1h prep with EMA200 ────────────────────────────────────────────────

def prepare_1h_exp008(df: pd.DataFrame) -> pd.DataFrame:
    """prepare_1h + EMA200 for macro direction filter."""
    from indicators_v2 import ema as calc_ema
    out = prepare_1h(df)
    out['ema200'] = calc_ema(out['close'], EMA200_PERIOD)
    return out


def align_1h_to_15m_exp008(df_15m: pd.DataFrame, df_1h_prep: pd.DataFrame) -> pd.DataFrame:
    """align_1h_to_15m + carry ema200 into the merged frame."""
    left = df_15m.sort_values('open_time').reset_index(drop=True)
    right = (
        df_1h_prep[[
            'available_at', 'ema20', 'ema20_slope',
            'ema50', 'ema50_slope_pct', 'er24',
            'close', 'low', 'high', 'ema200',
        ]]
        .rename(columns={'close': 'close_1h', 'low': 'low_1h', 'high': 'high_1h'})
        .dropna(subset=['ema20', 'ema20_slope'])
        .sort_values('available_at')
        .reset_index(drop=True)
    )
    merged = pd.merge_asof(
        left,
        right,
        left_on='open_time',
        right_on='available_at',
        direction='backward',
    )
    return merged


# ── Core backtest loop ────────────────────────────────────────────────────────

def run_flat(path_1h: str, path_15m: str, asset: str) -> dict:
    log_file = f'logs/exp008_{asset}.log'
    logger   = setup_logger(f'exp008_{asset}', log_file=log_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"EXP008-v2  |  {asset}")
    logger.info(f"Filters: EXP007_180d + macro direction (EMA200 on 1h for shorts)")
    logger.info(f"{'='*60}\n")

    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h_prep  = prepare_1h_exp008(df_1h_raw)
    df_15m_prep = prepare_15m(df_15m_raw)
    df          = align_1h_to_15m_exp008(df_15m_prep, df_1h_prep)

    equity       = INITIAL_CAPITAL
    position     = None
    trades       = []
    equity_curve = []
    rej_macro    = 0   # new filter counter

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
                    'open_ts':     position['open_ts'],
                    'close_ts':    str(ts),
                    'direction':   position['direction'],
                    'entry':       position['entry'],
                    'exit':        exit_price,
                    'sl':          position['sl'],
                    'tp':          position['tp'],
                    'sl_dist_pct': position['sl_dist_pct'],
                    'reason':      reason,
                    'pnl':         round(pnl, 4),
                    'equity':      round(equity, 4),
                })
                position = None

            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # ── EXP002 + EXP003 filters (unchanged) ──────────────────────────────
        trend = get_trend(row)
        if trend is None:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_trend_strong(row):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_pullback_quality(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_entry_trigger(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_candle_quality(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_range_sufficient(row):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_market_efficient(row):
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

        # ── EXP007: SL distance filter ────────────────────────────────────────
        sl_dist_pct = risk_price / entry
        if sl_dist_pct < MIN_SL_DIST_PCT:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # ── EXP008: macro direction filter (shorts only) ──────────────────────
        if direction == 'short':
            ema200 = row.get('ema200')
            if pd.isna(ema200) or row['close_1h'] > ema200:
                rej_macro += 1
                equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
                continue

        risk_usd = equity * RISK_PCT
        qty      = risk_usd / risk_price

        position = {
            'direction':   direction,
            'entry':       entry,
            'sl':          sl,
            'tp':          tp,
            'qty':         qty,
            'open_ts':     str(ts),
            'sl_dist_pct': round(sl_dist_pct * 100, 4),
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
            'open_ts':     position['open_ts'],
            'close_ts':    str(last_row['open_time']),
            'direction':   position['direction'],
            'entry':       position['entry'],
            'exit':        exit_price,
            'sl':          position['sl'],
            'tp':          position['tp'],
            'sl_dist_pct': position['sl_dist_pct'],
            'reason':      'END',
            'pnl':         round(pnl, 4),
            'equity':      round(equity, 4),
        })

    logger.info(f"\nRejected by macro direction filter (shorts above EMA200): {rej_macro}")

    return {
        'asset':        asset,
        'trades':       trades,
        'equity_curve': equity_curve,
        'final_equity': round(equity, 4),
        'rej_macro':    rej_macro,
    }


# ── Metrics helpers ───────────────────────────────────────────────────────────

def compute_flat_metrics(trades: list, initial_capital: float) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    gp = wins['pnl'].sum()        if len(wins)   else 0.0
    gl = abs(losses['pnl'].sum()) if len(losses) else 0.0
    pf = gp / gl if gl > 0 else float('inf')
    wr = len(wins) / len(df) * 100
    eq = df['equity'].values
    peak, max_dd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak * 100)
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(wr, 1),
        'net_pnl':        round(df['pnl'].sum(), 2),
        'return_pct':     round(df['pnl'].sum() / initial_capital * 100, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
    }


def compute_monthly_breakdown(trades: list) -> list:
    if not trades:
        return []
    df = pd.DataFrame(trades)
    df['close_ts'] = pd.to_datetime(df['close_ts'])
    df['month']    = df['close_ts'].dt.to_period('M')
    rows = []
    for month, group in df.groupby('month'):
        wins = group[group['pnl'] > 0]
        gl   = abs(group[group['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        pf   = gp / gl if gl > 0 else float('inf')
        rows.append({
            'month':         str(month),
            'trades':        len(group),
            'win_rate_pct':  round(len(wins) / len(group) * 100, 1),
            'net_pnl':       round(group['pnl'].sum(), 2),
            'profit_factor': round(pf, 3),
        })
    return rows


def compute_side_breakdown(trades: list) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    result = {}
    for direction in ['long', 'short']:
        sub = df[df['direction'] == direction]
        if len(sub) == 0:
            result[direction] = {'trades': 0}
            continue
        wins = sub[sub['pnl'] > 0]
        gl   = abs(sub[sub['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        pf   = gp / gl if gl > 0 else float('inf')
        result[direction] = {
            'trades':        len(sub),
            'win_rate_pct':  round(len(wins) / len(sub) * 100, 1),
            'net_pnl':       round(sub['pnl'].sum(), 2),
            'profit_factor': round(pf, 3),
        }
    return result


# ── Comparison printer ────────────────────────────────────────────────────────

BASELINE_BTC = {
    'total_trades': 193, 'win_rate_pct': 36.3, 'return_pct': 16.18,
    'max_dd_pct': 18.53, 'profit_factor': 1.132, 'expectancy_usd': 8.38,
    'long':  {'trades': 99,  'win_rate_pct': 39.4, 'profit_factor': 1.290, 'net_pnl': 1731.10},
    'short': {'trades': 94,  'win_rate_pct': 33.0, 'profit_factor': 0.982, 'net_pnl': -112.84},
    'monthly': {
        '2025-09': {'pf': 0.656, 'pnl': -102.95},
        '2025-10': {'pf': 1.186, 'pnl':  369.20},
        '2025-11': {'pf': 0.611, 'pnl':-1003.75},
        '2025-12': {'pf': 0.752, 'pnl': -474.93},
        '2026-01': {'pf': 1.713, 'pnl': 1181.84},
        '2026-02': {'pf': 1.344, 'pnl':  786.48},
        '2026-03': {'pf': 1.553, 'pnl':  862.37},
    },
}


def print_report(asset: str, result: dict, metrics: dict, monthly: list, sides: dict) -> None:
    print(f"\n{'='*70}")
    print(f"EXP008-v2  |  {asset}  |  Macro direction filter (EMA200 gate on shorts)")
    print(f"{'='*70}")

    if asset == 'BTC':
        b = BASELINE_BTC
        print(f"\n{'Metric':<22} {'EXP007 base':>14} {'EXP008':>14} {'Delta':>10}")
        print(f"{'-'*62}")
        rows = [
            ('Trades',       b['total_trades'],    metrics['total_trades'],   '{:+d}'),
            ('Win rate',     b['win_rate_pct'],     metrics['win_rate_pct'],   '{:+.1f}pp'),
            ('Return %',     b['return_pct'],       metrics['return_pct'],     '{:+.2f}pp'),
            ('Max DD %',     b['max_dd_pct'],       metrics['max_dd_pct'],     '{:+.2f}pp'),
            ('Profit factor',b['profit_factor'],    metrics['profit_factor'],  '{:+.3f}'),
            ('Expectancy $', b['expectancy_usd'],   metrics['expectancy_usd'], '{:+.2f}'),
        ]
        for label, base_val, new_val, fmt in rows:
            delta = new_val - base_val
            print(f"  {label:<20} {base_val:>14} {new_val:>14}  {fmt.format(delta):>9}")

        print(f"\n── Long / Short breakdown ───────────────────────────────────────")
        base_l, base_s = b['long'], b['short']
        new_l = sides.get('long',  {'trades': 0})
        new_s = sides.get('short', {'trades': 0})
        for side, bside, nside in [('LONG', base_l, new_l), ('SHORT', base_s, new_s)]:
            nt = nside.get('trades', 0)
            if nt == 0:
                print(f"  {side}: 0 trades (all blocked by macro filter)")
            else:
                dpf  = nside['profit_factor'] - bside['profit_factor']
                dpnl = nside['net_pnl'] - bside['net_pnl']
                print(
                    f"  {side:<6}: {bside['trades']:>3}t PF={bside['profit_factor']:.3f} → "
                    f"{nt:>3}t PF={nside['profit_factor']:.3f} ({dpf:+.3f}) | "
                    f"PnL Δ={dpnl:+,.0f}"
                )
        print(f"  Shorts rejected by macro filter: {result['rej_macro']}")

    print(f"\n── Monthly breakdown ────────────────────────────────────────────")
    print(f"  {'Month':<10} {'Trades':>6} {'WR':>6} {'PnL':>10} {'PF':>7}", end='')
    if asset == 'BTC':
        print(f"  {'vs base PnL':>12}", end='')
    print()
    print(f"  {'-'*55}")
    for m in monthly:
        pf_str = f"{m['profit_factor']:.3f}" if m['profit_factor'] != float('inf') else "  inf"
        flag   = '  *' if m['profit_factor'] < 1.0 else ''
        line   = f"  {m['month']:<10} {m['trades']:>6} {m['win_rate_pct']:>5.1f}% {m['net_pnl']:>+9.2f}  {pf_str}{flag}"
        if asset == 'BTC' and m['month'] in BASELINE_BTC['monthly']:
            base_pnl = BASELINE_BTC['monthly'][m['month']]['pnl']
            line += f"  {m['net_pnl'] - base_pnl:>+10.2f}"
        print(line)

    print(f"\n  Final equity : ${result['final_equity']:,.2f}")
    print(f"{'='*70}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    assets = [
        {
            'name':     'BTC',
            'path_1h':  'data/BTCUSDT_1h_last_200d.csv',
            'path_15m': 'data/BTCUSDT_15m_last_180d.csv',
        },
        {
            'name':     'ETH',
            'path_1h':  'data/ETHUSDT_1h_last_200d.csv',
            'path_15m': 'data/ETHUSDT_15m_last_180d.csv',
        },
    ]

    all_results = {}

    for cfg in assets:
        print(f"\nRunning {cfg['name']}...")
        result  = run_flat(cfg['path_1h'], cfg['path_15m'], cfg['name'])
        metrics = compute_flat_metrics(result['trades'], INITIAL_CAPITAL)
        monthly = compute_monthly_breakdown(result['trades'])
        sides   = compute_side_breakdown(result['trades'])

        print_report(cfg['name'], result, metrics, monthly, sides)

        all_results[cfg['name']] = {
            'metrics':      metrics,
            'monthly':      monthly,
            'sides':        sides,
            'final_equity': result['final_equity'],
            'rej_macro':    result['rej_macro'],
        }

    out_path = 'data/backtest_exp008.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to {out_path}")
