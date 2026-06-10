"""
Camino 3 — Equity drawdown pause sobre pullback EXP017-B (BTC 5 años)

Hipótesis: el sistema no necesita predecir el régimen — necesita SOBREVIVIR
los malos períodos sin destruir el capital. Si el equity cae X% desde el
pico mensual (o semanal), pausar nuevas entradas hasta que recupere.

Esto no mejora el edge — reduce las pérdidas en los períodos malos.
Si funciona: la curva de equity es más suave con el mismo PF o mejor.

Lógica de pausa:
  - Computar el peak de equity del período actual (mes o semana)
  - Si equity < peak × (1 − threshold) → no abrir nuevas posiciones
  - Las posiciones abiertas siguen hasta su SL/TP normal

Variantes:
  H0 — Sin pausa (baseline)
  H1 — Pausa mensual si DD>5%
  H2 — Pausa mensual si DD>3%
  H3 — Pausa mensual si DD>7%
  H4 — Pausa semanal  si DD>5%
  H5 — Pausa mensual si DD>5% + máx 3 SL consecutivos → pausa 2 semanas

Config base: EXP017-B (longs only, SL≥0.30%, RR=2:1, fees 0.05%/lado)
Datos: BTCUSDT_15m + BTCUSDT_1h (5 años)

Criterio KEEP: PF≥1.1, MaxDD<20%, retorno positivo en 5 años.
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
MIN_SL_PCT       = 0.0030
RR               = 2.0

PATH_1H  = 'data/BTCUSDT_1h_last_5y.csv'
PATH_15M = 'data/BTCUSDT_15m_last_5y.csv'

PF_THRESHOLD = 1.1
MAX_DD_LIMIT = 20.0


def run(df: pd.DataFrame, pause_period: str, dd_threshold: float,
        consec_sl_limit: int) -> list:
    """
    pause_period: 'month' | 'week'
    dd_threshold: float (e.g. 0.05 = 5%)
    consec_sl_limit: max consecutive SL before extra pause (0 = disabled)
    """
    equity      = INITIAL_CAPITAL
    position    = None
    trades      = []
    period_peak = INITIAL_CAPITAL
    current_period = None
    paused_until   = None   # pd.Timestamp — pause until this bar
    consec_sl      = 0

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        ts = pd.Timestamp(row['open_time'])

        # ── Reset period peak at start of new period ──────────────────────────
        if pause_period == 'month':
            period_key = (ts.year, ts.month)
        else:
            period_key = (ts.isocalendar().year, ts.isocalendar().week)

        if period_key != current_period:
            current_period = period_key
            period_peak    = equity  # reset peak at start of period

        period_peak = max(period_peak, equity)

        # ── Exit check ────────────────────────────────────────────────────────
        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty   = position['qty']
                gross = (exit_price - position['entry']) * qty
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'open_time': str(position['open_time']),
                    'entry':     position['entry'],
                    'exit':      exit_price,
                    'reason':    reason,
                    'gross_pnl': round(gross, 4),
                    'fee_usd':   round(fee, 4),
                    'pnl':       round(net_pnl, 4),
                    'equity':    round(equity, 4),
                    'paused':    False,
                })
                if reason == 'SL':
                    consec_sl += 1
                    if consec_sl_limit > 0 and consec_sl >= consec_sl_limit:
                        paused_until = ts + pd.Timedelta(weeks=2)
                        consec_sl = 0
                else:
                    consec_sl = 0
                position = None
            continue

        # ── Pause gate ────────────────────────────────────────────────────────
        if paused_until is not None and ts < paused_until:
            continue

        if dd_threshold > 0 and period_peak > 0:
            current_dd = (period_peak - equity) / period_peak
            if current_dd > dd_threshold:
                continue

        # ── Pullback filters ──────────────────────────────────────────────────
        trend = get_trend(row)
        if trend is None or trend != 'up': continue
        if not is_trend_strong(row): continue
        if not is_pullback_quality(row, trend): continue
        if not is_entry_trigger(row, trend): continue
        if not is_candle_quality(row, trend): continue
        if not is_range_sufficient(row): continue
        if not is_market_efficient(row): continue

        entry = row['close']
        sl    = row['low']
        risk  = entry - sl
        if risk <= 0 or risk / entry < MIN_SL_PCT: continue
        tp = entry + RR * risk

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'direction': 'long',
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       risk_usd / risk,
        }

    return trades


def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0.0, 'return_pct': 0.0,
                'max_dd': 0.0, 'win_rate': 0.0, 'fees': 0.0, 'trades_raw': []}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum()
    gl   = abs(loss['pnl'].sum())
    pf   = round(gp / gl, 3) if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
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


def monthly_breakdown(trades: list) -> list:
    df = pd.DataFrame(trades)
    df['month'] = pd.to_datetime(df['open_time']).dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        wins = g[g['pnl'] > 0]
        gl   = abs(g[g['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        rows.append({'month': str(month), 'n': len(g),
                     'wr':  round(len(wins)/len(g)*100, 1),
                     'pf':  round(gp/gl, 3) if gl > 0 else float('inf'),
                     'pnl': round(g['pnl'].sum(), 2)})
    return rows


VARIANTS = [
    {'label': 'H0 — Sin pausa (baseline)',             'period': 'month', 'dd': 0.0,  'consec': 0},
    {'label': 'H1 — Pausa mensual si DD>5%',           'period': 'month', 'dd': 0.05, 'consec': 0},
    {'label': 'H2 — Pausa mensual si DD>3%',           'period': 'month', 'dd': 0.03, 'consec': 0},
    {'label': 'H3 — Pausa mensual si DD>7%',           'period': 'month', 'dd': 0.07, 'consec': 0},
    {'label': 'H4 — Pausa semanal si DD>5%',           'period': 'week',  'dd': 0.05, 'consec': 0},
    {'label': 'H5 — DD>5% + 3 SL consec→pausa 2sem',  'period': 'month', 'dd': 0.05, 'consec': 3},
]


if __name__ == '__main__':
    print("\nCAMINO 3 — Equity drawdown pause | BTC 5 años | EXP017-B base")
    print(f"Criterio: PF≥{PF_THRESHOLD}, MaxDD<{MAX_DD_LIMIT}%, retorno positivo\n")
    print("Cargando datos...", end='', flush=True)

    df_1h_raw, df_15m_raw = load_data(PATH_1H, PATH_15M)
    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)
    print(f" {len(df):,} filas\n")

    results = []
    for v in VARIANTS:
        print(f"  {v['label']}...", end='', flush=True)
        trades = run(df, v['period'], v['dd'], v['consec'])
        m = metrics(trades, v['label'])
        results.append(m)
        print(f" {m['trades']} trades  PF={m['pf']}  ret={m['return_pct']:+.1f}%  MaxDD={m['max_dd']:.1f}%")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*82}")
    print(f"  RESULTADOS CAMINO 3 — Equity pause | BTC 5 años")
    print(f"{'='*82}")
    print(f"  {'Variante':<42} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  Veredicto")
    print(f"  {'-'*80}")
    for m in results:
        passes = m['pf'] >= PF_THRESHOLD and m['max_dd'] < MAX_DD_LIMIT and m['return_pct'] > 0
        v = '✅ KEEP' if passes else '❌ FAIL'
        print(f"  {m['label']:<42} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  {v}")

    # ── Delta vs baseline ────────────────────────────────────────────────────
    base = results[0]
    print(f"\n{'='*82}")
    print(f"  DELTA vs BASELINE (H0 sin pausa)")
    print(f"  {'Variante':<42} {'Δ trades':>9} {'Δ PF':>8} {'Δ MaxDD':>9} {'Δ ret':>8}")
    print(f"  {'-'*75}")
    for m in results[1:]:
        dt  = m['trades'] - base['trades']
        dpf = round(m['pf'] - base['pf'], 3)
        ddd = round(m['max_dd'] - base['max_dd'], 1)
        dr  = round(m['return_pct'] - base['return_pct'], 1)
        print(f"  {m['label']:<42} {dt:>+9} {dpf:>+8.3f} {ddd:>+8.1f}% {dr:>+7.1f}%")

    # ── Best keeper monthly detail ────────────────────────────────────────────
    keepers = [m for m in results
               if m['pf'] >= PF_THRESHOLD and m['max_dd'] < MAX_DD_LIMIT and m['return_pct'] > 0]

    print(f"\n{'='*82}")
    if keepers:
        bk = max(keepers, key=lambda x: x['pf'])
        mb = monthly_breakdown(bk['trades_raw'])
        prof = sum(1 for r in mb if r['pf'] >= 1.0)
        print(f"  MEJOR KEEPER: {bk['label']}")
        print(f"  PF={bk['pf']}  trades={bk['trades']}  ret={bk['return_pct']:+.1f}%  MaxDD={bk['max_dd']:.1f}%")
        print(f"  Meses rentables: {prof}/{len(mb)} ({prof/len(mb)*100:.0f}%)")
        print(f"\n  {'Mes':<10} {'N':>4} {'WR':>6} {'PF':>7} {'PnL':>9}")
        print(f"  {'-'*40}")
        for r in mb:
            flag = '✓' if r['pf'] >= 1.0 else '✗'
            print(f"  {r['month']:<10} {r['n']:>4} {r['wr']:>5.1f}% {r['pf']:>7.3f} ${r['pnl']:>+8.2f}  {flag}")
        print(f"\n  VEREDICTO: ✅ Equity pause mejora el sistema — Camino 3 viable")
    else:
        best = max(results, key=lambda x: x['pf'])
        print(f"  MEJOR (sin keeper): {best['label']}")
        print(f"  PF={best['pf']}  MaxDD={best['max_dd']:.1f}%  ret={best['return_pct']:+.1f}%")
        print(f"\n  VEREDICTO: ❌ Equity pause no alcanza criterios de KEEP")
    print(f"{'='*82}\n")
