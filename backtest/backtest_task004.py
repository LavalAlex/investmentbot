"""
TASK 004 — Time-of-Day Filter

Base: EXP019 SLOPE_CAP (0.20%).

Hypothesis:
    Asian session (00:00-07:00 UTC) has lower liquidity and wider spreads.
    SLs placed at candle extremes are more vulnerable to noise stop-hunts.
    Filtering entries to higher-liquidity hours improves win rate.

Variants (entry hour in UTC):
    BASE   : all hours
    TIME-A : 07:00–17:00  Europe + US overlap
    TIME-B : 07:00–21:00  Europe + full US session
    TIME-C : 13:00–17:00  Only EU/US overlap (peak liquidity)
    TIME-D : exclude 00:00–06:00  drop only deep Asia

Also includes a diagnostic: PF breakdown by session to validate the hypothesis.
"""

import json, os, sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend, is_trend_strong, is_pullback_quality,
    is_entry_trigger, is_candle_quality,
    is_range_sufficient, is_market_efficient,
)
from core.trade_logic import check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005
MAX_SLOPE_PCT    = 0.20

# Allowed entry hours (UTC), None = all hours
VARIANTS = {
    'BASE':   None,
    'TIME-A': (7, 17),
    'TIME-B': (7, 21),
    'TIME-C': (13, 17),
    'TIME-D': (6, 24),   # exclude 00-05 (deep Asia only)
}

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]


def session_label(hour):
    if 0 <= hour < 7:   return 'ASIA'
    if 7 <= hour < 13:  return 'EUROPE'
    if 13 <= hour < 17: return 'OVERLAP'
    return 'US_LATE'


def hour_ok(hour, allowed):
    if allowed is None: return True
    lo, hi = allowed
    return lo <= hour < hi


def calculate_sl_tp(entry, direction, low, high, rr=2.0):
    if direction == 'long':
        sl = low; risk = entry - sl
        if risk <= 0: return None, None
        return sl, entry + rr * risk
    else:
        sl = high; risk = sl - entry
        if risk <= 0: return None, None
        return sl, entry - rr * risk


def run(df, longs_only, min_sl_pct, allowed_hours, start=None, end=None):
    if start and end:
        df = df[(df['open_time'] >= start) & (df['open_time'] < end)].reset_index(drop=True)
    equity = INITIAL_CAPITAL
    position = None
    trades = []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty = position['qty']
                gross = (exit_price - position['entry']) * qty if position['direction'] == 'long' \
                        else (position['entry'] - exit_price) * qty
                fee = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'open_time':  str(position['open_time']),
                    'close_time': str(row['open_time']),
                    'direction':  position['direction'],
                    'entry':      position['entry'],
                    'exit':       exit_price,
                    'reason':     reason,
                    'session':    position['session'],
                    'hour':       position['hour'],
                    'gross_pnl':  round(gross, 4),
                    'fee_usd':    round(fee, 4),
                    'pnl':        round(net_pnl, 4),
                    'equity':     round(equity, 4),
                })
                position = None
            continue

        trend = get_trend(row)
        if trend is None: continue
        if longs_only and trend != 'up': continue
        if not is_trend_strong(row): continue
        if not is_pullback_quality(row, trend): continue
        if not is_entry_trigger(row, trend): continue
        if not is_candle_quality(row, trend): continue
        if not is_range_sufficient(row): continue
        if not is_market_efficient(row): continue

        slope = row.get('ema50_slope_pct')
        if not pd.isna(slope) and abs(slope) > MAX_SLOPE_PCT:
            continue

        ts = pd.Timestamp(row['open_time'])
        hour = ts.hour if ts.tzinfo is None else ts.tz_convert('UTC').hour
        if not hour_ok(hour, allowed_hours):
            continue

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None: continue
        risk_price = abs(entry - sl)
        if risk_price / entry < min_sl_pct: continue

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'], 'direction': direction,
            'entry': entry, 'sl': sl, 'tp': tp,
            'qty': risk_usd / risk_price,
            'session': session_label(hour),
            'hour': hour,
        }
    return trades


def metrics(trades):
    if not trades: return {'total_trades': 0}
    df = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]; loss = df[df['pnl'] <= 0]
    gp = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    pf = gp / gl if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    ret = (df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
    }


def session_breakdown(trades):
    if not trades: return {}
    df = pd.DataFrame(trades)
    result = {}
    for sess in ['ASIA', 'EUROPE', 'OVERLAP', 'US_LATE']:
        sub = df[df['session'] == sess]
        if len(sub) == 0:
            result[sess] = {}
            continue
        wins = sub[sub['pnl'] > 0]; loss = sub[sub['pnl'] <= 0]
        gp = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
        pf = gp / gl if gl > 0 else float('inf')
        result[sess] = {
            'trades': len(sub),
            'win_rate_pct': round(len(wins) / len(sub) * 100, 1),
            'profit_factor': round(pf, 3),
            'return_pct': round(sub['pnl'].sum() / INITIAL_CAPITAL * 100, 2),
        }
    return result


def wf_combined_pf(btc_trades, eth_trades, start, end):
    all_t = [t for t in btc_trades + eth_trades if start <= t['close_time'] < end]
    if not all_t: return 0.0
    gp = sum(t['pnl'] for t in all_t if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in all_t if t['pnl'] <= 0))
    return round(gp / gl, 3) if gl > 0 else float('inf')


ASSET_CONFIGS = {
    'BTC': {'path_1h': 'data/BTCUSDT_1h_last_740d.csv', 'path_15m': 'data/BTCUSDT_15m_last_730d.csv',
            'longs_only': True,  'min_sl_pct': 0.0030, 'label': 'BTC/USDT', 'base_pf': 1.344},
    'ETH': {'path_1h': 'data/ETHUSDT_1h_last_740d.csv', 'path_15m': 'data/ETHUSDT_15m_last_730d.csv',
            'longs_only': False, 'min_sl_pct': 0.0050, 'label': 'ETH/USDT', 'base_pf': 1.318},
}


if __name__ == '__main__':
    print(f"\nTASK004 — Time-of-Day Filter  |  SLOPE_CAP=0.20%  |  730d con fees\n")
    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        print(f"[{asset_name}] Preparando datos...", flush=True)
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = prepare_1h(df_1h_raw)
        df_15m = prepare_15m(df_15m_raw)
        df     = align_1h_to_15m(df_15m, df_1h)

        asset_results = {}
        for vname, allowed in VARIANTS.items():
            trades = run(df, cfg['longs_only'], cfg['min_sl_pct'], allowed)
            m = metrics(trades)
            sb = session_breakdown(trades) if vname == 'BASE' else {}
            asset_results[vname] = {'metrics': m, 'trades': trades, 'session_breakdown': sb}
            print(f"  [{vname:6}] trades={m['total_trades']:>3}  PF={m['profit_factor']:.3f}  "
                  f"WR={m['win_rate_pct']:.1f}%  Return={m['return_pct']:+.1f}%  MaxDD={m['max_dd_pct']:.1f}%")
        all_results[asset_name] = asset_results

        # Session diagnostic for BASE
        print(f"\n  ── Diagnóstico por sesión (BASE) — {asset_name}")
        sb = asset_results['BASE']['session_breakdown']
        print(f"  {'Sesión':<12}  {'T':>4}  {'WR%':>5}  {'PF':>6}  {'Ret%':>7}")
        print(f"  {'-'*40}")
        for sess in ['ASIA', 'EUROPE', 'OVERLAP', 'US_LATE']:
            sm = sb.get(sess, {})
            if sm:
                print(f"  {sess:<12}  {sm['trades']:>4}  {sm['win_rate_pct']:>4.0f}%  "
                      f"{sm['profit_factor']:>6.3f}  {sm['return_pct']:>+6.2f}%")

        # Summary table
        w = 10
        print(f"\n  {'Métrica':<20}" + ''.join(f"  {v:>{w}}" for v in VARIANTS))
        print(f"  {'-'*65}")
        for label, key, fmt in [
            ('Trades',        'total_trades',   '{:d}'),
            ('Win rate %',    'win_rate_pct',   '{:.1f}'),
            ('Return %',      'return_pct',     '{:+.2f}'),
            ('Max DD %',      'max_dd_pct',     '{:.2f}'),
            ('Profit factor', 'profit_factor',  '{:.3f}'),
            ('Expectancy $',  'expectancy_usd', '{:+.2f}'),
        ]:
            row = f"  {label:<20}"
            for v in VARIANTS:
                val = asset_results[v]['metrics'].get(key, 0)
                row += f"  {fmt.format(val):>{w}}"
            print(row)
        print()

    # Walk-forward
    print(f"\n{'='*72}")
    print(f"  TASK004  |  Walk-forward combinado BTC+ETH (4×182d)")
    print(f"{'='*72}")
    print(f"  {'Ventana':<6}  {'Período':<22}" + ''.join(f"  {v:>12}" for v in VARIANTS))
    print(f"  {'-'*72}")
    for wid, start, end, label in WINDOWS:
        row = f"  {wid:<6}  {label:<22}"
        for vname in VARIANTS:
            btc_t = all_results.get('BTC', {}).get(vname, {}).get('trades', [])
            eth_t = all_results.get('ETH', {}).get(vname, {}).get('trades', [])
            cpf = wf_combined_pf(btc_t, eth_t, start, end)
            flag = '✅' if cpf >= 1.0 else '❌'
            row += f"  {cpf:>9.3f} {flag}"
        print(row)

    out_path = 'data/backtest_task004.json'
    with open(out_path, 'w') as f:
        json.dump({a: {v: r['metrics'] for v, r in vr.items()}
                   for a, vr in all_results.items()}, f, indent=2, default=str)
    print(f"\nResultados guardados en {out_path}")
