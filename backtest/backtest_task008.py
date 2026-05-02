"""
TASK 008 — Diagnóstico de SLOPE_CAP en producción

Problema detectado (2026-05-02):
    Deploy-004 introdujo SLOPE_CAP (ema50_slope > 0.20% → skip) que está
    bloqueando el 100% de las señales BTC durante el rally actual (slope 0.22–0.32%).
    0 trades en 3 días post-deploy en un mercado tendencial.

Hipótesis:
    El SLOPE_CAP está demasiado ajustado. Eliminar el filtro (o subir el umbral)
    debería restaurar la frecuencia de trades sin destruir el PF.

Variantes (una variable a la vez, sobre TIME-B + DYN-B + ETH-SHORT-C):
    PROD        : configuración actual en producción (con SLOPE_CAP 0.20%)
    NO_CAP      : igual pero sin SLOPE_CAP  ← solución propuesta
    CAP_050     : SLOPE_CAP relajado a 0.50%
    CAP_100     : SLOPE_CAP relajado a 1.00%

Criterio de éxito:
    PF > 1.2 sobre 730d Y PF > 1.0 en cada ventana de 182d, con fees.
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

ATR_PERIOD      = 14
ATR_MEAN_WINDOW = 50
SCALE_MIN       = 0.6
SCALE_MAX       = 1.2
TIME_B_START    = 7
TIME_B_END      = 21
ETH_SHORT_VOL_MIN_RATIO = 1.0
ETH_SHORT_VOL_LOOKBACK  = 50

# SLOPE_CAP variants: None = sin filtro
VARIANTS = {
    'PROD':    {'slope_cap': 0.20},
    'NO_CAP':  {'slope_cap': None},
    'CAP_050': {'slope_cap': 0.50},
    'CAP_100': {'slope_cap': 1.00},
}

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]


def prepare_1h_with_atr(df_1h: pd.DataFrame) -> pd.DataFrame:
    out = prepare_1h(df_1h)
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low']  - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr14']      = tr.ewm(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False).mean()
    out['atr50_mean'] = out['atr14'].rolling(ATR_MEAN_WINDOW, min_periods=ATR_MEAN_WINDOW).mean()
    out['atr_ratio']  = out['atr14'] / out['atr50_mean'].replace(0, float('nan'))
    return out


def prepare_15m_with_vol(df_15m: pd.DataFrame) -> pd.DataFrame:
    out = prepare_15m(df_15m)
    out['vol_mean50'] = out['volume'].rolling(ETH_SHORT_VOL_LOOKBACK, min_periods=ETH_SHORT_VOL_LOOKBACK).mean()
    return out


def get_scale(atr_ratio):
    if pd.isna(atr_ratio) or atr_ratio <= 0:
        return 1.0
    return max(SCALE_MIN, min(SCALE_MAX, 1.0 / atr_ratio))


def calculate_sl_tp(entry, direction, low, high, rr=2.0):
    if direction == 'long':
        sl = low; risk = entry - sl
        if risk <= 0: return None, None
        return sl, entry + rr * risk
    else:
        sl = high; risk = sl - entry
        if risk <= 0: return None, None
        return sl, entry - rr * risk


def run(df, longs_only, min_sl_pct, asset_name, vcfg, start=None, end=None):
    if start and end:
        df = df[(df['open_time'] >= start) & (df['open_time'] < end)].reset_index(drop=True)

    slope_cap = vcfg['slope_cap']
    equity    = INITIAL_CAPITAL
    position  = None
    trades    = []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty     = position['qty']
                gross   = (exit_price - position['entry']) * qty if position['direction'] == 'long' \
                          else (position['entry'] - exit_price) * qty
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'open_time':  str(position['open_time']),
                    'close_time': str(row['open_time']),
                    'direction':  position['direction'],
                    'entry':      position['entry'],
                    'exit':       exit_price,
                    'reason':     reason,
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

        # SLOPE_CAP (variable bajo prueba)
        if slope_cap is not None:
            slope_pct = row.get('ema50_slope_pct')
            if not pd.isna(slope_pct) and abs(slope_pct) > slope_cap:
                continue

        # TIME-B
        ts   = pd.Timestamp(row['open_time'])
        hour = ts.hour if ts.tzinfo is None else ts.tz_convert('UTC').hour
        if not (TIME_B_START <= hour < TIME_B_END):
            continue

        direction = 'long' if trend == 'up' else 'short'

        # ETH-SHORT-C
        if asset_name == 'ETH' and direction == 'short':
            vol     = row.get('volume')
            vol_m50 = row.get('vol_mean50')
            if vol is not None and vol_m50 is not None and not pd.isna(vol_m50) and vol_m50 > 0:
                if vol / vol_m50 < ETH_SHORT_VOL_MIN_RATIO:
                    continue

        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None: continue

        risk_price = abs(entry - sl)
        if risk_price / entry < min_sl_pct: continue

        # DYN-B
        atr_ratio = row.get('atr_ratio', float('nan'))
        scale     = get_scale(atr_ratio)
        risk_usd  = equity * RISK_PCT * scale

        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry': entry, 'sl': sl, 'tp': tp,
            'qty':   risk_usd / risk_price,
        }
    return trades


def metrics(trades):
    if not trades:
        return {'total_trades': 0, 'profit_factor': 0.0, 'win_rate_pct': 0.0,
                'return_pct': 0.0, 'max_dd_pct': 0.0, 'expectancy_usd': 0.0,
                'total_fees_usd': 0.0}
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
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
    }


def wf_combined_pf(btc_trades, eth_trades, start, end):
    all_t = [t for t in btc_trades + eth_trades if start <= t['close_time'] < end]
    if not all_t: return 0.0
    gp = sum(t['pnl'] for t in all_t if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in all_t if t['pnl'] <= 0))
    return round(gp / gl, 3) if gl > 0 else float('inf')


ASSET_CONFIGS = {
    'BTC': {'path_1h': 'data/BTCUSDT_1h_last_740d.csv', 'path_15m': 'data/BTCUSDT_15m_last_730d.csv',
            'longs_only': True,  'min_sl_pct': 0.0030},
    'ETH': {'path_1h': 'data/ETHUSDT_1h_last_740d.csv', 'path_15m': 'data/ETHUSDT_15m_last_730d.csv',
            'longs_only': False, 'min_sl_pct': 0.0050},
}


if __name__ == '__main__':
    print(f"\nTASK008 — Diagnóstico SLOPE_CAP  |  Base: TIME-B + DYN-B + ETH-SHORT-C  |  730d con fees\n")
    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        print(f"[{asset_name}] Preparando datos...", flush=True)
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = prepare_1h_with_atr(df_1h_raw)
        df_15m = prepare_15m_with_vol(df_15m_raw)
        df     = align_1h_to_15m(df_15m, df_1h)

        asset_results = {}
        for vname, vcfg in VARIANTS.items():
            trades = run(df, cfg['longs_only'], cfg['min_sl_pct'], asset_name, vcfg)
            m      = metrics(trades)
            asset_results[vname] = {'metrics': m, 'trades': trades}
            cap_label = f"cap={vcfg['slope_cap']}" if vcfg['slope_cap'] else 'sin_cap'
            print(f"  [{vname:8} {cap_label:10}] trades={m['total_trades']:>3}  PF={m['profit_factor']:.3f}  "
                  f"WR={m['win_rate_pct']:.1f}%  Return={m['return_pct']:+.1f}%  "
                  f"MaxDD={m['max_dd_pct']:.2f}%  E={m['expectancy_usd']:+.2f}")
        all_results[asset_name] = asset_results

        print(f"\n  {'Métrica':<20}" + ''.join(f"  {v:>10}" for v in VARIANTS))
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
                row_str += f"  {fmt.format(val):>10}"
            print(row_str)
        print()

    print(f"\n{'='*80}")
    print(f"  TASK008  |  Walk-forward combinado BTC+ETH (4×182d)")
    print(f"{'='*80}")
    print(f"  {'Win':<4}  {'Período':<22}" + ''.join(f"  {v:>14}" for v in VARIANTS))
    print(f"  {'-'*80}")
    pass_all = {v: True for v in VARIANTS}
    for wid, start, end, label in WINDOWS:
        row_str = f"  {wid:<4}  {label:<22}"
        for vname in VARIANTS:
            btc_t = all_results.get('BTC', {}).get(vname, {}).get('trades', [])
            eth_t = all_results.get('ETH', {}).get(vname, {}).get('trades', [])
            cpf   = wf_combined_pf(btc_t, eth_t, start, end)
            flag  = '✅' if cpf >= 1.0 else '❌'
            if cpf < 1.0: pass_all[vname] = False
            row_str += f"  {cpf:>10.3f} {flag}"
        print(row_str)

    print(f"\n  {'Variante':<10}  {'730d PF BTC':>12}  {'730d PF ETH':>12}  {'4 ventanas':>12}")
    print(f"  {'-'*55}")
    for v in VARIANTS:
        btc_pf = all_results['BTC'][v]['metrics']['profit_factor']
        eth_pf = all_results['ETH'][v]['metrics']['profit_factor']
        ok     = '✅ PASS' if (btc_pf >= 1.2 and eth_pf >= 1.2 and pass_all[v]) else '❌ FAIL'
        print(f"  {v:<10}  {btc_pf:>12.3f}  {eth_pf:>12.3f}  {ok:>12}")

    out_path = 'data/backtest_task008.json'
    with open(out_path, 'w') as f:
        json.dump({a: {v: r['metrics'] for v, r in vr.items()}
                   for a, vr in all_results.items()}, f, indent=2, default=str)
    print(f"\nResultados guardados en {out_path}")
