"""
EXP019  —  Volatility/momentum extreme filter

Context from EXP018:
    ADX failed as a regime classifier — it selected the WORST trades.
    The root cause is not "trending vs choppy" but "normal trend vs parabolic/extreme move".

    The bad regime (ATH Oct24–Mar25 for BTC, Recovery 2025 for ETH) is characterized by:
    - Price moving parabolically (EMA50 slope extremely steep)
    - Current ATR 2-3x above historical average (extreme intraday volatility)
    - SLs placed below candle low get hit by noise before the trade can mature

New hypothesis:
    Filter out entries when the market is in extreme momentum mode.
    Detectors:
      A) EMA50 slope cap: skip entry if EMA50_slope_pct > MAX_SLOPE_PCT
         (avoids parabolic up-trends where pullbacks are traps)
      B) ATR ratio:        skip entry if ATR(14) / ATR_mean(50) > MAX_ATR_RATIO
         (avoids high-volatility explosions where SLs get blown out by noise)
      C) Combined A+B:     both conditions must hold (AND)
      D) Either A or B:    at least one must hold (OR)

Variants (all with fees 0.05%/side):
    BASE         : no new filter  (= EXP017-B BTC / EXP016A ETH)
    SLOPE_CAP    : skip if ema50_slope_pct > 0.20% per 5 bars on 1h
    ATR_RATIO    : skip if ATR14 / ATR50_mean > 1.8
    COMBINED     : skip if EITHER slope_cap OR atr_ratio triggers

Assets:
    BTC/USDT — longs only,   SL≥0.30%,  RR=2:1
    ETH/USDT — longs+shorts, SL≥0.50%,  RR=2:1

Data: data/*_730d.csv + data/*_740d.csv (already downloaded)

Success criteria:
    Filtered PF > BASE PF  (at least one variant improves on base)
    Discarded trades have PF < BASE PF  (confirms filter removes bad trades)
    Trade count kept >= 80
    PF > 1.0 for both assets with fees
"""

import json
import os
import sys
import pandas as pd
import numpy as np

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

# ── Filter thresholds ─────────────────────────────────────────────────────────
MAX_SLOPE_PCT  = 0.20   # EMA50 slope > 0.20%/5bars → parabolic (skip)
MAX_ATR_RATIO  = 1.8    # ATR14 / ATR50_mean > 1.8 → extreme volatility (skip)
ATR_PERIOD     = 14
ATR_MEAN_WINDOW = 50


def add_volatility_filters(df_1h: pd.DataFrame) -> pd.DataFrame:
    """
    Add ATR(14) and ATR_ratio = ATR14 / rolling_mean(ATR14, 50) to the 1h dataframe.
    EMA50_slope_pct is already in the df from prepare_1h().
    """
    out = df_1h.copy()
    high  = out['high']
    low   = out['low']
    close = out['close']

    # True Range
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    out['atr14']     = tr.ewm(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False).mean()
    out['atr50_mean'] = out['atr14'].rolling(ATR_MEAN_WINDOW, min_periods=ATR_MEAN_WINDOW).mean()
    out['atr_ratio']  = out['atr14'] / out['atr50_mean'].replace(0, float('nan'))
    return out


def align_with_volatility(df_15m: pd.DataFrame, df_1h_prep: pd.DataFrame) -> pd.DataFrame:
    """Extend align_1h_to_15m to also carry atr_ratio through to the 15m frame."""
    from core.strategy_pullback import align_1h_to_15m
    # First do the standard alignment
    df = align_1h_to_15m(df_15m, df_1h_prep)

    # Merge atr_ratio separately (same merge_asof logic)
    right_atr = (
        df_1h_prep[['available_at', 'atr_ratio', 'ema50_slope_pct']]
        .dropna(subset=['atr_ratio'])
        .sort_values('available_at')
        .reset_index(drop=True)
    )
    df = df.sort_values('open_time').reset_index(drop=True)
    df = pd.merge_asof(
        df,
        right_atr.rename(columns={
            'atr_ratio':       'atr_ratio_1h',
            'ema50_slope_pct': 'ema50_slope_pct_1h',
        }),
        left_on='open_time',
        right_on='available_at',
        direction='backward',
        suffixes=('', '_dup'),
    )
    return df


def calculate_sl_tp(entry, direction, candle_low, candle_high, rr: float):
    if direction == 'long':
        sl   = candle_low
        risk = entry - sl
        if risk <= 0:
            return None, None
        tp = entry + rr * risk
    else:
        sl   = candle_high
        risk = sl - entry
        if risk <= 0:
            return None, None
        tp = entry - rr * risk
    return sl, tp


def is_extreme(row, variant: str) -> bool:
    """Return True if the filter triggers (entry should be SKIPPED)."""
    slope_pct = row.get('ema50_slope_pct_1h')
    atr_ratio = row.get('atr_ratio_1h')

    slope_extreme = (not pd.isna(slope_pct)) and (abs(slope_pct) > MAX_SLOPE_PCT)
    atr_extreme   = (not pd.isna(atr_ratio)) and (atr_ratio > MAX_ATR_RATIO)

    if variant == 'SLOPE_CAP':
        return slope_extreme
    if variant == 'ATR_RATIO':
        return atr_extreme
    if variant == 'COMBINED':   # skip if EITHER extreme
        return slope_extreme or atr_extreme
    if variant == 'STRICT':     # skip if BOTH extreme (more permissive)
        return slope_extreme and atr_extreme
    return False  # BASE


def run(path_1h: str, path_15m: str, longs_only: bool,
        min_sl_pct: float, rr: float, variant: str) -> dict:
    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h  = prepare_1h(df_1h_raw)
    df_1h  = add_volatility_filters(df_1h)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_with_volatility(df_15m, df_1h)

    equity_kept      = INITIAL_CAPITAL
    equity_discarded = INITIAL_CAPITAL
    position_kept    = None
    position_disc    = None
    trades_kept      = []
    trades_discarded = []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        extreme = is_extreme(row, variant)

        # ── Check exits ───────────────────────────────────────────────────────
        if position_kept is not None:
            result = check_exit(position_kept['direction'], position_kept['sl'], position_kept['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty = position_kept['qty']
                gross = (exit_price - position_kept['entry']) * qty if position_kept['direction'] == 'long' \
                        else (position_kept['entry'] - exit_price) * qty
                fee     = (position_kept['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity_kept += net_pnl
                trades_kept.append({
                    'open_time':    str(position_kept['open_time']),
                    'close_time':   str(row['open_time']),
                    'direction':    position_kept['direction'],
                    'entry':        position_kept['entry'],
                    'exit':         exit_price,
                    'sl':           position_kept['sl'],
                    'tp':           position_kept['tp'],
                    'sl_dist_pct':  position_kept['sl_dist_pct'],
                    'slope_at_entry': position_kept['slope'],
                    'atr_ratio_at_entry': position_kept['atr_ratio'],
                    'reason':       reason,
                    'gross_pnl':    round(gross, 4),
                    'fee_usd':      round(fee, 4),
                    'pnl':          round(net_pnl, 4),
                    'equity':       round(equity_kept, 4),
                })
                position_kept = None
            continue

        if position_disc is not None:
            result = check_exit(position_disc['direction'], position_disc['sl'], position_disc['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty = position_disc['qty']
                gross = (exit_price - position_disc['entry']) * qty if position_disc['direction'] == 'long' \
                        else (position_disc['entry'] - exit_price) * qty
                fee     = (position_disc['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity_discarded += net_pnl
                trades_discarded.append({
                    'open_time':    str(position_disc['open_time']),
                    'close_time':   str(row['open_time']),
                    'direction':    position_disc['direction'],
                    'entry':        position_disc['entry'],
                    'exit':         exit_price,
                    'sl_dist_pct':  position_disc['sl_dist_pct'],
                    'slope_at_entry': position_disc['slope'],
                    'atr_ratio_at_entry': position_disc['atr_ratio'],
                    'reason':       reason,
                    'gross_pnl':    round(gross, 4),
                    'fee_usd':      round(fee, 4),
                    'pnl':          round(net_pnl, 4),
                    'equity':       round(equity_discarded, 4),
                })
                position_disc = None
            continue

        # ── Entry signal check ────────────────────────────────────────────────
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

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'], rr)
        if sl is None:
            continue
        risk_price  = abs(entry - sl)
        sl_dist_pct = risk_price / entry
        if sl_dist_pct < min_sl_pct:
            continue

        slope_now     = row.get('ema50_slope_pct_1h')
        atr_ratio_now = row.get('atr_ratio_1h')

        pos_data = {
            'open_time':   row['open_time'],
            'direction':   direction,
            'entry':       entry,
            'sl':          sl,
            'tp':          tp,
            'sl_dist_pct': round(sl_dist_pct * 100, 4),
            'slope':       round(float(slope_now), 4) if not pd.isna(slope_now) else None,
            'atr_ratio':   round(float(atr_ratio_now), 3) if not pd.isna(atr_ratio_now) else None,
        }

        if not extreme:
            risk_usd       = equity_kept * RISK_PCT
            pos_data['qty'] = risk_usd / risk_price
            position_kept  = pos_data
        else:
            risk_usd       = equity_discarded * RISK_PCT
            pos_data['qty'] = risk_usd / risk_price
            position_disc  = pos_data

    return {'kept': trades_kept, 'discarded': trades_discarded}


def metrics(trades: list, initial: float = INITIAL_CAPITAL) -> dict:
    if not trades:
        return {}
    df        = pd.DataFrame(trades)
    wins      = df[df['pnl'] > 0]
    losses    = df[df['pnl'] <= 0]
    gp        = wins['pnl'].sum()
    gl        = abs(losses['pnl'].sum())
    pf        = gp / gl if gl > 0 else float('inf')
    total_ret = (df['equity'].iloc[-1] - initial) / initial * 100
    peak, max_dd = initial, 0.0
    eq = initial
    for p in df['pnl']:
        eq += p
        peak   = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    avg_slope = df['slope_at_entry'].dropna().mean() if 'slope_at_entry' in df else None
    avg_atr   = df['atr_ratio_at_entry'].dropna().mean() if 'atr_ratio_at_entry' in df else None
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(total_ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'avg_slope':      round(avg_slope, 4) if avg_slope else None,
        'avg_atr_ratio':  round(avg_atr, 3) if avg_atr else None,
    }


def regime_split(trades: list) -> dict:
    if not trades:
        return {}
    def _m(subset): return metrics(subset) if subset else {}
    return {
        'bull_2024':     _m([t for t in trades if t['close_time'] < '2024-10-01']),
        'ath_2024_25':   _m([t for t in trades if '2024-10-01' <= t['close_time'] < '2025-04-01']),
        'recovery_2025': _m([t for t in trades if '2025-04-01' <= t['close_time'] < '2025-10-01']),
        'bear_2025_26':  _m([t for t in trades if t['close_time'] >= '2025-10-01']),
    }


ASSET_CONFIGS = {
    'BTC': {
        'path_1h':    'data/BTCUSDT_1h_last_740d.csv',
        'path_15m':   'data/BTCUSDT_15m_last_730d.csv',
        'longs_only': True,
        'min_sl_pct': 0.0030,
        'rr':         2.0,
        'label':      'BTC/USDT — longs only  SL≥0.30%  RR=2:1',
        'base_pf':    1.126,
    },
    'ETH': {
        'path_1h':    'data/ETHUSDT_1h_last_740d.csv',
        'path_15m':   'data/ETHUSDT_15m_last_730d.csv',
        'longs_only': False,
        'min_sl_pct': 0.0050,
        'rr':         2.0,
        'label':      'ETH/USDT — longs+shorts  SL≥0.50%  RR=2:1',
        'base_pf':    0.939,
    },
}

VARIANTS = ['BASE', 'SLOPE_CAP', 'ATR_RATIO', 'COMBINED', 'STRICT']


def print_asset_report(asset: str, cfg: dict, results: dict) -> None:
    w = 13
    print(f"\n{'='*90}")
    print(f"  EXP019  |  {cfg['label']}")
    print(f"  Filtros: SLOPE_CAP (ema50_slope>{MAX_SLOPE_PCT}%), ATR_RATIO (atr14/atr50mean>{MAX_ATR_RATIO})")
    print(f"{'='*90}")

    header = f"  {'Métrica':<22}" + ''.join(f"  {v:>{w}}" for v in VARIANTS)
    print(header)
    print(f"  {'-'*88}")

    fields = [
        ('Trades (kept)',  'total_trades',   '{:d}'),
        ('Win rate %',     'win_rate_pct',    '{:.1f}'),
        ('Return %',       'return_pct',      '{:+.2f}'),
        ('Max DD %',       'max_dd_pct',      '{:.2f}'),
        ('Profit factor',  'profit_factor',   '{:.3f}'),
        ('Expectancy $',   'expectancy_usd',  '{:+.2f}'),
        ('Avg EMA50 slope','avg_slope',        '{:.4f}'),
        ('Avg ATR ratio',  'avg_atr_ratio',    '{:.3f}'),
        ('Total fees $',   'total_fees_usd',  '{:.0f}'),
    ]

    for label, key, fmt in fields:
        row = f"  {label:<22}"
        for v in VARIANTS:
            m = results[v]['kept_metrics']
            val = m.get(key) if m else None
            if val is None:
                row += f"  {'—':>{w}}"
            else:
                row += f"  {fmt.format(val):>{w}}"
        print(row)

    # Discarded
    print(f"\n  ── TRADES DESCARTADOS (extreme filter triggered) ────────────────────────────────")
    dheader = f"  {'Métrica':<22}" + ''.join(f"  {v:>{w}}" for v in VARIANTS)
    print(dheader)
    print(f"  {'-'*88}")
    for label, key, fmt in [
        ('Trades (disc.)', 'total_trades',  '{:d}'),
        ('Profit factor',  'profit_factor', '{:.3f}'),
        ('Avg EMA50 slope','avg_slope',      '{:.4f}'),
        ('Avg ATR ratio',  'avg_atr_ratio',  '{:.3f}'),
    ]:
        row = f"  {label:<22}"
        for v in VARIANTS:
            if v == 'BASE':
                row += f"  {'—':>{w}}"
            else:
                m = results[v]['disc_metrics']
                val = m.get(key) if m else None
                if val is None:
                    row += f"  {'—':>{w}}"
                else:
                    row += f"  {fmt.format(val):>{w}}"
        print(row)

    # Regime breakdown for BASE and best variant
    best_v    = max(
        [v for v in VARIANTS if results[v]['kept_metrics']],
        key=lambda v: results[v]['kept_metrics'].get('profit_factor', 0)
    )
    best_pf   = results[best_v]['kept_metrics'].get('profit_factor', 0)
    base_pf   = cfg['base_pf']

    print(f"\n  ── DESGLOSE POR RÉGIMEN (BASE vs {best_v}) ─────────────────────────────────────")
    regimes = [
        ('bull_2024',     'Bull 2024 (Apr-Sep 24)'),
        ('ath_2024_25',   'ATH 2024-25 (Oct24-Mar25)'),
        ('recovery_2025', 'Recovery 2025 (Apr-Sep 25)'),
        ('bear_2025_26',  'Bear 2025-26 (Oct25-Apr26)'),
    ]
    print(f"  {'Variante':<12}  {'Régimen':<28}  {'T':>4}  {'WR%':>5}  {'PF':>6}  {'Ret%':>7}")
    print(f"  {'-'*72}")
    for v in ['BASE', best_v]:
        rg = results[v]['regime']
        for rkey, rlabel in regimes:
            rm = rg.get(rkey, {})
            if rm and rm.get('total_trades', 0) > 0:
                flag = ' ✓' if rm['profit_factor'] >= 1.0 else ' ✗'
                print(f"  [{v}]{'':6}  {rlabel:<28}  "
                      f"{rm['total_trades']:>4}  "
                      f"{rm['win_rate_pct']:>4.0f}%  "
                      f"{rm['profit_factor']:>6.3f}  "
                      f"{rm['return_pct']:>+6.1f}%{flag}")
            else:
                print(f"  [{v}]{'':6}  {rlabel:<28}  {'—':>4}")

    # Verdict
    print(f"\n  ── VEREDICTO ────────────────────────────────────────────────────────────────────")
    print(f"  BASE PF:          {base_pf:.3f}")
    print(f"  Mejor variante:   [{best_v}]  PF={best_pf:.3f}  "
          f"({'↑' if best_pf > base_pf else '↓'} vs BASE)")
    kept_t = results[best_v]['kept_metrics'].get('total_trades', 0)
    print(f"  Trades kept:      {kept_t}  "
          f"({'✓ suficiente' if kept_t >= 80 else '✗ insuficiente'})")
    disc_pf = results[best_v]['disc_metrics'].get('profit_factor', 0)
    print(f"  Discarded PF:     {disc_pf:.3f}  "
          f"({'✓ peor que BASE' if disc_pf < base_pf else '✗ mejor que BASE — filtro no discrimina'})")

    if best_pf > base_pf and kept_t >= 80 and disc_pf < base_pf:
        print(f"\n  ✅  FILTRO FUNCIONA — variante [{best_v}] mejora sobre BASE")
    elif best_pf > base_pf and kept_t >= 80:
        print(f"\n  ⚠️  MEJORA PARCIAL — variante [{best_v}] mejora PF pero los descartados no son claramente peores")
    elif best_pf > 1.0:
        print(f"\n  ⚠️  PF>1 PERO NO SUPERA BASE — posible solapamiento con filtros existentes (EMA, ER)")
    else:
        print(f"\n  ❌  NINGÚN FILTRO FUNCIONA")
        print(f"      → El problema del ATH no es capturable con slope ni ATR ratio")
        print(f"      → Considerar: ancho de SL adaptativo (SL basado en ATR, no en low de vela)")

    print(f"{'='*90}\n")


if __name__ == '__main__':
    print(f"\nEXP019 — Momentum extreme filter  |  730d con fees\n")
    print(f"Thresholds: SLOPE_CAP={MAX_SLOPE_PCT}%  ATR_RATIO={MAX_ATR_RATIO}\n")

    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        if not os.path.exists(cfg['path_15m']):
            print(f"[{asset_name}] ERROR: datos no encontrados.")
            print("  Ejecutar: python fetch_all.py --2y")
            continue

        print(f"[{asset_name}] Corriendo variantes...", flush=True)
        asset_results = {}

        for vname in VARIANTS:
            result = run(
                path_1h    = cfg['path_1h'],
                path_15m   = cfg['path_15m'],
                longs_only = cfg['longs_only'],
                min_sl_pct = cfg['min_sl_pct'],
                rr         = cfg['rr'],
                variant    = vname,
            )
            km = metrics(result['kept'])
            dm = metrics(result['discarded'])
            rg = regime_split(result['kept'])
            asset_results[vname] = {
                'kept_metrics': km,
                'disc_metrics': dm,
                'regime':       rg,
            }
            kept_pf = km.get('profit_factor', 0) if km else 0
            disc_pf = dm.get('profit_factor', 0) if dm else 0
            kept_t  = km.get('total_trades', 0) if km else 0
            disc_t  = dm.get('total_trades', 0) if dm else 0
            print(f"  [{vname:12}] kept={kept_t:>3} PF={kept_pf:.3f}  |  disc={disc_t:>3} PF={disc_pf:.3f}")

        all_results[asset_name] = asset_results
        print_asset_report(asset_name, cfg, asset_results)

    out_path = 'data/backtest_exp019.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Resultados guardados en {out_path}")
