"""
EXP_B — BTC/USDT 730d: ¿Llega BTC a PF≥1.3 con filtro 4h?

Pregunta: El 4h filter (Task010-B) subió PF en 180d pero nunca se testeó en 730d.
¿Puede alguna combinación de 4h slope + ADX llevar BTC de PF=1.097 a ≥1.3?

Baseline: EXP017-B (longs only, SL≥0.30%, RR=2:1, fees 0.05%/lado)
Datos: BTCUSDT_15m_last_730d.csv + BTCUSDT_1h_last_740d.csv

Variantes:
  B0 — Baseline EXP017-B (sin filtros adicionales)
  B1 — 4h slope>0%    (mínimo bullish en 4h)
  B2 — 4h slope>0.03% (Task010-B actual)
  B3 — 4h slope>0.05% (más estricto)
  B4 — ADX>25 gate    (solo trending)
  B5 — ADX>25 + 4h slope>0.03%

Criterio KEEP: PF≥1.3 con ≥80 trades en 730d.
Criterio FAIL: Ninguna variante supera PF=1.3 → continuar búsqueda en Fase 2.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    prepare_4h, align_4h_to_15m,
    get_trend, is_trend_strong, is_pullback_quality,
    is_entry_trigger, is_candle_quality,
    is_range_sufficient, is_market_efficient,
)
from core.trade_logic import check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005
MIN_SL_PCT       = 0.0030   # EXP017-B
RR               = 2.0
LONGS_ONLY       = True

PATH_1H  = 'data/BTCUSDT_1h_last_740d.csv'
PATH_15M = 'data/BTCUSDT_15m_last_730d.csv'

MIN_TRADES_THRESHOLD = 80
PF_THRESHOLD         = 1.3


def run(slope_4h_min: float | None, adx_min: float | None) -> list:
    df_1h_raw, df_15m_raw = load_data(PATH_1H, PATH_15M)
    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)
    df_4h  = prepare_4h(df_1h_raw)
    df     = align_4h_to_15m(df, df_4h)

    equity, position, trades = INITIAL_CAPITAL, None, []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty   = position['qty']
                gross = (exit_price - position['entry']) * qty  # longs only
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'direction':   position['direction'],
                    'entry':       position['entry'],
                    'exit':        exit_price,
                    'reason':      reason,
                    'gross_pnl':   round(gross, 4),
                    'fee_usd':     round(fee, 4),
                    'pnl':         round(net_pnl, 4),
                    'equity':      round(equity, 4),
                    'open_time':   str(position['open_time']),
                    'slope_4h':    position.get('slope_4h'),
                    'adx14':       position.get('adx14'),
                })
                position = None
            continue

        trend = get_trend(row)
        if trend is None or trend != 'up': continue  # longs only
        if not is_trend_strong(row): continue
        if not is_pullback_quality(row, trend): continue
        if not is_entry_trigger(row, trend): continue
        if not is_candle_quality(row, trend): continue
        if not is_range_sufficient(row): continue
        if not is_market_efficient(row): continue

        # 4h slope gate
        if slope_4h_min is not None:
            slope_val = row.get('slope_4h_pct')
            if pd.isna(slope_val) or slope_val < slope_4h_min:
                continue

        # ADX gate (column is adx_1h after align_1h_to_15m rename)
        if adx_min is not None:
            adx_val = row.get('adx_1h')
            if pd.isna(adx_val) or adx_val < adx_min:
                continue

        entry = row['close']
        sl    = row['low']
        risk  = entry - sl
        if risk <= 0: continue
        if risk / entry < MIN_SL_PCT: continue
        tp = entry + RR * risk

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'direction': 'long',
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       risk_usd / risk,
            'slope_4h':  row.get('slope_4h_pct'),
            'adx_1h':    row.get('adx_1h'),
        }

    return trades


def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0, 'return_pct': 0,
                'max_dd': 0, 'win_rate': 0, 'fees': 0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum()
    gl   = abs(loss['pnl'].sum())
    pf   = round(gp / gl, 3) if gl > 0 else float('inf')

    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p
        peak   = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)

    return {
        'label':      label,
        'trades':     len(df),
        'win_rate':   round(len(wins) / len(df) * 100, 1),
        'pf':         pf,
        'return_pct': round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd':     round(max_dd, 2),
        'fees':       round(df['fee_usd'].sum(), 2),
        'trades_raw': trades,
    }


def monthly_breakdown(trades: list) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    df['month'] = pd.to_datetime(df['open_time']).dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        wins = g[g['pnl'] > 0]
        gl   = abs(g[g['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        rows.append({
            'month': str(month),
            'n':     len(g),
            'wr':    round(len(wins) / len(g) * 100, 1),
            'pf':    round(gp / gl, 3) if gl > 0 else float('inf'),
            'pnl':   round(g['pnl'].sum(), 2),
        })
    return pd.DataFrame(rows)


VARIANTS = [
    (None,   None,  'B0 — Baseline EXP017-B'),
    (0.0,    None,  'B1 — 4h slope>0%'),
    (0.03,   None,  'B2 — 4h slope>0.03% (Task010-B)'),
    (0.05,   None,  'B3 — 4h slope>0.05%'),
    (None,   25.0,  'B4 — ADX>25'),
    (0.03,   25.0,  'B5 — 4h slope>0.03% + ADX>25'),
]

VERDICT = {True: '✅ KEEP', False: '❌ FAIL'}


if __name__ == '__main__':
    print("\nEXP_B — BTC/USDT 730d | EXP017-B base | longs only | fees 0.05%/lado")
    print(f"Criterio KEEP: PF≥{PF_THRESHOLD} con ≥{MIN_TRADES_THRESHOLD} trades\n")

    results = []
    for slope_min, adx_min, label in VARIANTS:
        print(f"  {label}...", end='', flush=True)
        trades = run(slope_min, adx_min)
        m = metrics(trades, label)
        results.append(m)
        print(f" {m['trades']} trades  PF={m['pf']}  ret={m['return_pct']:+.1f}%")

    # ── Summary table ──────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  RESULTADOS EXP_B — BTC 730d")
    print(f"{'='*80}")
    print(f"  {'Variante':<35} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7} {'Fees':>8}  Veredicto")
    print(f"  {'-'*80}")
    for m in results:
        passes = m['trades'] >= MIN_TRADES_THRESHOLD and m['pf'] >= PF_THRESHOLD
        print(f"  {m['label']:<35} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}% ${m['fees']:>7.2f}  {VERDICT[passes]}")

    # ── Best variant monthly breakdown ────────────────────────────────────────
    best = max(results, key=lambda x: x['pf'] if x['trades'] >= MIN_TRADES_THRESHOLD else 0)
    passes_best = best['trades'] >= MIN_TRADES_THRESHOLD and best['pf'] >= PF_THRESHOLD
    print(f"\n{'='*80}")
    print(f"  MEJOR VARIANTE: {best['label']}  {'✅ KEEP' if passes_best else '❌ FAIL'}")
    print(f"  PF={best['pf']}  trades={best['trades']}  ret={best['return_pct']:+.1f}%  MaxDD={best['max_dd']:.1f}%")
    if best['trades'] > 0:
        mb = monthly_breakdown(best['trades_raw'])
        print(f"\n  Breakdown mensual:")
        print(f"  {'Mes':<10} {'N':>4} {'WR':>6} {'PF':>7} {'PnL':>9}")
        print(f"  {'-'*40}")
        for _, row in mb.iterrows():
            flag = '✓' if row['pf'] >= 1.0 else '✗'
            print(f"  {row['month']:<10} {row['n']:>4} {row['wr']:>5.1f}% {row['pf']:>7.3f} ${row['pnl']:>+8.2f}  {flag}")

    # ── Trades per day analysis ───────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  FRECUENCIA DE TRADES")
    print(f"  {'Variante':<35} {'T/día':>7} {'T/mes est.':>10}")
    print(f"  {'-'*55}")
    for m in results:
        tpd  = round(m['trades'] / 730, 2)
        tpm  = round(tpd * 30, 1)
        print(f"  {m['label']:<35} {tpd:>7.2f} {tpm:>10.1f}")

    # ── Final verdict ─────────────────────────────────────────────────────────
    any_pass = any(m['trades'] >= MIN_TRADES_THRESHOLD and m['pf'] >= PF_THRESHOLD for m in results)
    print(f"\n{'='*80}")
    if any_pass:
        keepers = [m for m in results if m['trades'] >= MIN_TRADES_THRESHOLD and m['pf'] >= PF_THRESHOLD]
        print(f"  VEREDICTO FINAL: ✅ BTC PASA — {len(keepers)} variante(s) superan PF={PF_THRESHOLD}")
        for k in keepers:
            print(f"    → {k['label']}  PF={k['pf']}  trades={k['trades']}")
        print(f"  Usar configuración con mejor balance PF/frecuencia para producción.")
    else:
        print(f"  VEREDICTO FINAL: ❌ BTC NO ALCANZA PF={PF_THRESHOLD} con ≥{MIN_TRADES_THRESHOLD} trades")
        best_pf = max(results, key=lambda x: x['pf'])
        print(f"  Mejor PF encontrado: {best_pf['pf']} ({best_pf['trades']} trades) — {best_pf['label']}")
        print(f"  Continuar en Fase 2: backtest BTC sobre 5 años.")
    print(f"{'='*80}\n")
