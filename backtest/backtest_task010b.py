"""
TASK 010-B — 4h alignment filter SOLO en BTC

Resultado de Task010: el filtro 4h mejora BTC dramáticamente (PF 1.787→2.343)
pero destruye ETH shorts (WR 29%, PF 0.686) y rompe W4 en el combinado.

Hipótesis: Aplicar el filtro 4h solo a BTC (longs only) preserva la mejora
sin tocar ETH. ETH queda en BASE (Task007 ETH-SHORT-C).

Variantes:
    BASE        : ningún filtro 4h (Task007 referencia)
    BTC_4H_A    : filtro 4h solo en BTC (cualquier slope positivo)
    BTC_4H_B    : filtro 4h solo en BTC (slope > 0.03%/5 4h-bars)
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
ETH_SHORT_VOL_MIN = 1.0
FIXED_RR          = 2.0
EMA_PERIOD_4H     = 20
SLOPE_LB_4H       = 5

VARIANTS = {
    'BASE':     {'btc_4h': False, 'min_slope': None},
    'BTC_4H_A': {'btc_4h': True,  'min_slope': 0.0},
    'BTC_4H_B': {'btc_4h': True,  'min_slope': 0.03},
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


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def build_4h_context(df_1h_raw):
    df = df_1h_raw.copy()
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df = df.set_index('open_time')
    df4 = df[['open','high','low','close','volume']].resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum',
    }).dropna().reset_index().rename(columns={'open_time': 'open_time_4h'})
    df4['ema20_4h']     = ema(df4['close'], EMA_PERIOD_4H)
    df4['slope_4h_pct'] = (df4['ema20_4h'] - df4['ema20_4h'].shift(SLOPE_LB_4H)) \
                          / df4['ema20_4h'].shift(SLOPE_LB_4H) * 100
    df4['available_at_4h'] = df4['open_time_4h'] + pd.Timedelta(hours=4)
    return df4[['available_at_4h', 'slope_4h_pct']].dropna()


def add_atr_ratio(df):
    out = df.copy()
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low']  - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr14']      = tr.ewm(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False).mean()
    out['atr50_mean'] = out['atr14'].rolling(ATR_MEAN_WINDOW, min_periods=ATR_MEAN_WINDOW).mean()
    out['atr_ratio']  = out['atr14'] / out['atr50_mean'].replace(0, float('nan'))
    return out


def add_vol_ratios(df):
    out = df.copy()
    out['vol_mean50']  = out['volume'].rolling(50, min_periods=50).mean()
    out['vol_ratio50'] = out['volume'] / out['vol_mean50'].replace(0, float('nan'))
    return out


def align_full(df_15m, df_1h_prep, df_4h_ctx):
    df = align_1h_to_15m(df_15m, df_1h_prep)
    atr_right = (df_1h_prep[['available_at', 'atr_ratio']]
                 .dropna(subset=['atr_ratio']).sort_values('available_at').reset_index(drop=True))
    df = df.sort_values('open_time').reset_index(drop=True)
    df = pd.merge_asof(df, atr_right, left_on='open_time', right_on='available_at',
                       direction='backward', suffixes=('', '_atr'))
    df4 = df_4h_ctx.sort_values('available_at_4h').reset_index(drop=True)
    df  = pd.merge_asof(df, df4, left_on='open_time', right_on='available_at_4h', direction='backward')
    return df


def get_scale(atr_ratio):
    if pd.isna(atr_ratio) or atr_ratio <= 0:
        return 1.0
    return max(SCALE_MIN, min(SCALE_MAX, 1.0 / atr_ratio))


def calculate_sl_tp(entry, direction, low, high, rr=FIXED_RR):
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
    filtered_4h = 0

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

        if asset_name == 'ETH' and direction == 'short':
            vr50 = row.get('vol_ratio50')
            if vr50 is None or pd.isna(vr50) or vr50 < ETH_SHORT_VOL_MIN:
                continue

        # 4h filter — solo en BTC
        if asset_name == 'BTC' and vcfg['btc_4h']:
            slope_4h = row.get('slope_4h_pct')
            if slope_4h is None or pd.isna(slope_4h):
                filtered_4h += 1
                continue
            min_s = vcfg['min_slope']
            if direction == 'long'  and slope_4h <= min_s:
                filtered_4h += 1
                continue
            if direction == 'short' and slope_4h >= -min_s:
                filtered_4h += 1
                continue

        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None: continue

        risk_price = abs(entry - sl)
        if risk_price / entry < min_sl_pct: continue

        scale    = get_scale(row.get('atr_ratio', float('nan')))
        risk_usd = equity * RISK_PCT * scale

        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry': entry, 'sl': sl, 'tp': tp,
            'qty': risk_usd / risk_price,
        }
    return trades, filtered_4h


def metrics(trades):
    if not trades:
        return {'total_trades': 0, 'profit_factor': 0.0, 'win_rate_pct': 0.0,
                'return_pct': 0.0, 'max_dd_pct': 0.0, 'expectancy_usd': 0.0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]; loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    pf   = gp / gl if gl > 0 else float('inf')
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
    }


def wf_combined_pf(btc_trades, eth_trades, start, end):
    all_t = [t for t in btc_trades + eth_trades if start <= t['close_time'] < end]
    if not all_t: return 0.0
    gp = sum(t['pnl'] for t in all_t if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in all_t if t['pnl'] <= 0))
    return round(gp / gl, 3) if gl > 0 else float('inf')


if __name__ == '__main__':
    print(f"\nTASK010-B — 4h filter SOLO BTC  |  ETH sin cambios  |  730d\n")
    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        print(f"[{asset_name}] Preparando datos...", flush=True)
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = add_atr_ratio(prepare_1h(df_1h_raw))
        df_15m = add_vol_ratios(prepare_15m(df_15m_raw))
        df_4h  = build_4h_context(df_1h_raw)
        df     = align_full(df_15m, df_1h, df_4h)

        asset_results = {}
        for vname, vcfg in VARIANTS.items():
            trades, f4h = run(df, cfg['longs_only'], cfg['min_sl_pct'], vcfg, asset_name)
            m = metrics(trades)
            asset_results[vname] = {'metrics': m, 'trades': trades}
            extra = f"  filtered_4h={f4h}" if f4h > 0 else ""
            print(f"  [{vname:10}] trades={m['total_trades']:>3}  PF={m['profit_factor']:.3f}  "
                  f"WR={m['win_rate_pct']:.1f}%  Return={m['return_pct']:+.1f}%  "
                  f"MaxDD={m['max_dd_pct']:.2f}%{extra}")
        all_results[asset_name] = asset_results

        print(f"\n  {'Métrica':<20}" + ''.join(f"  {v:>12}" for v in VARIANTS))
        print(f"  {'-'*65}")
        for label, key, fmt in [
            ('Trades',        'total_trades',   '{:d}'),
            ('Win rate %',    'win_rate_pct',   '{:.1f}'),
            ('Return %',      'return_pct',     '{:+.2f}'),
            ('Max DD %',      'max_dd_pct',     '{:.2f}'),
            ('Profit factor', 'profit_factor',  '{:.3f}'),
            ('Expectancy $',  'expectancy_usd', '{:+.2f}'),
        ]:
            row_str = f"  {label:<20}"
            for v in VARIANTS:
                val = asset_results[v]['metrics'].get(key, 0)
                row_str += f"  {fmt.format(val):>12}"
            print(row_str)
        print()

    print(f"\n{'='*75}")
    print(f"  TASK010-B  |  Walk-forward combinado BTC+ETH (4×182d)")
    print(f"{'='*75}")
    print(f"  {'Ventana':<6}  {'Período':<22}" + ''.join(f"  {v:>14}" for v in VARIANTS))
    print(f"  {'-'*75}")
    for wid, start, end, label in WINDOWS:
        row_str = f"  {wid:<6}  {label:<22}"
        for vname in VARIANTS:
            btc_t = all_results.get('BTC', {}).get(vname, {}).get('trades', [])
            eth_t = all_results.get('ETH', {}).get(vname, {}).get('trades', [])
            cpf   = wf_combined_pf(btc_t, eth_t, start, end)
            flag  = '✅' if cpf >= 1.0 else '❌'
            row_str += f"  {cpf:>11.3f} {flag}"
        print(row_str)

    out_path = 'data/backtest_task010b.json'
    with open(out_path, 'w') as f:
        json.dump({a: {v: r['metrics'] for v, r in vr.items()}
                   for a, vr in all_results.items()}, f, indent=2, default=str)
    print(f"\nResultados guardados en {out_path}")
