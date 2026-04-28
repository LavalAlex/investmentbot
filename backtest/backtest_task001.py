"""
TASK 001 — Trailing Stop vs TP fijo 2:1

Hypothesis:
    Replacing the fixed 2:1 TP with a trailing stop increases PF and total return
    by letting winning trades run in strong trending moves, at the cost of a slightly
    lower win rate.

Base system: EXP019 SLOPE_CAP (skip when EMA50 slope > 0.20%/5bars on 1h).

Variants (all with fees 0.05%/side):
    BASE     : fixed TP at 2:1  (EXP019 reference)
    TRAIL-A  : trailing 1.5×ATR14(15m), activates at +1:1
    TRAIL-B  : trailing 2.0×ATR14(15m), activates at +1:1  (more room)
    TRAIL-C  : trailing 1.5×ATR14(15m), activates at break-even  (more aggressive)
    HYBRID   : fixed TP 2:1 OR trailing 3×ATR — whichever hits first

ATR(14) is computed on the 15m candles (same timeframe as entry).

Assets:
    BTC/USDT — longs only,   SL≥0.30%,  RR=2:1 base
    ETH/USDT — longs+shorts, SL≥0.50%,  RR=2:1 base

Success criteria (KEEP):
    PF improves >= 0.05 over BASE for both assets, OR
    Total return improves >= 10% with MaxDD not worse
    Walk-forward (4×182d) combined PF >= 1.0 in all windows
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
MAX_SLOPE_PCT    = 0.20   # EXP019 SLOPE_CAP — fixed

ATR_PERIOD       = 14

VARIANTS = {
    'BASE':    {'mode': 'fixed',   'trail_mult': None, 'activation': None},
    'TRAIL-A': {'mode': 'trail',   'trail_mult': 1.5,  'activation': 1.0},  # activates at +1R
    'TRAIL-B': {'mode': 'trail',   'trail_mult': 2.0,  'activation': 1.0},  # wider trail
    'TRAIL-C': {'mode': 'trail',   'trail_mult': 1.5,  'activation': 0.0},  # activates at BE
    'HYBRID':  {'mode': 'hybrid',  'trail_mult': 3.0,  'activation': 0.0},  # TP2:1 or trail3×
}

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]


def add_atr14_15m(df: pd.DataFrame) -> pd.DataFrame:
    """Add ATR(14) to the 15m dataframe."""
    out = df.copy()
    high  = out['high']
    low   = out['low']
    close = out['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr14_15m'] = tr.ewm(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False).mean()
    return out


def calculate_sl_tp(entry, direction, candle_low, candle_high, rr=2.0):
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


def check_trail_exit(pos: dict, row: dict, variant_cfg: dict) -> tuple | None:
    """
    Check exit for a position that may have a trailing stop.
    Returns (reason, exit_price) or None.
    """
    direction  = pos['direction']
    sl         = pos['sl']
    tp         = pos.get('tp')           # None for pure trailing (no fixed TP)
    trail_sl   = pos.get('trail_sl')
    trail_active = pos.get('trail_active', False)
    mode       = variant_cfg['mode']

    hi = row['high']
    lo = row['low']

    # Update trailing stop if active
    if trail_active and trail_sl is not None:
        atr = row.get('atr14_15m')
        if atr and not pd.isna(atr):
            mult = variant_cfg['trail_mult']
            if direction == 'long':
                new_trail = hi - mult * atr
                pos['trail_sl'] = max(trail_sl, new_trail)
            else:
                new_trail = lo + mult * atr
                pos['trail_sl'] = min(trail_sl, new_trail)
        trail_sl = pos['trail_sl']
    elif not trail_active:
        # Check if trailing activates this bar
        activation = variant_cfg.get('activation')
        if activation is not None:
            risk    = pos['risk']
            atr     = row.get('atr14_15m')
            if atr and not pd.isna(atr):
                mult    = variant_cfg['trail_mult']
                act_price = pos['entry'] + activation * risk if direction == 'long' \
                            else pos['entry'] - activation * risk
                if (direction == 'long' and hi >= act_price) or \
                   (direction == 'short' and lo <= act_price):
                    pos['trail_active'] = True
                    if direction == 'long':
                        pos['trail_sl'] = hi - mult * atr
                    else:
                        pos['trail_sl'] = lo + mult * atr
                    trail_sl = pos['trail_sl']
                    trail_active = True

    # Determine what exits are active
    active_sl = trail_sl if (trail_active and trail_sl is not None) else sl

    if direction == 'long':
        sl_hit = lo <= active_sl
        tp_hit = (tp is not None) and (hi >= tp)
    else:
        sl_hit = hi >= active_sl
        tp_hit = (tp is not None) and (lo <= tp)

    if sl_hit and tp_hit:
        bearish = row['close'] < row['open']
        if direction == 'long':
            return ('SL', active_sl) if bearish else ('TP', tp)
        else:
            return ('SL', active_sl) if not bearish else ('TP', tp)
    if tp_hit:
        return ('TP', tp)
    if sl_hit:
        reason = 'TRAIL' if (trail_active and trail_sl is not None) else 'SL'
        return (reason, active_sl)
    return None


def run(df: pd.DataFrame, longs_only: bool, min_sl_pct: float,
        variant_cfg: dict, start: str = None, end: str = None) -> list:
    """Run backtest for a single variant. Returns list of closed trades."""
    if start and end:
        mask = (df['open_time'] >= start) & (df['open_time'] < end)
        frame = df[mask].reset_index(drop=True)
    else:
        frame = df

    equity   = INITIAL_CAPITAL
    position = None
    trades   = []
    mode     = variant_cfg['mode']

    for _, row in frame.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        # ── Exit check ────────────────────────────────────────────────────────
        if position is not None:
            result = check_trail_exit(position, row, variant_cfg)
            if result is not None:
                reason, exit_price = result
                qty   = position['qty']
                gross = (exit_price - position['entry']) * qty \
                        if position['direction'] == 'long' \
                        else (position['entry'] - exit_price) * qty
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl

                risk        = position['risk']
                exit_mult   = (exit_price - position['entry']) / risk \
                              if position['direction'] == 'long' \
                              else (position['entry'] - exit_price) / risk

                trades.append({
                    'open_time':   str(position['open_time']),
                    'close_time':  str(row['open_time']),
                    'direction':   position['direction'],
                    'entry':       position['entry'],
                    'exit':        exit_price,
                    'sl':          position['sl'],
                    'tp':          position.get('tp'),
                    'sl_dist_pct': position['sl_dist_pct'],
                    'reason':      reason,
                    'exit_mult':   round(exit_mult, 3),
                    'gross_pnl':   round(gross, 4),
                    'fee_usd':     round(fee, 4),
                    'pnl':         round(net_pnl, 4),
                    'equity':      round(equity, 4),
                })
                position = None
            continue

        # ── Entry check ───────────────────────────────────────────────────────
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

        slope_pct = row.get('ema50_slope_pct')
        if not pd.isna(slope_pct) and abs(slope_pct) > MAX_SLOPE_PCT:
            continue

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']

        sl, tp_fixed = calculate_sl_tp(entry, direction, row['low'], row['high'], rr=2.0)
        if sl is None:
            continue
        risk_price  = abs(entry - sl)
        sl_dist_pct = risk_price / entry
        if sl_dist_pct < min_sl_pct:
            continue

        # TP assignment per mode
        if mode == 'fixed':
            tp = tp_fixed
        elif mode in ('trail', 'hybrid'):
            tp = tp_fixed if mode == 'hybrid' else None
        else:
            tp = tp_fixed

        risk_usd = equity * RISK_PCT
        position = {
            'open_time':    row['open_time'],
            'direction':    direction,
            'entry':        entry,
            'sl':           sl,
            'tp':           tp,
            'qty':          risk_usd / risk_price,
            'risk':         risk_price,
            'sl_dist_pct':  round(sl_dist_pct * 100, 4),
            'trail_active': False,
            'trail_sl':     None,
        }

    return trades


def metrics(trades: list) -> dict:
    if not trades:
        return {'total_trades': 0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum()
    gl   = abs(loss['pnl'].sum())
    pf   = gp / gl if gl > 0 else float('inf')
    peak, max_dd = INITIAL_CAPITAL, 0.0
    eq = INITIAL_CAPITAL
    for p in df['pnl']:
        eq    += p
        peak   = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    total_ret = (df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # Exit reason breakdown
    reasons = df['reason'].value_counts().to_dict()

    # Trades that exceeded the original 2:1
    exceeded_2r = df[df['exit_mult'] > 2.0]

    return {
        'total_trades':    len(df),
        'win_rate_pct':    round(len(wins) / len(df) * 100, 1),
        'return_pct':      round(total_ret, 2),
        'max_dd_pct':      round(max_dd, 2),
        'profit_factor':   round(pf, 3),
        'expectancy_usd':  round(df['pnl'].mean(), 2),
        'total_fees_usd':  round(df['fee_usd'].sum(), 2),
        'avg_exit_mult':   round(df['exit_mult'].mean(), 3),
        'pct_exceeded_2r': round(len(exceeded_2r) / len(df) * 100, 1),
        'avg_mult_exceeded': round(exceeded_2r['exit_mult'].mean(), 2) if len(exceeded_2r) else 0,
        'exit_reasons':    reasons,
    }


def regime_split(trades: list) -> dict:
    def _m(subset): return metrics(subset) if subset else {}
    return {
        'bull_2024':     _m([t for t in trades if t['close_time'] < '2024-10-01']),
        'ath_2024_25':   _m([t for t in trades if '2024-10-01' <= t['close_time'] < '2025-04-01']),
        'recovery_2025': _m([t for t in trades if '2025-04-01' <= t['close_time'] < '2025-10-01']),
        'bear_2025_26':  _m([t for t in trades if t['close_time'] >= '2025-10-01']),
    }


def wf_combined_pf(btc_trades: list, eth_trades: list, start: str, end: str) -> float:
    """Compute combined BTC+ETH PF for a time window."""
    all_t = [t for t in btc_trades + eth_trades
             if start <= t['close_time'] < end]
    if not all_t:
        return 0.0
    wins = [t for t in all_t if t['pnl'] > 0]
    loss = [t for t in all_t if t['pnl'] <= 0]
    gp = sum(t['pnl'] for t in wins)
    gl = abs(sum(t['pnl'] for t in loss))
    return round(gp / gl, 3) if gl > 0 else float('inf')


ASSET_CONFIGS = {
    'BTC': {
        'path_1h':    'data/BTCUSDT_1h_last_740d.csv',
        'path_15m':   'data/BTCUSDT_15m_last_730d.csv',
        'longs_only': True,
        'min_sl_pct': 0.0030,
        'label':      'BTC/USDT — longs only  SL≥0.30%',
        'base_pf':    1.390,
    },
    'ETH': {
        'path_1h':    'data/ETHUSDT_1h_last_740d.csv',
        'path_15m':   'data/ETHUSDT_15m_last_730d.csv',
        'longs_only': False,
        'min_sl_pct': 0.0050,
        'label':      'ETH/USDT — longs+shorts  SL≥0.50%',
        'base_pf':    1.386,
    },
}


def print_asset_report(asset: str, cfg: dict, results: dict) -> None:
    vnames = list(VARIANTS.keys())
    w = 12

    print(f"\n{'='*90}")
    print(f"  TASK001  |  {cfg['label']}")
    print(f"  Trailing stop vs TP fijo 2:1  |  SLOPE_CAP=0.20%  |  730d con fees")
    print(f"{'='*90}")

    header = f"  {'Métrica':<22}" + ''.join(f"  {v:>{w}}" for v in vnames)
    print(header)
    print(f"  {'-'*88}")

    fields = [
        ('Trades',          'total_trades',      '{:d}'),
        ('Win rate %',      'win_rate_pct',       '{:.1f}'),
        ('Return %',        'return_pct',         '{:+.2f}'),
        ('Max DD %',        'max_dd_pct',         '{:.2f}'),
        ('Profit factor',   'profit_factor',      '{:.3f}'),
        ('Expectancy $',    'expectancy_usd',     '{:+.2f}'),
        ('Avg exit mult',   'avg_exit_mult',      '{:.2f}×'),
        ('% super 2R',      'pct_exceeded_2r',    '{:.1f}%'),
        ('Avg mult >2R',    'avg_mult_exceeded',  '{:.2f}×'),
        ('Total fees $',    'total_fees_usd',     '{:.0f}'),
    ]

    for label, key, fmt in fields:
        row = f"  {label:<22}"
        for v in vnames:
            m   = results[v]['metrics']
            val = m.get(key, 0) if m else 0
            row += f"  {fmt.format(val):>{w}}"
        print(row)

    # Exit reason breakdown
    print(f"\n  ── RAZONES DE SALIDA ─────────────────────────────────────────────────────────────")
    all_reasons = set()
    for v in vnames:
        all_reasons |= set(results[v]['metrics'].get('exit_reasons', {}).keys())
    for reason in sorted(all_reasons):
        row = f"  {reason:<22}"
        for v in vnames:
            cnt = results[v]['metrics'].get('exit_reasons', {}).get(reason, 0)
            row += f"  {cnt:>{w}d}"
        print(row)

    # Regime breakdown for BASE and best variant
    best_v  = max(vnames[1:], key=lambda v: results[v]['metrics'].get('profit_factor', 0))
    regimes = [
        ('bull_2024',     'Bull 2024'),
        ('ath_2024_25',   'ATH 2024-25'),
        ('recovery_2025', 'Recovery 2025'),
        ('bear_2025_26',  'Bear 2025-26'),
    ]
    print(f"\n  ── DESGLOSE POR RÉGIMEN (BASE vs {best_v}) ──────────────────────────────────────────")
    print(f"  {'Variante':<12}  {'Régimen':<22}  {'T':>4}  {'WR%':>5}  {'PF':>6}  {'Ret%':>7}  {'Mult':>6}")
    print(f"  {'-'*72}")
    for v in ['BASE', best_v]:
        rg = results[v]['regime']
        for rkey, rlabel in regimes:
            rm = rg.get(rkey, {})
            if rm and rm.get('total_trades', 0) > 0:
                print(f"  [{v}]{'':5}  {rlabel:<22}  "
                      f"{rm['total_trades']:>4}  "
                      f"{rm['win_rate_pct']:>4.0f}%  "
                      f"{rm['profit_factor']:>6.3f}  "
                      f"{rm['return_pct']:>+6.1f}%  "
                      f"{rm.get('avg_exit_mult', 0):>5.2f}×")

    # Verdict
    base_pf  = results['BASE']['metrics'].get('profit_factor', 0)
    best_pf  = results[best_v]['metrics'].get('profit_factor', 0)
    best_ret = results[best_v]['metrics'].get('return_pct', 0)
    base_ret = results['BASE']['metrics'].get('return_pct', 0)
    best_dd  = results[best_v]['metrics'].get('max_dd_pct', 99)
    base_dd  = results['BASE']['metrics'].get('max_dd_pct', 99)

    print(f"\n  ── VEREDICTO ─────────────────────────────────────────────────────────────────────")
    print(f"  BASE PF:       {base_pf:.3f}  |  Return: {base_ret:+.1f}%  |  MaxDD: {base_dd:.1f}%")
    print(f"  Mejor [{best_v}]:  PF={best_pf:.3f}  |  Return: {best_ret:+.1f}%  |  MaxDD: {best_dd:.1f}%")
    print(f"{'='*90}\n")


if __name__ == '__main__':
    print(f"\nTASK001 — Trailing Stop  |  SLOPE_CAP=0.20%  |  730d con fees\n")

    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        if not os.path.exists(cfg['path_15m']):
            print(f"[{asset_name}] ERROR: datos no encontrados.")
            continue

        print(f"[{asset_name}] Preparando datos...", flush=True)
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = prepare_1h(df_1h_raw)
        df_15m = prepare_15m(df_15m_raw)
        df_15m = add_atr14_15m(df_15m)
        df     = align_1h_to_15m(df_15m, df_1h)

        asset_results = {}
        for vname, vcfg in VARIANTS.items():
            trades = run(
                df         = df,
                longs_only = cfg['longs_only'],
                min_sl_pct = cfg['min_sl_pct'],
                variant_cfg = vcfg,
            )
            m  = metrics(trades)
            rg = regime_split(trades)
            asset_results[vname] = {
                'metrics': m,
                'regime':  rg,
                'trades':  trades,
            }
            pf = m.get('profit_factor', 0)
            t  = m.get('total_trades', 0)
            mult = m.get('avg_exit_mult', 0)
            print(f"  [{vname:8}] trades={t:>3}  PF={pf:.3f}  avg_mult={mult:.2f}×")

        all_results[asset_name] = asset_results
        print_asset_report(asset_name, cfg, asset_results)

    # Walk-forward combined PF
    print(f"\n{'='*90}")
    print(f"  TASK001  |  Walk-forward combinado BTC+ETH (4×182d)")
    print(f"{'='*90}")
    print(f"  {'Ventana':<6}  {'Período':<22}" + ''.join(f"  {v:>10}" for v in VARIANTS.keys()))
    print(f"  {'-'*85}")

    for wid, start, end, label in WINDOWS:
        row = f"  {wid:<6}  {label:<22}"
        for vname in VARIANTS.keys():
            btc_t = all_results.get('BTC', {}).get(vname, {}).get('trades', [])
            eth_t = all_results.get('ETH', {}).get(vname, {}).get('trades', [])
            cpf   = wf_combined_pf(btc_t, eth_t, start, end)
            flag  = '✅' if cpf >= 1.0 else '❌'
            row  += f"  {cpf:>7.3f} {flag}"
        print(row)

    # Save
    out_path = 'data/backtest_task001.json'
    with open(out_path, 'w') as f:
        json.dump(
            {a: {v: {'metrics': r['metrics'], 'regime': r['regime']}
                 for v, r in vr.items()}
             for a, vr in all_results.items()},
            f, indent=2, default=str,
        )
    print(f"\nResultados guardados en {out_path}")
