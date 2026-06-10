"""
EXP_D — Camino A: Daily momentum gate sobre BTC 5 años

Hipótesis: el edge de pullback solo existe cuando BTC está en régimen de
momentum fuerte en timeframe diario. Jul-Sep 2024 fue exactamente ese régimen.
Un gate diario puede aislar esos períodos y filtrar el ruido del resto.

Gates testeados (todos requieren que el día actual cumpla la condición):
  D0 — Baseline EXP017-B sin gate diario (referencia)
  D1 — Precio > SMA200_diario (macro bull trend)
  D2 — SMA20_diario slope > 0%  (momentum positivo en 20d)
  D3 — SMA20_diario slope > 0.15%/día (momentum fuerte)
  D4 — D1 + D2 combinados
  D5 — D1 + D3 combinados (el más restrictivo)

Datos: BTCUSDT_1h_last_5y.csv + BTCUSDT_15m_last_5y.csv
Config: EXP017-B (longs only, SL≥0.30%, RR=2:1, fees 0.05%)

Criterio KEEP: PF≥1.2 en 5 años, MaxDD<25%, trades≥200.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
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

PF_THRESHOLD     = 1.2
MIN_TRADES       = 200


def build_daily(df_1h_raw: pd.DataFrame) -> pd.DataFrame:
    """Resample 1h → daily OHLCV and compute SMA200 + SMA20 slope."""
    df = df_1h_raw.copy()
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df = df.set_index('open_time')

    daily = df['close'].resample('1D').last().dropna().to_frame()
    daily['sma200'] = daily['close'].rolling(200, min_periods=200).mean()
    daily['sma20']  = daily['close'].rolling(20,  min_periods=20).mean()
    # slope in % per day
    daily['sma20_slope_pct'] = daily['sma20'].pct_change() * 100
    # available the next day's open (close of day D is known after day D ends)
    daily['date'] = daily.index.normalize()
    daily = daily.reset_index()
    daily['available_date'] = daily['open_time'].dt.normalize() + pd.Timedelta(days=1)
    return daily[['available_date', 'sma200', 'sma20', 'sma20_slope_pct']].dropna()


def align_daily_to_15m(df_15m: pd.DataFrame, df_daily: pd.DataFrame) -> pd.DataFrame:
    df = df_15m.copy()
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df_daily = df_daily.copy()
    df_daily['available_date'] = pd.to_datetime(df_daily['available_date'], utc=True)
    merged = pd.merge_asof(
        df.sort_values('open_time'),
        df_daily.sort_values('available_date'),
        left_on='open_time',
        right_on='available_date',
        direction='backward',
    )
    return merged


def run(df: pd.DataFrame, use_sma200: bool, sma20_slope_min: float | None) -> list:
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
                    'open_time': str(position['open_time']),
                    'direction': 'long',
                    'entry':     position['entry'],
                    'exit':      exit_price,
                    'reason':    reason,
                    'gross_pnl': round(gross, 4),
                    'fee_usd':   round(fee, 4),
                    'pnl':       round(net_pnl, 4),
                    'equity':    round(equity, 4),
                })
                position = None
            continue

        # ── Daily gate ────────────────────────────────────────────────────────
        close   = row['close']
        sma200  = row.get('sma200')
        sma20_slope = row.get('sma20_slope_pct')

        if use_sma200:
            if pd.isna(sma200) or close < sma200:
                continue

        if sma20_slope_min is not None:
            if pd.isna(sma20_slope) or sma20_slope < sma20_slope_min:
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

        entry = close
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
        rows.append({
            'month': str(month), 'n': len(g),
            'wr':    round(len(wins) / len(g) * 100, 1),
            'pf':    round(gp / gl, 3) if gl > 0 else float('inf'),
            'pnl':   round(g['pnl'].sum(), 2),
        })
    return rows


VARIANTS = [
    (False, None,  'D0 — Baseline (sin gate diario)'),
    (True,  None,  'D1 — Precio > SMA200d'),
    (False, 0.0,   'D2 — SMA20d slope > 0%'),
    (False, 0.15,  'D3 — SMA20d slope > 0.15%/día'),
    (True,  0.0,   'D4 — SMA200 + SMA20 slope>0%'),
    (True,  0.15,  'D5 — SMA200 + SMA20 slope>0.15%'),
]


if __name__ == '__main__':
    print("\nEXP_D — BTC 5 años | Daily gate sobre pullback | fees 0.05%")
    print(f"Criterio: PF≥{PF_THRESHOLD}, MaxDD<25%, trades≥{MIN_TRADES}\n")
    print("Cargando datos y construyendo df...", end='', flush=True)

    df_1h_raw, df_15m_raw = load_data(PATH_1H, PATH_15M)
    df_1h   = prepare_1h(df_1h_raw)
    df_15m  = prepare_15m(df_15m_raw)
    df      = align_1h_to_15m(df_15m, df_1h)
    df_daily = build_daily(df_1h_raw)
    df      = align_daily_to_15m(df, df_daily)
    print(f" {len(df):,} filas listas\n")

    results = []
    for use_sma200, slope_min, label in VARIANTS:
        print(f"  {label}...", end='', flush=True)
        trades = run(df, use_sma200, slope_min)
        m = metrics(trades, label)
        results.append(m)
        print(f" {m['trades']} trades  PF={m['pf']}  ret={m['return_pct']:+.1f}%")

    # ── Summary table ──────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  EXP_D — BTC 5 años con daily gate")
    print(f"{'='*80}")
    print(f"  {'Variante':<38} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  Veredicto")
    print(f"  {'-'*78}")
    for m in results:
        passes = m['trades'] >= MIN_TRADES and m['pf'] >= PF_THRESHOLD and m['max_dd'] < 25
        v = '✅ KEEP' if passes else '❌ FAIL'
        print(f"  {m['label']:<38} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  {v}")

    # ── Best variant monthly detail ────────────────────────────────────────────
    keepers = [m for m in results if m['trades'] >= MIN_TRADES and m['pf'] >= PF_THRESHOLD and m['max_dd'] < 25]
    best    = max(results, key=lambda x: x['pf'] if x['trades'] >= MIN_TRADES else 0)

    print(f"\n{'='*80}")
    if keepers:
        best_keep = max(keepers, key=lambda x: x['pf'])
        print(f"  MEJOR KEEPER: {best_keep['label']}")
        print(f"  PF={best_keep['pf']}  trades={best_keep['trades']}  ret={best_keep['return_pct']:+.1f}%  MaxDD={best_keep['max_dd']:.1f}%")
        mb = monthly_breakdown(best_keep['trades_raw'])
        profitable = sum(1 for r in mb if r['pf'] >= 1.0)
        print(f"\n  Breakdown mensual ({profitable}/{len(mb)} meses rentables):")
        print(f"  {'Mes':<10} {'N':>4} {'WR':>6} {'PF':>7} {'PnL':>9}")
        print(f"  {'-'*42}")
        for r in mb:
            flag = '✓' if r['pf'] >= 1.0 else '✗'
            print(f"  {r['month']:<10} {r['n']:>4} {r['wr']:>5.1f}% {r['pf']:>7.3f} ${r['pnl']:>+8.2f}  {flag}")
    else:
        print(f"  MEJOR SIN KEEPER: {best['label']}")
        print(f"  PF={best['pf']}  trades={best['trades']}  ret={best['return_pct']:+.1f}%  MaxDD={best['max_dd']:.1f}%")

    print(f"\n{'='*80}")
    if keepers:
        print(f"  VEREDICTO: ✅ Daily gate funciona — {len(keepers)} variante(s) pasan")
        print(f"  Camino A viable → implementar en producción")
    else:
        pf_best = max(results, key=lambda x: x['pf'])
        print(f"  VEREDICTO: ❌ Daily gate no alcanza PF≥{PF_THRESHOLD} con ≥{MIN_TRADES} trades")
        print(f"  Mejor: PF={pf_best['pf']} ({pf_best['trades']} trades) — {pf_best['label']}")
    print(f"{'='*80}\n")
