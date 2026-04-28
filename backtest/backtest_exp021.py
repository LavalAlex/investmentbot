"""
EXP021  —  Walk-forward validation (4 × ~182d)

Validates that EXP019's SLOPE_CAP filter has real edge — not overfitting to the
full 730d dataset. Uses fixed parameters, no re-optimization per window.

Filter applied (from EXP019 SLOPE_CAP):
    Skip entry when EMA50 slope > 0.20%/5bars (parabolic momentum)

Windows (~182d each, same dates as roadmap):
    W1: 2024-04-27 → 2024-10-25  (Bull 2024)
    W2: 2024-10-25 → 2025-04-24  (ATH 2024-25)
    W3: 2025-04-24 → 2025-10-21  (Recovery 2025)
    W4: 2025-10-21 → 2026-04-19  (Bear 2025-26)

Each window runs with fresh $10,000 equity (isolated simulation).

Assets:
    BTC/USDT — longs only,   SL≥0.30%,  RR=2:1  (EXP017-B params)
    ETH/USDT — longs+shorts, SL≥0.50%,  RR=2:1  (EXP016A params)

Success criteria (ALL must pass):
    PF > 1.0 in every window for both assets
    MaxDD < 20% in any individual window
    Trade count >= 20 in each window
"""

import json
import os
import sys
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

MAX_SLOPE_PCT = 0.20  # EXP019 SLOPE_CAP threshold — do not change

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]


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


def run_window(df: pd.DataFrame, start: str, end: str,
               longs_only: bool, min_sl_pct: float, rr: float) -> list:
    """
    Run backtest over a single time window. Returns list of trades.
    df must already be the full aligned 15m+1h dataframe.
    """
    mask = (df['open_time'] >= start) & (df['open_time'] < end)
    window_df = df[mask].reset_index(drop=True)

    equity   = INITIAL_CAPITAL
    position = None
    trades   = []

    for _, row in window_df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        # ── Exit check ────────────────────────────────────────────────────────
        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty   = position['qty']
                gross = (exit_price - position['entry']) * qty \
                        if position['direction'] == 'long' \
                        else (position['entry'] - exit_price) * qty
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'open_time':    str(position['open_time']),
                    'close_time':   str(row['open_time']),
                    'direction':    position['direction'],
                    'entry':        position['entry'],
                    'exit':         exit_price,
                    'sl':           position['sl'],
                    'tp':           position['tp'],
                    'sl_dist_pct':  position['sl_dist_pct'],
                    'slope_1h':     position['slope'],
                    'reason':       reason,
                    'gross_pnl':    round(gross, 4),
                    'fee_usd':      round(fee, 4),
                    'pnl':          round(net_pnl, 4),
                    'equity':       round(equity, 4),
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

        # SLOPE_CAP filter (EXP019)
        slope_pct = row.get('ema50_slope_pct')
        if not pd.isna(slope_pct) and abs(slope_pct) > MAX_SLOPE_PCT:
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

        risk_usd = equity * RISK_PCT
        position = {
            'open_time':   row['open_time'],
            'direction':   direction,
            'entry':       entry,
            'sl':          sl,
            'tp':          tp,
            'qty':         risk_usd / risk_price,
            'sl_dist_pct': round(sl_dist_pct * 100, 4),
            'slope':       round(float(slope_pct), 4) if not pd.isna(slope_pct) else None,
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
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
    }


ASSET_CONFIGS = {
    'BTC': {
        'path_1h':    'data/BTCUSDT_1h_last_740d.csv',
        'path_15m':   'data/BTCUSDT_15m_last_730d.csv',
        'longs_only': True,
        'min_sl_pct': 0.0030,
        'rr':         2.0,
        'label':      'BTC/USDT — longs only  SL≥0.30%  RR=2:1',
        'exp019_pf':  1.390,
    },
    'ETH': {
        'path_1h':    'data/ETHUSDT_1h_last_740d.csv',
        'path_15m':   'data/ETHUSDT_15m_last_730d.csv',
        'longs_only': False,
        'min_sl_pct': 0.0050,
        'rr':         2.0,
        'label':      'ETH/USDT — longs+shorts  SL≥0.50%  RR=2:1',
        'exp019_pf':  1.386,
    },
}


def print_asset_report(asset: str, cfg: dict, window_results: list) -> None:
    print(f"\n{'='*80}")
    print(f"  EXP021  |  {cfg['label']}")
    print(f"  Walk-forward 4×182d  |  SLOPE_CAP={MAX_SLOPE_PCT}%  |  fees 0.05%/lado")
    print(f"  EXP019 PF (730d full): {cfg['exp019_pf']:.3f}")
    print(f"{'='*80}")

    print(f"\n  {'Ventana':<6}  {'Período':<22}  {'T':>4}  {'WR%':>5}  {'PF':>6}  "
          f"{'Ret%':>7}  {'MaxDD%':>7}  {'E$':>7}  {'Criterio'}")
    print(f"  {'-'*78}")

    passed = 0
    total  = 0
    for wid, start, end, label, m in window_results:
        if not m or m.get('total_trades', 0) == 0:
            print(f"  {wid:<6}  {label:<22}  {'—':>4}  {'—':>5}  {'—':>6}  {'—':>7}  {'—':>7}  {'—':>7}  ✗ sin trades")
            total += 1
            continue
        pf    = m['profit_factor']
        dd    = m['max_dd_pct']
        t     = m['total_trades']
        ok_pf = pf > 1.0
        ok_dd = dd < 20.0
        ok_t  = t >= 20
        ok    = ok_pf and ok_dd and ok_t
        flag  = '✅' if ok else '❌'
        issues = []
        if not ok_pf: issues.append(f'PF<1.0')
        if not ok_dd: issues.append(f'DD>{20}%')
        if not ok_t:  issues.append(f'T<20')
        detail = '  ' + ', '.join(issues) if issues else ''
        print(f"  {wid:<6}  {label:<22}  {t:>4}  {m['win_rate_pct']:>4.0f}%  "
              f"{pf:>6.3f}  {m['return_pct']:>+6.1f}%  {dd:>6.1f}%  "
              f"{m['expectancy_usd']:>+6.1f}$  {flag}{detail}")
        if ok:
            passed += 1
        total += 1

    # Full 730d aggregate (all windows combined)
    all_trades = []
    for _, _, _, _, m in window_results:
        pass  # handled separately below

    print(f"\n  Ventanas superadas: {passed}/{total}")

    print(f"\n  ── VEREDICTO {'─'*58}")
    if passed == total and total == 4:
        print(f"  ✅  WALK-FORWARD PASA — edge confirmado en los 4 períodos")
        print(f"     → EXP021 aprobado. Sistema listo para EXP020/Deploy.")
    elif passed >= 3:
        print(f"  ⚠️  WALK-FORWARD PARCIAL — {total-passed} ventana(s) fallan")
        print(f"     → Identificar qué régimen falla. NO re-optimizar para arreglarlo.")
    else:
        print(f"  ❌  WALK-FORWARD FALLA — edge no es robusto inter-período")
        print(f"     → SLOPE_CAP necesita ajuste o el edge es específico a ciertos períodos.")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    print(f"\nEXP021 — Walk-forward validation  |  SLOPE_CAP={MAX_SLOPE_PCT}%  |  4×182d\n")

    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        if not os.path.exists(cfg['path_15m']):
            print(f"[{asset_name}] ERROR: {cfg['path_15m']} no encontrado.")
            continue

        print(f"[{asset_name}] Preparando datos...", flush=True)
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = prepare_1h(df_1h_raw)
        df_15m = prepare_15m(df_15m_raw)
        df     = align_1h_to_15m(df_15m, df_1h)

        window_results = []
        for wid, start, end, label in WINDOWS:
            trades = run_window(
                df         = df,
                start      = start,
                end        = end,
                longs_only = cfg['longs_only'],
                min_sl_pct = cfg['min_sl_pct'],
                rr         = cfg['rr'],
            )
            m = metrics(trades)
            pf = m.get('profit_factor', 0)
            t  = m.get('total_trades', 0)
            print(f"  [{wid}] {label:<22}  trades={t:>3}  PF={pf:.3f}")
            window_results.append((wid, start, end, label, m))

        all_results[asset_name] = window_results
        print_asset_report(asset_name, cfg, window_results)

    # Save JSON
    out_path = 'data/backtest_exp021.json'
    serializable = {
        asset: [
            {'window': wid, 'start': s, 'end': e, 'label': lbl, 'metrics': m}
            for wid, s, e, lbl, m in wrs
        ]
        for asset, wrs in all_results.items()
    }
    with open(out_path, 'w') as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"Resultados guardados en {out_path}")
