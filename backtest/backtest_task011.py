"""
TASK011 — Refinar filtro is_trend_strong: slope mínimo + alineación estructural

Base: COMBINED (Task007 ETH-SHORT-C) — 730d con fees.

Hipótesis:
    El filtro actual rechaza trades donde el EMA50 slope en 1h es bajo (<0.05%)
    pero la estructura de precios es claramente bajista/alcista (precio del lado
    correcto de EMA20 Y EMA50). Esos trades pueden tener edge real.

Variantes:
    BASE         : Filtro actual — slope abs >= 0.05% (EMA50_SLOPE_MIN_PCT)
    SLOPE_LOW_A  : Bajar umbral a 0.02% (acepta más trades con tendencia débil)
    SLOPE_LOW_B  : Bajar umbral a 0.00% (solo requiere dirección, no magnitud)
    ALIGN_OR     : slope >= 0.05% OR (alineación estructural AND slope >= 0.01%)
                   Alineación: long → close > ema20 > ema50_at_close? No…
                   Para el pullback: long → ema50 < ema20 (EMAs apuntan up)
                                     short → ema50 > ema20 (EMAs apuntan down)
    ALIGN_STRICT : slope >= 0.02% AND alineación estructural (EMA20 del lado correcto de EMA50)

El test responde: ¿los trades con slope bajo pero estructura alineada son rentables?
"""

import json, os, sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend, is_pullback_quality,
    is_entry_trigger, is_candle_quality,
    is_range_sufficient, is_market_efficient,
    EMA50_SLOPE_MIN_PCT,
)
from core.trade_logic import check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005
MAX_SLOPE_PCT    = 0.20   # EXP019 SLOPE_CAP (unchanged)

ATR_PERIOD      = 14
ATR_MEAN_WINDOW = 50
SCALE_MIN    = 0.6
SCALE_MAX    = 1.2
TIME_B_START = 7
TIME_B_END   = 21
ETH_VOL_MIN  = 1.0   # ETH-SHORT-C

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]

# Variants: (min_slope_abs, use_structural_fallback, structural_min_slope)
VARIANTS = {
    'BASE':         (0.05,  False, None),   # current filter
    'SLOPE_LOW_A':  (0.02,  False, None),   # lower threshold only
    'SLOPE_LOW_B':  (0.00,  False, None),   # direction only, no magnitude
    'ALIGN_OR':     (0.05,  True,  0.01),   # slope>=0.05 OR (structural + slope>=0.01)
    'ALIGN_STRICT': (0.02,  True,  0.02),   # slope>=0.02 AND structural alignment
}


def add_atr_ratio(df_1h: pd.DataFrame) -> pd.DataFrame:
    out = df_1h.copy()
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low']  - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr14']      = tr.ewm(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False).mean()
    out['atr50_mean'] = out['atr14'].rolling(ATR_MEAN_WINDOW, min_periods=ATR_MEAN_WINDOW).mean()
    out['atr_ratio']  = out['atr14'] / out['atr50_mean'].replace(0, float('nan'))
    return out


def is_trend_strong_variant(row, min_slope: float, use_structural: bool, struct_min: float) -> bool:
    """
    Variante parametrizable de is_trend_strong.

    min_slope: umbral mínimo de abs(ema50_slope_pct) para pasar directamente.
    use_structural: si True, permite pasar también cuando hay alineación estructural
                    (EMA20 está del lado correcto de EMA50) y slope >= struct_min.
    """
    ema50     = row.get('ema50')
    ema20     = row.get('ema20')
    slope_pct = row.get('ema50_slope_pct')
    close     = row.get('close')

    if pd.isna(ema50) or pd.isna(slope_pct) or ema50 == 0:
        return False

    abs_slope = abs(slope_pct)
    dist_from_ema50 = abs(close - ema50) / ema50

    # Condición de slope directo
    slope_ok = (abs_slope >= min_slope) and (dist_from_ema50 >= 0.005)

    if slope_ok:
        return True

    if not use_structural:
        return False

    # Alineación estructural: EMA20 del lado correcto de EMA50
    # long (slope > 0): EMA20 > EMA50 (mercado ha subido, EMA corta > EMA larga)
    # short (slope < 0): EMA20 < EMA50
    if pd.isna(ema20):
        return False

    if slope_pct > 0:
        structural_ok = ema20 > ema50
    else:
        structural_ok = ema20 < ema50

    return structural_ok and (abs_slope >= struct_min) and (dist_from_ema50 >= 0.005)


def run_backtest(df_15m_raw, df_1h_raw, longs_only, min_sl_dist_pct,
                 variant_name, min_slope, use_structural, struct_min,
                 start_date=None, end_date=None):

    df_1h_aug  = add_atr_ratio(prepare_1h(df_1h_raw))
    df_15m_aug = prepare_15m(df_15m_raw)
    df         = align_1h_to_15m(df_15m_aug, df_1h_aug)

    if start_date:
        df = df[df['open_time'] >= pd.Timestamp(start_date, tz='UTC')]
    if end_date:
        df = df[df['open_time'] < pd.Timestamp(end_date, tz='UTC')]
    if df.empty:
        return None

    capital   = INITIAL_CAPITAL
    trades    = []
    position  = None
    MIN_RISK  = 1.0

    for _, row in df.iterrows():
        if position:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result:
                reason, exit_price = result
                if position['direction'] == 'long':
                    gross = (exit_price - position['entry']) * position['qty']
                else:
                    gross = (position['entry'] - exit_price) * position['qty']
                fee    = (position['entry'] + exit_price) * position['qty'] * FEE_PER_SIDE_PCT
                pnl    = gross - fee
                capital += pnl
                trades.append({'pnl': pnl, 'direction': position['direction']})
                position = None
            continue

        trend = get_trend(row)
        if trend is None:
            continue
        if longs_only and trend != 'up':
            continue

        # TASK011: variante de is_trend_strong
        if not is_trend_strong_variant(row, min_slope, use_structural, struct_min):
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

        # EXP019 SLOPE_CAP
        s = row.get('ema50_slope_pct')
        if s is not None and not pd.isna(s) and abs(s) > MAX_SLOPE_PCT:
            continue

        # TIME-B
        ts = pd.Timestamp(row['open_time'])
        h  = ts.hour if ts.tzinfo is None else ts.tz_convert('UTC').hour
        if not (TIME_B_START <= h < TIME_B_END):
            continue

        entry     = row['close']
        direction = 'long' if trend == 'up' else 'short'

        # ETH-SHORT-C volume filter
        if not longs_only and direction == 'short':
            vol    = row.get('volume')
            vm50   = row.get('vol_mean50')
            if vol is not None and vm50 is not None and not pd.isna(vm50) and vm50 > 0:
                if vol / vm50 < ETH_VOL_MIN:
                    continue

        from core.trade_logic import calculate_sl_tp
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None:
            continue

        risk_price = abs(entry - sl)
        if risk_price < MIN_RISK:
            continue
        if risk_price / entry < min_sl_dist_pct:
            continue

        # DYN-B sizing
        atr_ratio = row.get('atr_ratio')
        if atr_ratio is not None and not pd.isna(atr_ratio) and atr_ratio > 0:
            dyn = max(SCALE_MIN, min(SCALE_MAX, 1.0 / atr_ratio))
        else:
            dyn = 1.0

        risk_usd = capital * RISK_PCT * dyn
        qty      = risk_usd / risk_price

        position = {
            'direction': direction, 'entry': entry,
            'sl': sl, 'tp': tp, 'qty': qty,
            'open_time': str(row['open_time']),
        }

    if not trades:
        return None

    wins = [t for t in trades if t['pnl'] > 0]
    loss = [t for t in trades if t['pnl'] <= 0]
    gp   = sum(t['pnl'] for t in wins)
    gl   = abs(sum(t['pnl'] for t in loss))
    pf   = gp / gl if gl > 0 else float('inf')
    ret  = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # Max drawdown
    eq, peak, dd = INITIAL_CAPITAL, INITIAL_CAPITAL, 0.0
    for t in trades:
        eq   += t['pnl']
        peak  = max(peak, eq)
        dd    = max(dd, (peak - eq) / peak * 100)

    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(loss),
        'pf': pf, 'wr': len(wins) / len(trades) * 100,
        'ret': ret, 'maxdd': dd,
    }


def print_results(label, btc_r, eth_r):
    t  = (btc_r['trades'] if btc_r else 0) + (eth_r['trades'] if eth_r else 0)
    pf_b = f"{btc_r['pf']:.3f}" if btc_r else 'N/A'
    pf_e = f"{eth_r['pf']:.3f}" if eth_r else 'N/A'
    ret  = (btc_r['ret'] if btc_r else 0) + (eth_r['ret'] if eth_r else 0)
    dd_b = f"{btc_r['maxdd']:.2f}%" if btc_r else 'N/A'
    dd_e = f"{eth_r['maxdd']:.2f}%" if eth_r else 'N/A'
    wr_b = f"{btc_r['wr']:.1f}%" if btc_r else 'N/A'
    wr_e = f"{eth_r['wr']:.1f}%" if eth_r else 'N/A'
    t_b  = btc_r['trades'] if btc_r else 0
    t_e  = eth_r['trades'] if eth_r else 0
    print(f"  [{label:<14}] T={t:3d} (BTC={t_b} ETH={t_e})  "
          f"PF_BTC={pf_b}  PF_ETH={pf_e}  "
          f"WR_BTC={wr_b}  WR_ETH={wr_e}  "
          f"Ret={ret:+.1f}%  DD_BTC={dd_b}  DD_ETH={dd_e}")


if __name__ == '__main__':
    print('\nTASK011 — Refinamiento filtro is_trend_strong  |  730d con fees\n')

    btc_1h, btc_15m = load_data('data/BTCUSDT_1h_last_740d.csv', 'data/BTCUSDT_15m_last_730d.csv')
    eth_1h, eth_15m = load_data('data/ETHUSDT_1h_last_740d.csv', 'data/ETHUSDT_15m_last_730d.csv')

    results = {}

    for vname, (min_slope, use_struct, struct_min) in VARIANTS.items():
        btc_r = run_backtest(btc_15m, btc_1h, longs_only=True,  min_sl_dist_pct=0.003,
                             variant_name=vname, min_slope=min_slope,
                             use_structural=use_struct, struct_min=struct_min)
        eth_r = run_backtest(eth_15m, eth_1h, longs_only=False, min_sl_dist_pct=0.005,
                             variant_name=vname, min_slope=min_slope,
                             use_structural=use_struct, struct_min=struct_min)
        print_results(vname, btc_r, eth_r)
        results[vname] = {'btc': btc_r, 'eth': eth_r}

    # Walk-forward por ventanas (combinado BTC+ETH)
    print(f'\n{"="*90}')
    print(f'  TASK011  |  Walk-forward combinado BTC+ETH (4×182d)')
    print(f'{"="*90}')
    header = f"  {'Ventana':<8} {'Período':<22}" + ''.join(f"  {v:<14}" for v in VARIANTS)
    print(header)
    print(f"  {'-'*88}")

    for wid, wstart, wend, wlabel in WINDOWS:
        row_parts = [f"  {wid:<8} {wlabel:<22}"]
        for vname, (min_slope, use_struct, struct_min) in VARIANTS.items():
            btc_w = run_backtest(btc_15m, btc_1h, longs_only=True,  min_sl_dist_pct=0.003,
                                 variant_name=vname, min_slope=min_slope,
                                 use_structural=use_struct, struct_min=struct_min,
                                 start_date=wstart, end_date=wend)
            eth_w = run_backtest(eth_15m, eth_1h, longs_only=False, min_sl_dist_pct=0.005,
                                 variant_name=vname, min_slope=min_slope,
                                 use_structural=use_struct, struct_min=struct_min,
                                 start_date=wstart, end_date=wend)
            pfs = []
            if btc_w: pfs.append(btc_w['pf'])
            if eth_w: pfs.append(eth_w['pf'])
            if pfs:
                combined_pf = sum(pfs) / len(pfs)
                ok = '✅' if combined_pf > 1.0 else '❌'
                row_parts.append(f"  {combined_pf:.3f} {ok:<12}")
            else:
                row_parts.append(f"  {'N/A':<15}")
        print(''.join(row_parts))

    # Diagnóstico extra: ¿qué trades nuevos agrega ALIGN_OR vs BASE?
    print(f'\n{"─"*60}')
    print('  Diagnóstico: trades NUEVOS que agrega ALIGN_OR vs BASE')
    print(f'{"─"*60}')
    for asset_name, df_15m_raw, df_1h_raw, longs_only, sl_pct in [
        ('BTC', btc_15m, btc_1h, True,  0.003),
        ('ETH', eth_15m, eth_1h, False, 0.005),
    ]:
        base = results['BASE'][asset_name.lower()]
        new  = results['ALIGN_OR'][asset_name.lower()]
        extra = (new['trades'] - base['trades']) if (base and new) else 0
        print(f"  {asset_name}: BASE={base['trades'] if base else 0} trades  "
              f"ALIGN_OR={new['trades'] if new else 0} trades  "
              f"extra={extra:+d}")

    # Guardar
    with open('data/backtest_task011.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print('\nResultados guardados en data/backtest_task011.json')
