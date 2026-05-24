"""
TASK 009 — Dynamic R:R based on Kaufman Efficiency Ratio

Base: COMBINED final (SLOPE_CAP + DYN-B + TIME-B + ETH-SHORT-C) from Task007.

Hypothesis:
    The fixed 2:1 R:R ignores market context. When ER is high, price has real
    directional momentum and can sustain larger moves — extending TP captures
    more of the trend. When ER is borderline (0.15-0.20), the move is weaker
    and a tighter TP locks in gains before reversal.

    TP multiplier formula (variant A):
        tp_mult = clamp(1.5 + er24 * 4.0,  min=1.5,  max=3.0)
        ER 0.15 → 2.1×   ER 0.25 → 2.5×   ER 0.40 → 3.0×   ER 0.60 → 3.0× (cap)

    Variant B — steeper curve:
        tp_mult = clamp(1.5 + er24 * 6.0,  min=1.5,  max=3.0)
        ER 0.15 → 2.4×   ER 0.25 → 3.0×

    Variant C — stepped thresholds (simpler, less overfitting risk):
        ER >= 0.30 → 3:1,  ER >= 0.20 → 2.5:1,  else → 2:1

Variants:
    BASE      : fixed 2:1 (Task007 ETH-SHORT-C reference)
    DYN_TP_A  : continuous formula, slope 4.0
    DYN_TP_B  : continuous formula, slope 6.0
    DYN_TP_C  : stepped thresholds
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
ATR_PERIOD       = 14
ATR_MEAN_WINDOW  = 50
SCALE_MIN        = 0.6
SCALE_MAX        = 1.2
TIME_B_START     = 7
TIME_B_END       = 21
ETH_SHORT_VOL_LOOKBACK = 50
ETH_SHORT_VOL_MIN      = 1.0

VARIANTS = {
    'BASE':     {'tp_mode': 'fixed',   'slope': None, 'steps': None},
    'DYN_TP_A': {'tp_mode': 'linear',  'slope': 4.0,  'steps': None},
    'DYN_TP_B': {'tp_mode': 'linear',  'slope': 6.0,  'steps': None},
    'DYN_TP_C': {'tp_mode': 'stepped', 'slope': None, 'steps': [(0.30, 3.0), (0.20, 2.5), (0.0, 2.0)]},
}

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]

ASSET_CONFIGS = {
    'BTC': {'path_1h': 'data/BTCUSDT_1h_last_740d.csv', 'path_15m': 'data/BTCUSDT_15m_last_730d.csv',
            'longs_only': True,  'min_sl_pct': 0.0030},
    'ETH': {'path_1h': 'data/ETHUSDT_1h_last_740d.csv', 'path_15m': 'data/ETHUSDT_15m_last_730d.csv',
            'longs_only': False, 'min_sl_pct': 0.0050},
}


def add_atr_ratio(df):
    out = df.copy()
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low']  - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr14']     = tr.ewm(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False).mean()
    out['atr50_mean']= out['atr14'].rolling(ATR_MEAN_WINDOW, min_periods=ATR_MEAN_WINDOW).mean()
    out['atr_ratio'] = out['atr14'] / out['atr50_mean'].replace(0, float('nan'))
    return out


def add_vol_ratios(df):
    out = df.copy()
    out['vol_mean50'] = out['volume'].rolling(50, min_periods=50).mean()
    out['vol_ratio50']= out['volume'] / out['vol_mean50'].replace(0, float('nan'))
    return out


def align_with_atr(df_15m, df_1h_prep):
    df = align_1h_to_15m(df_15m, df_1h_prep)
    right = (df_1h_prep[['available_at', 'atr_ratio']]
             .dropna(subset=['atr_ratio']).sort_values('available_at').reset_index(drop=True))
    df = df.sort_values('open_time').reset_index(drop=True)
    df = pd.merge_asof(df, right, left_on='open_time', right_on='available_at',
                       direction='backward', suffixes=('', '_dup'))
    return df


def get_scale(atr_ratio):
    if pd.isna(atr_ratio) or atr_ratio <= 0:
        return 1.0
    return max(SCALE_MIN, min(SCALE_MAX, 1.0 / atr_ratio))


def get_tp_mult(er24, vcfg) -> float:
    mode = vcfg['tp_mode']
    if mode == 'fixed':
        return 2.0
    if pd.isna(er24) or er24 <= 0:
        return 2.0
    if mode == 'linear':
        return min(3.0, max(1.5, 1.5 + er24 * vcfg['slope']))
    if mode == 'stepped':
        for threshold, mult in vcfg['steps']:
            if er24 >= threshold:
                return mult
    return 2.0


def calculate_sl_tp(entry, direction, low, high, rr):
    if direction == 'long':
        sl = low; risk = entry - sl
        if risk <= 0: return None, None
        return sl, entry + rr * risk
    else:
        sl = high; risk = sl - entry
        if risk <= 0: return None, None
        return sl, entry - rr * risk


def run(df, longs_only, min_sl_pct, vcfg, asset_name, start=None, end=None):
    if start and end:
        df = df[(df['open_time'] >= start) & (df['open_time'] < end)].reset_index(drop=True)
    equity   = INITIAL_CAPITAL
    position = None
    trades   = []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty   = position['qty']
                gross = (exit_price - position['entry']) * qty if position['direction'] == 'long' \
                        else (position['entry'] - exit_price) * qty
                fee   = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                pnl   = gross - fee
                equity += pnl
                trades.append({
                    'open_time':  str(position['open_time']),
                    'close_time': str(row['open_time']),
                    'direction':  position['direction'],
                    'entry':      position['entry'],
                    'exit':       exit_price,
                    'reason':     reason,
                    'tp_mult':    position['tp_mult'],
                    'er24':       position['er24'],
                    'pnl':        round(pnl, 4),
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

        ts   = pd.Timestamp(row['open_time'])
        hour = ts.hour if ts.tzinfo is None else ts.tz_convert('UTC').hour
        if not (TIME_B_START <= hour < TIME_B_END):
            continue

        direction = 'long' if trend == 'up' else 'short'

        # ETH-SHORT-C vol filter
        if asset_name == 'ETH' and direction == 'short':
            vr50 = row.get('vol_ratio50')
            if vr50 is None or pd.isna(vr50) or vr50 < ETH_SHORT_VOL_MIN:
                continue

        entry   = row['close']
        er24    = row.get('er24', float('nan'))
        tp_mult = get_tp_mult(er24, vcfg)
        sl, tp  = calculate_sl_tp(entry, direction, row['low'], row['high'], tp_mult)
        if sl is None: continue

        risk_price = abs(entry - sl)
        if risk_price / entry < min_sl_pct: continue

        scale    = get_scale(row.get('atr_ratio', float('nan')))
        risk_usd = equity * RISK_PCT * scale

        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry': entry, 'sl': sl, 'tp': tp,
            'qty':    risk_usd / risk_price,
            'tp_mult': round(tp_mult, 2),
            'er24':    round(float(er24), 3) if not pd.isna(er24) else None,
        }
    return trades


def metrics(trades):
    if not trades:
        return {'total_trades': 0, 'profit_factor': 0.0, 'win_rate_pct': 0.0,
                'return_pct': 0.0, 'max_dd_pct': 0.0, 'expectancy_usd': 0.0,
                'avg_tp_mult': 0.0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]; loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    pf   = gp / gl if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    ret = (df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    avg_mult = df['tp_mult'].mean() if 'tp_mult' in df else 2.0
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'avg_tp_mult':    round(float(avg_mult), 2),
    }


def wf_combined_pf(btc_trades, eth_trades, start, end):
    all_t = [t for t in btc_trades + eth_trades if start <= t['close_time'] < end]
    if not all_t: return 0.0
    gp = sum(t['pnl'] for t in all_t if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in all_t if t['pnl'] <= 0))
    return round(gp / gl, 3) if gl > 0 else float('inf')


if __name__ == '__main__':
    print(f"\nTASK009 — Dynamic R:R (Kaufman ER)  |  Base: COMBINED (Task007 ETH-SHORT-C)  |  730d\n")
    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        print(f"[{asset_name}] Preparando datos...", flush=True)
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = add_atr_ratio(prepare_1h(df_1h_raw))
        df_15m = add_vol_ratios(prepare_15m(df_15m_raw))
        df     = align_with_atr(df_15m, df_1h)

        asset_results = {}
        for vname, vcfg in VARIANTS.items():
            trades = run(df, cfg['longs_only'], cfg['min_sl_pct'], vcfg, asset_name)
            m      = metrics(trades)
            asset_results[vname] = {'metrics': m, 'trades': trades}
            print(f"  [{vname:10}] trades={m['total_trades']:>3}  PF={m['profit_factor']:.3f}  "
                  f"WR={m['win_rate_pct']:.1f}%  Return={m['return_pct']:+.1f}%  "
                  f"MaxDD={m['max_dd_pct']:.2f}%  avg_mult={m['avg_tp_mult']:.2f}×")
        all_results[asset_name] = asset_results

        # TP mult distribution for DYN_TP_A
        if 'DYN_TP_A' in asset_results:
            tdf = pd.DataFrame(asset_results['DYN_TP_A']['trades'])
            if not tdf.empty and 'tp_mult' in tdf:
                print(f"\n  ── Distribución tp_mult (DYN_TP_A) para {asset_name}:")
                for bucket, lo, hi in [('<2.0',0,2.0),('2.0–2.5',2.0,2.5),('2.5–3.0',2.5,3.0),('3.0',3.0,99)]:
                    sub = tdf[(tdf['tp_mult'] >= lo) & (tdf['tp_mult'] < hi)]
                    if sub.empty: continue
                    wins_b = sub[sub['pnl'] > 0]
                    gl_b = abs(sub[sub['pnl']<=0]['pnl'].sum())
                    pf_b = wins_b['pnl'].sum() / gl_b if gl_b > 0 else float('inf')
                    print(f"  tp_mult {bucket:<10}  T={len(sub):>3}  WR={len(wins_b)/len(sub)*100:.0f}%  PF={pf_b:.3f}")

        print(f"\n  {'Métrica':<20}" + ''.join(f"  {v:>12}" for v in VARIANTS))
        print(f"  {'-'*80}")
        for label, key, fmt in [
            ('Trades',        'total_trades',   '{:d}'),
            ('Win rate %',    'win_rate_pct',   '{:.1f}'),
            ('Return %',      'return_pct',     '{:+.2f}'),
            ('Max DD %',      'max_dd_pct',     '{:.2f}'),
            ('Profit factor', 'profit_factor',  '{:.3f}'),
            ('Expectancy $',  'expectancy_usd', '{:+.2f}'),
            ('Avg TP mult',   'avg_tp_mult',    '{:.2f}×'),
        ]:
            row_str = f"  {label:<20}"
            for v in VARIANTS:
                val = asset_results[v]['metrics'].get(key, 0)
                row_str += f"  {fmt.format(val):>12}"
            print(row_str)
        print()

    print(f"\n{'='*85}")
    print(f"  TASK009  |  Walk-forward combinado BTC+ETH (4×182d)")
    print(f"{'='*85}")
    print(f"  {'Ventana':<6}  {'Período':<22}" + ''.join(f"  {v:>14}" for v in VARIANTS))
    print(f"  {'-'*85}")
    for wid, start, end, label in WINDOWS:
        row_str = f"  {wid:<6}  {label:<22}"
        for vname in VARIANTS:
            btc_t = all_results.get('BTC', {}).get(vname, {}).get('trades', [])
            eth_t = all_results.get('ETH', {}).get(vname, {}).get('trades', [])
            cpf   = wf_combined_pf(btc_t, eth_t, start, end)
            flag  = '✅' if cpf >= 1.0 else '❌'
            row_str += f"  {cpf:>11.3f} {flag}"
        print(row_str)

    out_path = 'data/backtest_task009.json'
    with open(out_path, 'w') as f:
        json.dump({a: {v: r['metrics'] for v, r in vr.items()}
                   for a, vr in all_results.items()}, f, indent=2, default=str)
    print(f"\nResultados guardados en {out_path}")
