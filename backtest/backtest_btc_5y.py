"""
BTC/USDT 5 años — Validación de robustez EXP017-B

Pregunta: ¿El edge de BTC (PF=1.126 en 730d) se sostiene en 5 años completos?

Período: mayo 2021 → mayo 2026 (incluye bear 2022, rebote 2023, bull 2024, corrección 2025)
Config: EXP017-B exacta (longs only, SL≥0.30%, RR=2:1, fees 0.05%/lado)
Datos: BTCUSDT_15m_last_5y.csv + BTCUSDT_1h_last_5y.csv

Variante única: misma config de producción, sin cambios.

Criterio: PF≥1.1 sostenido en 5 años → edge genuino.
          PF<1.0 → el 730d estaba sobreajustado, buscar alternativa.

Regímenes cubiertos:
  Bear 2022:        May 2021 → Nov 2022  (BTC 58k → 16k, -72%)
  Recovery 2023:    Nov 2022 → Nov 2023  (BTC 16k → 37k, +131%)
  Bull 2024:        Nov 2023 → Mar 2025  (BTC 37k → 109k, +195%)
  Corrección 2025:  Mar 2025 → May 2026  (BTC 109k → 95k)
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
MIN_SL_PCT       = 0.0030   # EXP017-B
RR               = 2.0

PATH_1H  = 'data/BTCUSDT_1h_last_5y.csv'
PATH_15M = 'data/BTCUSDT_15m_last_5y.csv'

REGIMES = [
    ('Bear 2022',       '2021-05-30', '2022-11-21'),
    ('Recovery 2023',   '2022-11-21', '2023-11-01'),
    ('Bull 2024',       '2023-11-01', '2025-03-01'),
    ('Correccion 2025', '2025-03-01', '2026-05-30'),
]


def run() -> list:
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
                gross = (exit_price - position['entry']) * qty
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'open_time':  str(position['open_time']),
                    'close_time': str(row['open_time']),
                    'direction':  'long',
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
        }

    return trades


def metrics(trades: list) -> dict:
    if not trades:
        return {}
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
        'trades':     len(df),
        'win_rate':   round(len(wins) / len(df) * 100, 1),
        'pf':         pf,
        'return_pct': round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd':     round(max_dd, 2),
        'fees':       round(df['fee_usd'].sum(), 2),
        'net_pnl':    round(df['pnl'].sum(), 2),
    }


def regime_metrics(trades: list, label: str, start: str, end: str) -> dict:
    df = pd.DataFrame(trades)
    df['open_time'] = pd.to_datetime(df['open_time'])
    mask = (df['open_time'] >= start) & (df['open_time'] < end)
    sub  = df[mask].to_dict('records')
    m    = metrics(sub)
    m['label'] = label
    m['n_days'] = (pd.Timestamp(end) - pd.Timestamp(start)).days
    return m


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


if __name__ == '__main__':
    print("\nBTC 5 AÑOS — EXP017-B (longs only, SL≥0.30%, RR=2:1, fees 0.05%)")
    print("Corriendo backtest completo...\n")
    trades = run()

    m = metrics(trades)
    print(f"{'='*65}")
    print(f"  RESULTADO GLOBAL (5 años)")
    print(f"{'='*65}")
    print(f"  Trades:     {m['trades']}  ({m['trades']/5/365:.2f}/día)")
    print(f"  Win rate:   {m['win_rate']}%")
    print(f"  PF:         {m['pf']}")
    print(f"  Return:     {m['return_pct']:+.1f}%")
    print(f"  MaxDD:      {m['max_dd']:.1f}%")
    print(f"  Fees:       ${m['fees']:,.2f}")
    print(f"  Net PnL:    ${m['net_pnl']:+,.2f}")

    # ── Régimen por régimen ───────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  POR RÉGIMEN DE MERCADO")
    print(f"{'='*65}")
    print(f"  {'Régimen':<22} {'Días':>5} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8}  Veredicto")
    print(f"  {'-'*65}")
    for label, start, end in REGIMES:
        rm = regime_metrics(trades, label, start, end)
        if not rm.get('trades'):
            print(f"  {label:<22} {rm.get('n_days',0):>5} {'0':>5} {'—':>6} {'—':>7} {'—':>8}")
            continue
        verdict = '✅' if rm['pf'] >= 1.0 else '❌'
        print(f"  {label:<22} {rm['n_days']:>5} {rm['trades']:>5} "
              f"{rm['win_rate']:>5.1f}% {rm['pf']:>7.3f} {rm['return_pct']:>+7.1f}%  {verdict}")

    # ── Breakdown mensual completo ─────────────────────────────────────────────
    mb = monthly_breakdown(trades)
    print(f"\n{'='*65}")
    print(f"  BREAKDOWN MENSUAL (5 años)")
    print(f"{'='*65}")
    print(f"  {'Mes':<10} {'N':>4} {'WR':>6} {'PF':>7} {'PnL':>10}")
    print(f"  {'-'*42}")
    profitable = 0
    for _, row in mb.iterrows():
        flag = '✓' if row['pf'] >= 1.0 else '✗'
        if row['pf'] >= 1.0:
            profitable += 1
        print(f"  {row['month']:<10} {row['n']:>4} {row['wr']:>5.1f}% {row['pf']:>7.3f} ${row['pnl']:>+9.2f}  {flag}")
    total_months = len(mb)
    print(f"\n  Meses rentables: {profitable}/{total_months} ({profitable/total_months*100:.0f}%)")

    # ── Veredicto final ───────────────────────────────────────────────────────
    pf_ok    = m['pf'] >= 1.1
    dd_ok    = m['max_dd'] < 30
    trades_ok = m['trades'] >= 300
    print(f"\n{'='*65}")
    print(f"  VEREDICTO FINAL")
    print(f"{'='*65}")
    print(f"  PF≥1.1:          {'✅' if pf_ok else '❌'}  {m['pf']}")
    print(f"  MaxDD<30%:       {'✅' if dd_ok else '❌'}  {m['max_dd']:.1f}%")
    print(f"  Trades≥300:      {'✅' if trades_ok else '❌'}  {m['trades']}")
    if pf_ok and dd_ok and trades_ok:
        print(f"\n  ✅ EDGE GENUINO — BTC EXP017-B es robusto en 5 años.")
        print(f"     El PF de 730d no era overfitting.")
        print(f"     Mantener en producción. Escalar capital cuando sea posible.")
    else:
        print(f"\n  ❌ EDGE NO CONFIRMADO — revisar parámetros o estrategia.")
    print(f"{'='*65}\n")
