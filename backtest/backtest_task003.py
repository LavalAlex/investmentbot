"""
TASK 003 — Volume Filter en vela de entrada (15m)

Base: EXP019 SLOPE_CAP (0.20%). Tasks 001-002 results feed into base if KEEP.

Hypothesis:
    Entry candles with above-average volume have more conviction behind the reversal.
    Filtering for vol >= threshold * rolling_mean(vol, 20) improves win rate by
    eliminating low-conviction reversals.

Variants:
    BASE  : no volume filter
    VOL-A : vol >= 1.0× mean(20)  — at or above average
    VOL-B : vol >= 1.2× mean(20)  — 20% above average
    VOL-C : vol >= 1.5× mean(20)  — high conviction only
    VOL-D : vol >= 1.0× mean(50)  — longer lookback

Volume is in base units (BTC or ETH), not USDT.
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

VARIANTS = {
    'BASE':  {'min_ratio': None, 'lookback': None},
    'VOL-A': {'min_ratio': 1.0,  'lookback': 20},
    'VOL-B': {'min_ratio': 1.2,  'lookback': 20},
    'VOL-C': {'min_ratio': 1.5,  'lookback': 20},
    'VOL-D': {'min_ratio': 1.0,  'lookback': 50},
}

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]


def add_vol_ratios(df_15m: pd.DataFrame) -> pd.DataFrame:
    out = df_15m.copy()
    out['vol_mean20'] = out['volume'].rolling(20, min_periods=20).mean()
    out['vol_mean50'] = out['volume'].rolling(50, min_periods=50).mean()
    out['vol_ratio20'] = out['volume'] / out['vol_mean20'].replace(0, float('nan'))
    out['vol_ratio50'] = out['volume'] / out['vol_mean50'].replace(0, float('nan'))
    return out


def calculate_sl_tp(entry, direction, low, high, rr=2.0):
    if direction == 'long':
        sl = low; risk = entry - sl
        if risk <= 0: return None, None
        return sl, entry + rr * risk
    else:
        sl = high; risk = sl - entry
        if risk <= 0: return None, None
        return sl, entry - rr * risk


def vol_ok(row, vcfg) -> bool:
    if vcfg['min_ratio'] is None:
        return True
    lookback = vcfg['lookback']
    col = f'vol_ratio{lookback}'
    val = row.get(col)
    if val is None or pd.isna(val):
        return False
    return val >= vcfg['min_ratio']


def run(df, longs_only, min_sl_pct, vcfg, start=None, end=None):
    if start and end:
        df = df[(df['open_time'] >= start) & (df['open_time'] < end)].reset_index(drop=True)
    equity = INITIAL_CAPITAL
    position = None
    trades = []
    filtered_by_vol = 0

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
                    'vol_ratio':  position['vol_ratio'],
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

        if not vol_ok(row, vcfg):
            filtered_by_vol += 1
            continue

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None: continue
        risk_price = abs(entry - sl)
        if risk_price / entry < min_sl_pct: continue

        vr = row.get('vol_ratio20', float('nan'))
        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'], 'direction': direction,
            'entry': entry, 'sl': sl, 'tp': tp,
            'qty': risk_usd / risk_price,
            'vol_ratio': round(float(vr), 3) if not pd.isna(vr) else None,
        }
    return trades, filtered_by_vol


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
    avg_vr = df['vol_ratio'].dropna().mean() if 'vol_ratio' in df else 0
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'avg_vol_ratio':  round(avg_vr, 3),
    }


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
    print(f"\nTASK003 — Volume Filter  |  SLOPE_CAP=0.20%  |  730d con fees\n")
    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        print(f"[{asset_name}] Preparando datos...", flush=True)
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = prepare_1h(df_1h_raw)
        df_15m = add_vol_ratios(prepare_15m(df_15m_raw))
        df     = align_1h_to_15m(df_15m, df_1h)

        asset_results = {}
        for vname, vcfg in VARIANTS.items():
            trades, n_filtered = run(df, cfg['longs_only'], cfg['min_sl_pct'], vcfg)
            m = metrics(trades)
            asset_results[vname] = {'metrics': m, 'trades': trades, 'n_filtered': n_filtered}
            print(f"  [{vname:6}] trades={m['total_trades']:>3}  filtered={n_filtered:>3}  "
                  f"PF={m['profit_factor']:.3f}  WR={m['win_rate_pct']:.1f}%  "
                  f"Return={m['return_pct']:+.1f}%  MaxDD={m['max_dd_pct']:.1f}%")
        all_results[asset_name] = asset_results

        # Report
        w = 10
        print(f"\n{'='*72}")
        print(f"  TASK003  |  {cfg['label']}  |  BASE PF={cfg['base_pf']:.3f}")
        print(f"{'='*72}")
        print(f"  {'Métrica':<22}" + ''.join(f"  {v:>{w}}" for v in VARIANTS))
        print(f"  {'-'*68}")
        for label, key, fmt in [
            ('Trades',         'total_trades',   '{:d}'),
            ('Filtrados vol',  'n_filtered',     '{:d}'),
            ('Win rate %',     'win_rate_pct',   '{:.1f}'),
            ('Return %',       'return_pct',     '{:+.2f}'),
            ('Max DD %',       'max_dd_pct',     '{:.2f}'),
            ('Profit factor',  'profit_factor',  '{:.3f}'),
            ('Expectancy $',   'expectancy_usd', '{:+.2f}'),
            ('Avg vol ratio',  'avg_vol_ratio',  '{:.2f}×'),
        ]:
            row_out = f"  {label:<22}"
            for v in VARIANTS:
                src = asset_results[v]
                val = src['metrics'].get(key, src.get(key, 0))
                row_out += f"  {fmt.format(val):>{w}}"
            print(row_out)
        print()

    # Walk-forward
    print(f"\n{'='*72}")
    print(f"  TASK003  |  Walk-forward combinado BTC+ETH (4×182d)")
    print(f"{'='*72}")
    print(f"  {'Ventana':<6}  {'Período':<22}" + ''.join(f"  {v:>12}" for v in VARIANTS))
    print(f"  {'-'*70}")
    for wid, start, end, label in WINDOWS:
        row = f"  {wid:<6}  {label:<22}"
        for vname in VARIANTS:
            btc_t = all_results.get('BTC', {}).get(vname, {}).get('trades', [])
            eth_t = all_results.get('ETH', {}).get(vname, {}).get('trades', [])
            cpf = wf_combined_pf(btc_t, eth_t, start, end)
            flag = '✅' if cpf >= 1.0 else '❌'
            row += f"  {cpf:>9.3f} {flag}"
        print(row)

    out_path = 'data/backtest_task003.json'
    with open(out_path, 'w') as f:
        json.dump({a: {v: r['metrics'] for v, r in vr.items()}
                   for a, vr in all_results.items()}, f, indent=2, default=str)
    print(f"\nResultados guardados en {out_path}")
