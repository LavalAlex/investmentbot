"""
TIME-B Filter Test — ETH/USDT 730d

Pregunta: ¿El filtro TIME-B (07:00-21:00 UTC) mejora o perjudica la performance de ETH?

Config base: EXP016A (longs+shorts, SL≥0.50%, RR=2:1, fees 0.05%/lado)
Datos: ETHUSDT_15m_last_730d.csv + ETHUSDT_1h_last_740d.csv

Variantes:
  A — Sin filtro horario (baseline, igual que el backtest original)
  B — TIME-B actual: 07:00–21:00 UTC (producción)
  C — Extendido:     06:00–22:00 UTC
  D — Solo noche:    00:00–07:00 + 21:00–24:00 (las horas bloqueadas en B)

Criterio: KEEP si PF > 1.0 con fees, al menos 60 trades en 730d.
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
LONGS_ONLY       = False

PATH_1H  = 'data/ETHUSDT_1h_last_740d.csv'
PATH_15M = 'data/ETHUSDT_15m_last_730d.csv'


def in_window(open_time, start_h: int, end_h: int) -> bool:
    """True si la hora UTC de open_time está en [start_h, end_h)."""
    if start_h is None:
        return True
    ts = pd.Timestamp(open_time)
    h = ts.tz_convert('UTC').hour if ts.tzinfo else ts.hour
    if start_h < end_h:
        return start_h <= h < end_h
    else:   # ventana que cruza medianoche, ej. 21–07
        return h >= start_h or h < end_h


def run(window_start, window_end, label: str) -> dict:
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
                    'hour_utc':   pd.Timestamp(position['open_time']).tz_convert('UTC').hour
                                  if pd.Timestamp(position['open_time']).tzinfo
                                  else pd.Timestamp(position['open_time']).hour,
                })
                position = None
            continue

        # TIME-B gate
        if not in_window(row['open_time'], window_start, window_end):
            continue

        trend = get_trend(row)
        if trend is None: continue
        if not is_trend_strong(row): continue
        if not is_pullback_quality(row, trend): continue
        if not is_entry_trigger(row, trend): continue
        if not is_candle_quality(row, trend): continue
        if not is_range_sufficient(row): continue
        if not is_market_efficient(row): continue

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']
        if direction == 'long':
            sl = row['low']; risk = entry - sl
            if risk <= 0: continue
            tp = entry + RR * risk
        else:
            sl = row['high']; risk = sl - entry
            if risk <= 0: continue
            tp = entry - RR * risk

        sl_pct = risk / entry
        if sl_pct < MIN_SL_PCT: continue

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       risk_usd / risk,
        }

    return _metrics(trades, label)


def _metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum()
    gl   = abs(loss['pnl'].sum())
    pf   = round(gp / gl, 3) if gl > 0 else float('inf')

    # Hour distribution
    hour_dist = df.groupby('hour_utc')['pnl'].agg(['count', 'sum']).reset_index()

    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p
        peak   = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)

    return {
        'label':       label,
        'trades':      len(df),
        'wins':        len(wins),
        'losses':      len(loss),
        'win_rate':    round(len(wins) / len(df) * 100, 1),
        'pf':          pf,
        'return_pct':  round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd':      round(max_dd, 2),
        'net_pnl':     round(df['pnl'].sum(), 2),
        'fees':        round(df['fee_usd'].sum(), 2),
        'tp_exits':    len(df[df['reason'] == 'TP']),
        'sl_exits':    len(df[df['reason'] == 'SL']),
        'hour_dist':   hour_dist,
        'longs':       len(df[df['direction'] == 'long']),
        'shorts':      len(df[df['direction'] == 'short']),
    }


def monthly_pf(trades_raw: list) -> list:
    if not trades_raw:
        return []
    df = pd.DataFrame(trades_raw)
    df['month'] = pd.to_datetime(df['close_time']).dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        wins = g[g['pnl'] > 0]
        gl   = abs(g[g['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        rows.append({
            'month': str(month),
            'n':     len(g),
            'pf':    round(gp / gl, 3) if gl > 0 else float('inf'),
            'pnl':   round(g['pnl'].sum(), 2),
        })
    return rows


def print_report(results: list) -> None:
    print(f"\n{'='*70}")
    print(f"  TIME-B TEST — ETH/USDT 730d  |  EXP016A  |  fees 0.05%/lado")
    print(f"{'='*70}")
    print(f"  {'Variante':<30} {'Trades':>7} {'WR':>6} {'PF':>7} {'Return':>8} {'MaxDD':>7} {'Fees':>8}")
    print(f"  {'-'*70}")
    for r in results:
        if r['trades'] == 0:
            print(f"  {r['label']:<30} {'0':>7} {'—':>6} {'—':>7} {'—':>8} {'—':>7} {'—':>8}")
        else:
            print(f"  {r['label']:<30} {r['trades']:>7} {r['win_rate']:>5.1f}% {r['pf']:>7.3f} "
                  f"{r['return_pct']:>+7.1f}% {r['max_dd']:>6.1f}% ${r['fees']:>7.2f}")

    print(f"\n{'='*70}")
    print(f"  LONGS vs SHORTS por variante")
    print(f"  {'Variante':<30} {'Longs':>8} {'Shorts':>8}")
    print(f"  {'-'*50}")
    for r in results:
        if r['trades'] > 0:
            print(f"  {r['label']:<30} {r['longs']:>8} {r['shorts']:>8}")

    # Baseline para comparar
    baseline = next((r for r in results if 'Sin filtro' in r['label']), None)
    if baseline and baseline['trades'] > 0:
        print(f"\n{'='*70}")
        print(f"  DELTA vs BASELINE (sin filtro horario)")
        print(f"  {'Variante':<30} {'Δ trades':>9} {'Δ PF':>9} {'Δ return':>10}")
        print(f"  {'-'*60}")
        for r in results:
            if r == baseline or r['trades'] == 0:
                continue
            dt  = r['trades'] - baseline['trades']
            dpf = r['pf'] - baseline['pf']
            dret = r['return_pct'] - baseline['return_pct']
            print(f"  {r['label']:<30} {dt:>+9} {dpf:>+9.3f} {dret:>+9.1f}%")

    print(f"\n{'='*70}")
    print(f"  DISTRIBUCIÓN HORARIA (Baseline sin filtro) — trades y PnL por hora UTC")
    base = next((r for r in results if 'Sin filtro' in r['label']), None)
    if base and base['trades'] > 0:
        hd = base['hour_dist']
        for _, row in hd.iterrows():
            bar = '█' * int(row['count'])
            print(f"  {int(row['hour_utc']):02d}h  {int(row['count']):>4} trades  ${row['sum']:>+8.2f}  {bar}")
    print(f"{'='*70}\n")


VARIANTS = [
    (None,  None, 'Sin filtro (baseline)'),
    (7,     21,   'TIME-B actual (07–21 UTC)'),
    (6,     22,   'TIME-B extendido (06–22 UTC)'),
    (5,     23,   'TIME-B amplio (05–23 UTC)'),
]

if __name__ == '__main__':
    print("Corriendo variantes TIME-B sobre ETH 730d...")
    results = []
    for start_h, end_h, label in VARIANTS:
        print(f"  {label}...", end='', flush=True)
        r = run(start_h, end_h, label)
        print(f" {r['trades']} trades  PF={r.get('pf','—')}")
        results.append(r)
    print_report(results)
