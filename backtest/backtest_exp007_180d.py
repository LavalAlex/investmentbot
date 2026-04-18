"""
EXP007-v2  —  180-day flat backtest (paper monitor exact replication)

Replicates exactly what paper_monitor.py runs:
  - EXP002 filters: trend, trend strength, pullback quality, entry trigger,
                    candle quality, range sufficient, market efficiency (ER)
  - EXP007 filter: MIN_SL_DIST_PCT = 0.15%

Purpose: verify that the strategy running live in paper trading is profitable
         over the last 180 days, with full metrics including monthly breakdown
         and long/short contribution.

Assets  : BTC/USDT, ETH/USDT
Period  : last 180d CSV (Sep 2025 – Mar 2026)
Capital : $10,000 | Risk: 1% per trade
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

# ── Config ────────────────────────────────────────────────────────────────────
INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
MIN_RISK_PRICE   = 1.0
MIN_SL_DIST_PCT  = 0.0015   # EXP007: 0.15%


# ── Core backtest loop ────────────────────────────────────────────────────────

def run_flat(path_1h: str, path_15m: str, asset: str) -> dict:
    log_file = f'logs/exp007_180d_{asset}.log'
    logger   = setup_logger(f'exp007_180d_{asset}', log_file=log_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"EXP007-v2 180d  |  {asset}")
    logger.info(f"Filters: EXP002 + is_market_efficient + MIN_SL_DIST={MIN_SL_DIST_PCT*100:.2f}%")
    logger.info(f"{'='*60}\n")

    df_1h, df_15m = load_data(path_1h, path_15m)
    df_1h_prep    = prepare_1h(df_1h)
    df_15m_prep   = prepare_15m(df_15m)
    df            = align_1h_to_15m(df_15m_prep, df_1h_prep)

    equity       = INITIAL_CAPITAL
    position     = None
    trades       = []
    equity_curve = []

    rej_trend = rej_strength = rej_pullback = rej_trigger = 0
    rej_candle = rej_range = rej_er = rej_sl_dist = 0

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

        # ── EXP002 filters ────────────────────────────────────────────────────
        trend = get_trend(row)
        if trend is None:
            rej_trend += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_trend_strong(row):
            rej_strength += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_pullback_quality(row, trend):
            rej_pullback += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_entry_trigger(row, trend):
            rej_trigger += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_candle_quality(row, trend):
            rej_candle += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_range_sufficient(row):
            rej_range += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_market_efficient(row):
            rej_er += 1
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

        # ── EXP007 filter ─────────────────────────────────────────────────────
        sl_dist_pct = risk_price / entry
        if sl_dist_pct < MIN_SL_DIST_PCT:
            rej_sl_dist += 1
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

    # close any open position at end of data
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

    logger.info(f"\nFilter rejection breakdown:")
    logger.info(f"  No trend        : {rej_trend}")
    logger.info(f"  Trend not strong: {rej_strength}")
    logger.info(f"  Pullback quality: {rej_pullback}")
    logger.info(f"  Entry trigger   : {rej_trigger}")
    logger.info(f"  Candle quality  : {rej_candle}")
    logger.info(f"  Range not suff  : {rej_range}")
    logger.info(f"  Market eff (ER) : {rej_er}")
    logger.info(f"  SL dist (EXP007): {rej_sl_dist}")

    return {
        'asset':         asset,
        'trades':        trades,
        'equity_curve':  equity_curve,
        'final_equity':  round(equity, 4),
        'rejections': {
            'no_trend':        rej_trend,
            'trend_strength':  rej_strength,
            'pullback_quality': rej_pullback,
            'entry_trigger':   rej_trigger,
            'candle_quality':  rej_candle,
            'range_sufficient': rej_range,
            'market_eff_er':   rej_er,
            'sl_dist_exp007':  rej_sl_dist,
        },
    }


# ── Metrics helpers ───────────────────────────────────────────────────────────

def compute_flat_metrics(trades: list, initial_capital: float) -> dict:
    if not trades:
        return {}

    df = pd.DataFrame(trades)
    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]

    gross_profit  = wins['pnl'].sum()   if len(wins)   else 0.0
    gross_loss    = abs(losses['pnl'].sum()) if len(losses) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    win_rate      = len(wins) / len(df) * 100
    expectancy    = df['pnl'].mean()
    net_pnl       = df['pnl'].sum()
    return_pct    = net_pnl / initial_capital * 100

    # max drawdown on equity curve of closed trades
    eq = df['equity'].values
    peak = eq[0]
    max_dd = 0.0
    for e in eq:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(win_rate, 1),
        'gross_profit':   round(gross_profit, 2),
        'gross_loss':     round(gross_loss, 2),
        'net_pnl':        round(net_pnl, 2),
        'return_pct':     round(return_pct, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(profit_factor, 3),
        'expectancy_usd': round(expectancy, 2),
    }


def compute_monthly_breakdown(trades: list) -> list:
    if not trades:
        return []

    df = pd.DataFrame(trades)
    df['close_ts'] = pd.to_datetime(df['close_ts'])
    df['month']    = df['close_ts'].dt.to_period('M')

    rows = []
    for month, group in df.groupby('month'):
        wins   = group[group['pnl'] > 0]
        losses = group[group['pnl'] <= 0]
        gp     = wins['pnl'].sum()   if len(wins)   else 0.0
        gl     = abs(losses['pnl'].sum()) if len(losses) else 0.0
        pf     = gp / gl if gl > 0 else float('inf')
        rows.append({
            'month':        str(month),
            'trades':       len(group),
            'wins':         len(wins),
            'losses':       len(losses),
            'win_rate_pct': round(len(wins) / len(group) * 100, 1),
            'net_pnl':      round(group['pnl'].sum(), 2),
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
        losses = sub[sub['pnl'] <= 0]
        gp = wins['pnl'].sum()   if len(wins)   else 0.0
        gl = abs(losses['pnl'].sum()) if len(losses) else 0.0
        pf = gp / gl if gl > 0 else float('inf')
        result[direction] = {
            'trades':       len(sub),
            'win_rate_pct': round(len(wins) / len(sub) * 100, 1),
            'net_pnl':      round(sub['pnl'].sum(), 2),
            'profit_factor': round(pf, 3),
        }
    return result


# ── Print report ──────────────────────────────────────────────────────────────

def print_report(asset: str, result: dict, metrics: dict, monthly: list, sides: dict) -> None:
    print(f"\n{'='*65}")
    print(f"EXP007-v2 180d  |  {asset}  |  MIN_SL_DIST=0.15%  |  paper monitor exact")
    print(f"{'='*65}")

    print(f"\n── Overall ──────────────────────────────────────────────────")
    print(f"  Trades        : {metrics['total_trades']}")
    print(f"  Win rate      : {metrics['win_rate_pct']}%")
    print(f"  Net PnL       : ${metrics['net_pnl']:+,.2f}")
    print(f"  Return        : {metrics['return_pct']:+.2f}%")
    print(f"  Max drawdown  : {metrics['max_dd_pct']:.2f}%")
    print(f"  Profit factor : {metrics['profit_factor']:.3f}")
    print(f"  Expectancy    : ${metrics['expectancy_usd']:+.2f}/trade")
    print(f"  Final equity  : ${result['final_equity']:,.2f}")

    print(f"\n── Long / Short breakdown ───────────────────────────────────")
    for side, s in sides.items():
        if s['trades'] == 0:
            print(f"  {side.upper():<6}: 0 trades")
        else:
            print(f"  {side.upper():<6}: {s['trades']} trades | WR={s['win_rate_pct']}% | PF={s['profit_factor']:.3f} | PnL=${s['net_pnl']:+,.2f}")

    print(f"\n── Monthly breakdown ────────────────────────────────────────")
    print(f"  {'Month':<10} {'Trades':>6} {'WR':>6} {'PnL':>10} {'PF':>7}")
    print(f"  {'-'*45}")
    for m in monthly:
        pf_str = f"{m['profit_factor']:.3f}" if m['profit_factor'] != float('inf') else "  inf"
        flag   = '  *' if m['profit_factor'] < 1.0 else ''
        print(f"  {m['month']:<10} {m['trades']:>6} {m['win_rate_pct']:>5.1f}% {m['net_pnl']:>+9.2f}  {pf_str}{flag}")

    print(f"\n── Filter rejections ────────────────────────────────────────")
    rej = result['rejections']
    print(f"  Market eff (ER): {rej['market_eff_er']}")
    print(f"  SL dist EXP007 : {rej['sl_dist_exp007']}")
    print(f"{'='*65}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    assets = [
        {
            'name':    'BTC',
            'path_1h': 'data/BTCUSDT_1h_last_200d.csv',
            'path_15m': 'data/BTCUSDT_15m_last_180d.csv',
        },
        {
            'name':    'ETH',
            'path_1h': 'data/ETHUSDT_1h_last_200d.csv',
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
            'metrics':  metrics,
            'monthly':  monthly,
            'sides':    sides,
            'final_equity': result['final_equity'],
            'rejections':   result['rejections'],
        }

    out_path = 'data/backtest_exp007_180d.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to {out_path}")
