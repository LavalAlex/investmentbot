"""
EXP009-v2  —  BTC Longs-Only

Hypothesis:
    BTC short side is structurally unprofitable in the current regime.
    Over 180 days, shorts contributed PF=0.982 (-$113 net) while longs
    contributed PF=1.290 (+$1,731 net). The EMA200 macro filter (EXP008)
    only recovered +$301 from shorts, still leaving them barely above 1.0.

    If removing BTC shorts entirely produces better PF, lower DD, and a
    cleaner equity curve — without harming trade frequency enough to lose
    statistical validity — then BTC should run longs-only until a regime
    shift makes shorts viable again.

    ETH is unchanged: both directions remain active (shorts are strong there,
    PF=1.575 over the same period).

Intervention:
    if asset == 'BTC' and direction == 'short' → reject (skip entry).

Baseline   : EXP007_180d (BTC)
             193 trades | WR=36.3% | PF=1.132 | Return=+16.18% | MaxDD=18.53%
             LONG 99t PF=1.290 (+$1,731) | SHORT 94t PF=0.982 (-$113)

Decision criteria:
    KEEP if:
      - BTC PF >= 1.25 (clear improvement from 1.132)
      - BTC MaxDD improves (< 18.53%)
      - Trade count >= 80 (enough for statistical validity)
      - No losing months that weren't losing before
    REVERT if PF < 1.15 or MaxDD worsens
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
    is_market_efficient,
)
from trade_logic import calculate_sl_tp, check_exit
from logger_v2 import setup_logger, log_open, log_close
from backtest_v2 import load_data

INITIAL_CAPITAL = 10_000.0
RISK_PCT        = 0.01
MIN_RISK_PRICE  = 1.0
MIN_SL_DIST_PCT = 0.0015


def run_flat(path_1h: str, path_15m: str, asset: str, longs_only: bool = False) -> dict:
    log_file = f'logs/exp009_{asset}.log'
    logger   = setup_logger(f'exp009_{asset}', log_file=log_file)

    mode = 'LONGS ONLY' if longs_only else 'BOTH DIRECTIONS'
    logger.info(f"\n{'='*60}")
    logger.info(f"EXP009-v2  |  {asset}  |  {mode}")
    logger.info(f"Filters: EXP007_180d stack (EXP002 + ER + SL-dist 0.15%)")
    logger.info(f"{'='*60}\n")

    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h_prep  = prepare_1h(df_1h_raw)
    df_15m_prep = prepare_15m(df_15m_raw)
    df          = align_1h_to_15m(df_15m_prep, df_1h_prep)

    equity       = INITIAL_CAPITAL
    position     = None
    trades       = []
    equity_curve = []
    rej_direction = 0

    for _, row in df.iterrows():
        ts = row['open_time']

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                pnl = (
                    (exit_price - position['entry']) * position['qty']
                    if position['direction'] == 'long'
                    else (position['entry'] - exit_price) * position['qty']
                )
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

        if longs_only and direction == 'short':
            rej_direction += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_price = abs(entry - sl)
        if risk_price < MIN_RISK_PRICE:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        sl_dist_pct = risk_price / entry
        if sl_dist_pct < MIN_SL_DIST_PCT:
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
        pnl = (
            (exit_price - position['entry']) * position['qty']
            if position['direction'] == 'long'
            else (position['entry'] - exit_price) * position['qty']
        )
        equity += pnl
        log_close(logger, position['direction'], position['entry'], exit_price, 'END', pnl, equity)
        trades.append({
            'open_ts': position['open_ts'], 'close_ts': str(last_row['open_time']),
            'direction': position['direction'], 'entry': position['entry'],
            'exit': exit_price, 'sl': position['sl'], 'tp': position['tp'],
            'sl_dist_pct': position['sl_dist_pct'], 'reason': 'END',
            'pnl': round(pnl, 4), 'equity': round(equity, 4),
        })

    logger.info(f"\nRejected (direction filter): {rej_direction}")
    return {
        'asset': asset, 'trades': trades,
        'equity_curve': equity_curve,
        'final_equity': round(equity, 4),
        'rej_direction': rej_direction,
    }


def metrics(trades: list) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    gl   = abs(df[df['pnl'] <= 0]['pnl'].sum())
    gp   = wins['pnl'].sum() if len(wins) else 0.0
    eq   = df['equity'].values
    peak, max_dd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak * 100)
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'net_pnl':        round(df['pnl'].sum(), 2),
        'return_pct':     round(df['pnl'].sum() / INITIAL_CAPITAL * 100, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(gp / gl if gl > 0 else float('inf'), 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
    }


def monthly(trades: list) -> list:
    if not trades:
        return []
    df = pd.DataFrame(trades)
    df['close_ts'] = pd.to_datetime(df['close_ts'])
    df['month']    = df['close_ts'].dt.to_period('M')
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
    'total_trades': 193, 'win_rate_pct': 36.3, 'return_pct': 16.18,
    'max_dd_pct': 18.53, 'profit_factor': 1.132, 'expectancy_usd': 8.38,
    'monthly': {
        '2025-09': -102.95, '2025-10': 369.20, '2025-11': -1003.75,
        '2025-12': -474.93, '2026-01': 1181.84, '2026-02': 786.48, '2026-03': 862.37,
    },
}


def print_report(asset: str, result: dict, m: dict, mo: list) -> None:
    print(f"\n{'='*65}")
    print(f"EXP009-v2  |  {asset}  |  {'LONGS ONLY' if asset == 'BTC' else 'both directions'}")
    print(f"{'='*65}")

    if asset == 'BTC':
        b = BASELINE
        print(f"\n{'Metric':<22} {'EXP007 base':>13} {'EXP008 (ema200)':>15} {'EXP009 (no shorts)':>18}")
        print(f"{'-'*70}")
        exp008 = {'total_trades': 181, 'win_rate_pct': 37.0, 'return_pct': 19.85,
                  'max_dd_pct': 16.87, 'profit_factor': 1.170, 'expectancy_usd': 10.96}
        fields = [
            ('Trades',        'total_trades',   '{:d}'),
            ('Win rate %',    'win_rate_pct',    '{:.1f}'),
            ('Return %',      'return_pct',      '{:+.2f}'),
            ('Max DD %',      'max_dd_pct',      '{:.2f}'),
            ('Profit factor', 'profit_factor',   '{:.3f}'),
            ('Expectancy $',  'expectancy_usd',  '{:+.2f}'),
        ]
        for label, key, fmt in fields:
            bv = b[key]
            e8 = exp008[key]
            e9 = m[key]
            print(f"  {label:<20} {fmt.format(bv):>13} {fmt.format(e8):>15} {fmt.format(e9):>18}")

        print(f"\n  Shorts rejected : {result['rej_direction']} (all)")
        print(f"  Final equity    : ${result['final_equity']:,.2f}")

    print(f"\n── Monthly breakdown ────────────────────────────────────────")
    print(f"  {'Month':<10} {'Trades':>6} {'WR':>6} {'PnL':>10} {'PF':>7}", end='')
    if asset == 'BTC':
        print(f"  {'vs EXP007':>10}", end='')
    print()
    print(f"  {'-'*58}")
    for row in mo:
        pf_str = f"{row['profit_factor']:.3f}" if row['profit_factor'] != float('inf') else "  inf"
        flag   = '  *' if row['profit_factor'] < 1.0 else ''
        line   = f"  {row['month']:<10} {row['trades']:>6} {row['win_rate_pct']:>5.1f}% {row['net_pnl']:>+9.2f}  {pf_str}{flag}"
        if asset == 'BTC' and row['month'] in BASELINE['monthly']:
            base_pnl = BASELINE['monthly'][row['month']]
            line += f"  {row['net_pnl'] - base_pnl:>+9.2f}"
        print(line)

    if asset == 'ETH':
        print(f"\n  Final equity : ${result['final_equity']:,.2f}")
    print(f"{'='*65}\n")


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
        result = run_flat(cfg['path_1h'], cfg['path_15m'], cfg['name'], cfg['longs_only'])
        m      = metrics(result['trades'])
        mo     = monthly(result['trades'])
        print_report(cfg['name'], result, m, mo)
        all_results[cfg['name']] = {
            'metrics': m, 'monthly': mo,
            'final_equity': result['final_equity'],
            'rej_direction': result['rej_direction'],
        }

    out_path = 'data/backtest_exp009.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to {out_path}")
