"""
EXP_A — ETH/USDT 730d: ¿Existe configuración con PF≥1.3?

Pregunta: ¿Puede ETH EXP016A sobrevivir en 730d con alguna combinación de
filtros ADX, dirección y SL mínimo?

Baseline: EXP016A (longs+shorts, SL≥0.50%, RR=2:1, fees 0.05%/lado)
Datos: ETHUSDT_15m_last_730d.csv + ETHUSDT_1h_last_740d.csv

Variantes:
  A0 — Baseline EXP016A (sin cambios)
  A1 — Longs only (¿los shorts destruyen el edge?)
  A2 — ADX>25 gate (solo entrar en régimen trending)
  A3 — ADX>25 + longs only
  A4 — ADX>20 gate (threshold relajado)
  A5 — ADX>20 + longs only

Criterio KEEP: PF≥1.3 con ≥60 trades en 730d.
Criterio FAIL: Ninguna variante supera PF=1.3 → desactivar ETH en producción.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
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
MIN_SL_PCT       = 0.0050   # EXP016A
RR               = 2.0

PATH_1H  = 'data/ETHUSDT_1h_last_740d.csv'
PATH_15M = 'data/ETHUSDT_15m_last_730d.csv'

MIN_TRADES_THRESHOLD = 60
PF_THRESHOLD         = 1.3


def run(longs_only: bool, adx_min: float | None) -> list:
    df_1h_raw, df_15m_raw = load_data(PATH_1H, PATH_15M)
    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)

    equity, position, trades = INITIAL_CAPITAL, None, []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty   = position['qty']
                gross = ((exit_price - position['entry']) * qty
                         if position['direction'] == 'long'
                         else (position['entry'] - exit_price) * qty)
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'direction': position['direction'],
                    'entry':     position['entry'],
                    'exit':      exit_price,
                    'reason':    reason,
                    'gross_pnl': round(gross, 4),
                    'fee_usd':   round(fee, 4),
                    'pnl':       round(net_pnl, 4),
                    'equity':    round(equity, 4),
                    'open_time': str(position['open_time']),
                    'adx14':     position.get('adx14'),
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

        # ADX gate (column is adx_1h after align_1h_to_15m rename)
        if adx_min is not None:
            adx_val = row.get('adx_1h')
            if pd.isna(adx_val) or adx_val < adx_min:
                continue

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']
        if direction == 'long':
            sl = row['low']; risk = entry - sl
        else:
            sl = row['high']; risk = sl - entry
        if risk <= 0: continue
        if risk / entry < MIN_SL_PCT: continue
        tp = entry + RR * risk if direction == 'long' else entry - RR * risk

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       risk_usd / risk,
            'adx_1h':    row.get('adx_1h'),
        }

    return trades


def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0, 'return_pct': 0, 'max_dd': 0,
                'win_rate': 0, 'fees': 0, 'longs': 0, 'shorts': 0}
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

    longs  = df[df['direction'] == 'long']
    shorts = df[df['direction'] == 'short']

    def side_pf(g):
        w = g[g['pnl'] > 0]['pnl'].sum()
        l = abs(g[g['pnl'] <= 0]['pnl'].sum())
        return round(w / l, 3) if l > 0 else float('inf')

    return {
        'label':      label,
        'trades':     len(df),
        'win_rate':   round(len(wins) / len(df) * 100, 1),
        'pf':         pf,
        'return_pct': round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd':     round(max_dd, 2),
        'fees':       round(df['fee_usd'].sum(), 2),
        'longs':      len(longs),
        'shorts':     len(shorts),
        'long_pf':    side_pf(longs),
        'short_pf':   side_pf(shorts),
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
    (False, None,  'A0 — Baseline (L+S, sin ADX)'),
    (True,  None,  'A1 — Longs only, sin ADX'),
    (False, 25.0,  'A2 — L+S, ADX>25'),
    (True,  25.0,  'A3 — Longs only, ADX>25'),
    (False, 20.0,  'A4 — L+S, ADX>20'),
    (True,  20.0,  'A5 — Longs only, ADX>20'),
]

VERDICT = {True: '✅ KEEP', False: '❌ FAIL'}


if __name__ == '__main__':
    print("\nEXP_A — ETH/USDT 730d | EXP016A base | fees 0.05%/lado")
    print(f"Criterio KEEP: PF≥{PF_THRESHOLD} con ≥{MIN_TRADES_THRESHOLD} trades\n")

    results = []
    for longs_only, adx_min, label in VARIANTS:
        print(f"  {label}...", end='', flush=True)
        trades = run(longs_only, adx_min)
        m = metrics(trades, label)
        m['trades_raw'] = trades
        results.append(m)
        print(f" {m['trades']} trades  PF={m['pf']}  ret={m['return_pct']:+.1f}%")

    # ── Summary table ──────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  RESULTADOS EXP_A — ETH 730d")
    print(f"{'='*80}")
    print(f"  {'Variante':<35} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7} {'Fees':>8}  Veredicto")
    print(f"  {'-'*80}")
    for m in results:
        passes = m['trades'] >= MIN_TRADES_THRESHOLD and m['pf'] >= PF_THRESHOLD
        print(f"  {m['label']:<35} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}% ${m['fees']:>7.2f}  {VERDICT[passes]}")

    # ── Long vs Short split ───────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  LONGS vs SHORTS")
    print(f"  {'Variante':<35} {'Longs':>6} {'L_PF':>7} {'Shorts':>7} {'S_PF':>7}")
    print(f"  {'-'*60}")
    for m in results:
        if m['trades'] > 0:
            print(f"  {m['label']:<35} {m['longs']:>6} {m['long_pf']:>7.3f} {m['shorts']:>7} {m['short_pf']:>7.3f}")

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

    # ── Final verdict ─────────────────────────────────────────────────────────
    any_pass = any(m['trades'] >= MIN_TRADES_THRESHOLD and m['pf'] >= PF_THRESHOLD for m in results)
    print(f"\n{'='*80}")
    if any_pass:
        print(f"  VEREDICTO FINAL: ✅ ETH TIENE EDGE — usar configuración '{best['label']}'")
        print(f"  Reemplazar EXP016A en producción con esta variante.")
    else:
        print(f"  VEREDICTO FINAL: ❌ ETH SIN EDGE — ninguna variante supera PF={PF_THRESHOLD}")
        print(f"  Recomendación: DESACTIVAR ETH en producción hasta nuevo diseño.")
    print(f"{'='*80}\n")
