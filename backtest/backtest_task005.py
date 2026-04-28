"""
TASK 005 — Tercer Activo: SOL/USDT

Base: EXP019 SLOPE_CAP (0.20%).

Hypothesis:
    SOL/USDT with the same pullback continuation + SLOPE_CAP strategy has PF > 1.2
    on 730d with fees. Adding SOL to the BTC+ETH system improves the combined PF
    and provides additional regime diversification.

Phase 1: Validate SOL individually (same params as ETH — longs+shorts, SL>=0.50%)
Phase 2: Walk-forward 4x182d for BTC+ETH+SOL combined system

If SOL PF < 1.0: REVERT — dilutes existing edge.
If SOL PF 1.0-1.2: ITERATE — try adjusting min SL%.
If SOL PF > 1.2: KEEP — add to system.
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

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]

# Test multiple min_sl variants for SOL to find viable threshold
SOL_SL_VARIANTS = {
    'SOL_SL040': 0.0040,
    'SOL_SL050': 0.0050,
    'SOL_SL060': 0.0060,
    'SOL_SL070': 0.0070,
}


def calculate_sl_tp(entry, direction, low, high, rr=2.0):
    if direction == 'long':
        sl = low; risk = entry - sl
        if risk <= 0: return None, None
        return sl, entry + rr * risk
    else:
        sl = high; risk = sl - entry
        if risk <= 0: return None, None
        return sl, entry - rr * risk


def run(df, longs_only, min_sl_pct, start=None, end=None):
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
                    'sl_dist_pct': position['sl_dist_pct'],
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
            'sl_dist_pct': round(risk_price / entry * 100, 4),
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
    avg_sl = df['sl_dist_pct'].mean() if 'sl_dist_pct' in df else 0
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'avg_sl_dist_pct': round(avg_sl, 3),
    }


def regime_split(trades):
    def _m(subset): return metrics(subset) if subset else {}
    return {
        'bull_2024':     _m([t for t in trades if t['close_time'] < '2024-10-01']),
        'ath_2024_25':   _m([t for t in trades if '2024-10-01' <= t['close_time'] < '2025-04-01']),
        'recovery_2025': _m([t for t in trades if '2025-04-01' <= t['close_time'] < '2025-10-01']),
        'bear_2025_26':  _m([t for t in trades if t['close_time'] >= '2025-10-01']),
    }


def wf_combined_pf_3(btc_t, eth_t, sol_t, start, end):
    all_t = [t for t in btc_t + eth_t + sol_t if start <= t['close_time'] < end]
    if not all_t: return 0.0
    gp = sum(t['pnl'] for t in all_t if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in all_t if t['pnl'] <= 0))
    return round(gp / gl, 3) if gl > 0 else float('inf')


def wf_combined_pf_2(btc_t, eth_t, start, end):
    all_t = [t for t in btc_t + eth_t if start <= t['close_time'] < end]
    if not all_t: return 0.0
    gp = sum(t['pnl'] for t in all_t if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in all_t if t['pnl'] <= 0))
    return round(gp / gl, 3) if gl > 0 else float('inf')


if __name__ == '__main__':
    print(f"\nTASK005 — Tercer Activo SOL/USDT  |  SLOPE_CAP=0.20%  |  730d con fees\n")

    # ── Phase 1: SOL individual, multiple SL thresholds ───────────────────────
    print("=" * 70)
    print("  FASE 1 — SOL/USDT individual (longs+shorts, variantes SL mínimo)")
    print("=" * 70)

    sol_path_1h  = 'data/SOLUSDT_1h_last_740d.csv'
    sol_path_15m = 'data/SOLUSDT_15m_last_730d.csv'

    if not os.path.exists(sol_path_15m):
        print("  ERROR: datos SOL no encontrados.")
        print("  Ejecutar: python fetch_all_sol.py")
        sys.exit(1)

    df_1h_raw, df_15m_raw = load_data(sol_path_1h, sol_path_15m)
    df_1h_sol  = prepare_1h(df_1h_raw)
    df_15m_sol = prepare_15m(df_15m_raw)
    df_sol     = align_1h_to_15m(df_15m_sol, df_1h_sol)

    sol_results = {}
    best_sl_variant = None
    best_pf = 0.0

    for vname, min_sl in SOL_SL_VARIANTS.items():
        trades = run(df_sol, longs_only=False, min_sl_pct=min_sl)
        m = metrics(trades)
        rg = regime_split(trades)
        sol_results[vname] = {'metrics': m, 'trades': trades, 'regime': rg}
        pf = m.get('profit_factor', 0)
        print(f"  [{vname}] trades={m['total_trades']:>3}  PF={pf:.3f}  "
              f"WR={m['win_rate_pct']:.1f}%  Return={m['return_pct']:+.1f}%  "
              f"MaxDD={m['max_dd_pct']:.1f}%  avg_SL={m.get('avg_sl_dist_pct',0):.3f}%")
        if pf > best_pf and m['total_trades'] >= 80:
            best_pf = pf
            best_sl_variant = vname

    if best_sl_variant:
        best_min_sl = SOL_SL_VARIANTS[best_sl_variant]
        print(f"\n  Mejor variante SOL: {best_sl_variant}  PF={best_pf:.3f}  min_SL={best_min_sl*100:.2f}%")
        bm = sol_results[best_sl_variant]['metrics']
        phase1_ok = best_pf > 1.0 and bm['total_trades'] >= 80 and bm['max_dd_pct'] < 20
        print(f"  Criterio Fase 1 (PF>1.0, T≥80, MaxDD<20%): {'✅ PASA' if phase1_ok else '❌ FALLA'}")
    else:
        print("\n  ❌ Ninguna variante cumple criterio mínimo (trades≥80)")
        phase1_ok = False

    # Regime breakdown for best variant
    if best_sl_variant:
        print(f"\n  ── Desglose por régimen ({best_sl_variant})")
        rg = sol_results[best_sl_variant]['regime']
        print(f"  {'Régimen':<25}  {'T':>4}  {'WR%':>5}  {'PF':>6}  {'Ret%':>7}")
        print(f"  {'-'*50}")
        for rkey, rlabel in [
            ('bull_2024',     'Bull 2024'),
            ('ath_2024_25',   'ATH 2024-25'),
            ('recovery_2025', 'Recovery 2025'),
            ('bear_2025_26',  'Bear 2025-26'),
        ]:
            rm = rg.get(rkey, {})
            if rm and rm.get('total_trades', 0) > 0:
                flag = '✅' if rm['profit_factor'] >= 1.0 else '❌'
                print(f"  {rlabel:<25}  {rm['total_trades']:>4}  {rm['win_rate_pct']:>4.0f}%  "
                      f"{rm['profit_factor']:>6.3f}  {rm['return_pct']:>+6.1f}%  {flag}")

    # ── Phase 2: Combined BTC+ETH+SOL walk-forward ────────────────────────────
    print(f"\n{'='*70}")
    print(f"  FASE 2 — Walk-forward combinado BTC+ETH+SOL (4×182d)")
    print(f"{'='*70}")

    # Load BTC and ETH (use best params from task001 REVERT = same as EXP019)
    btc_cfg = {'path_1h': 'data/BTCUSDT_1h_last_740d.csv', 'path_15m': 'data/BTCUSDT_15m_last_730d.csv',
               'longs_only': True, 'min_sl_pct': 0.0030}
    eth_cfg = {'path_1h': 'data/ETHUSDT_1h_last_740d.csv', 'path_15m': 'data/ETHUSDT_15m_last_730d.csv',
               'longs_only': False, 'min_sl_pct': 0.0050}

    print("  Preparando BTC y ETH...", flush=True)
    df_1h_raw, df_15m_raw = load_data(btc_cfg['path_1h'], btc_cfg['path_15m'])
    df_btc = align_1h_to_15m(prepare_15m(df_15m_raw), prepare_1h(df_1h_raw))
    btc_trades = run(df_btc, btc_cfg['longs_only'], btc_cfg['min_sl_pct'])

    df_1h_raw, df_15m_raw = load_data(eth_cfg['path_1h'], eth_cfg['path_15m'])
    df_eth = align_1h_to_15m(prepare_15m(df_15m_raw), prepare_1h(df_1h_raw))
    eth_trades = run(df_eth, eth_cfg['longs_only'], eth_cfg['min_sl_pct'])

    sol_best_trades = sol_results[best_sl_variant]['trades'] if best_sl_variant else []
    best_min_sl_val = SOL_SL_VARIANTS.get(best_sl_variant, 0.0050) if best_sl_variant else 0.0050

    print(f"\n  {'Ventana':<6}  {'Período':<22}  {'BTC+ETH':>10}  {'BTC+ETH+SOL':>13}  {'Δ':>6}")
    print(f"  {'-'*65}")
    for wid, start, end, label in WINDOWS:
        pf2 = wf_combined_pf_2(btc_trades, eth_trades, start, end)
        pf3 = wf_combined_pf_3(btc_trades, eth_trades, sol_best_trades, start, end)
        delta = pf3 - pf2
        flag2 = '✅' if pf2 >= 1.0 else '❌'
        flag3 = '✅' if pf3 >= 1.0 else '❌'
        sign = '+' if delta >= 0 else ''
        print(f"  {wid:<6}  {label:<22}  {pf2:>8.3f}{flag2}  {pf3:>11.3f}{flag3}  {sign}{delta:.3f}")

    # Verdict
    print(f"\n  ── VEREDICTO FINAL ──────────────────────────────────────────────────")
    if not best_sl_variant:
        print(f"  ❌ SOL no tiene suficientes trades. REVERT.")
    elif not phase1_ok:
        print(f"  ❌ SOL no pasa Fase 1 (PF<1.0 o MaxDD>20%). REVERT.")
    else:
        wf_pass = sum(1 for _, s, e, _ in WINDOWS
                      if wf_combined_pf_3(btc_trades, eth_trades, sol_best_trades, s, e) >= 1.0)
        if best_pf >= 1.2 and wf_pass == 4:
            print(f"  ✅ SOL pasa Fase 1 (PF={best_pf:.3f}) y walk-forward ({wf_pass}/4).")
            print(f"     → KEEP: añadir SOL al sistema con min_SL={best_min_sl_val*100:.2f}%")
        elif best_pf >= 1.0 and wf_pass >= 3:
            print(f"  ⚠️  SOL pasa Fase 1 (PF={best_pf:.3f}) pero walk-forward parcial ({wf_pass}/4).")
            print(f"     → ITERAR: ajustar umbral de SL mínimo")
        else:
            print(f"  ❌ SOL no aporta mejora robusta. REVERT.")

    print(f"{'='*70}\n")

    out_path = 'data/backtest_task005.json'
    with open(out_path, 'w') as f:
        json.dump({v: r['metrics'] for v, r in sol_results.items()}, f, indent=2, default=str)
    print(f"Resultados guardados en {out_path}")
