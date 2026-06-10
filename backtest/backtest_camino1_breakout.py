"""
Camino 1 — Breakout en timeframe diario (BTC + ETH, 5 años)

Hipótesis: en lugar de esperar un pullback al EMA20 en 15m (señal de ruido),
entrar cuando el precio rompe el máximo de N días con volumen. El breakout
es el momento donde el momentum se autoconfirma en timeframe relevante.

Señal de entrada (1D):
  - Close del día > max(close, N días anteriores)  → "nuevo N-day high"
  - Volumen del día ≥ vol_ratio × media(20 días de volumen)
  - Posición long — trend following puro

SL: close de la vela de entrada − ATR(14) × atr_mult
TP: entry + RR × risk
Sin filtros adicionales de pullback/EMA — limpio.

Variantes:
  F0 — breakout 20d, vol≥1.0×, ATR×1.5, RR=2:1
  F1 — breakout 20d, vol≥1.5×, ATR×1.5, RR=2:1  (más volumen)
  F2 — breakout 10d, vol≥1.0×, ATR×1.5, RR=2:1  (más señales)
  F3 — breakout 20d, vol≥1.0×, ATR×2.0, RR=2:1  (SL más amplio)
  F4 — breakout 20d, vol≥1.0×, ATR×1.5, RR=3:1  (TP más lejos)
  F5 — breakout 50d, vol≥1.0×, ATR×1.5, RR=2:1  (más selectivo)

Assets: BTC y ETH — datos 1h resampleados a 1D (5 años)
Criterio KEEP: PF≥1.3, MaxDD<25%, trades≥50 en 5 años.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

PF_THRESHOLD = 1.3
MIN_TRADES   = 50
MAX_DD_LIMIT = 25.0

ASSETS = {
    'BTC': ('data/BTCUSDT_1h_last_5y.csv', 'data/BTCUSDT_15m_last_5y.csv'),
    'ETH': ('data/ETHUSDT_1h_last_5y.csv', 'data/ETHUSDT_15m_last_5y.csv'),
}

VARIANTS = [
    {'label': 'F0 — 20d, vol≥1.0×, ATR×1.5, RR=2', 'n_days': 20, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
    {'label': 'F1 — 20d, vol≥1.5×, ATR×1.5, RR=2', 'n_days': 20, 'vol_ratio': 1.5, 'atr_mult': 1.5, 'rr': 2.0},
    {'label': 'F2 — 10d, vol≥1.0×, ATR×1.5, RR=2', 'n_days': 10, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
    {'label': 'F3 — 20d, vol≥1.0×, ATR×2.0, RR=2', 'n_days': 20, 'vol_ratio': 1.0, 'atr_mult': 2.0, 'rr': 2.0},
    {'label': 'F4 — 20d, vol≥1.0×, ATR×1.5, RR=3', 'n_days': 20, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 3.0},
    {'label': 'F5 — 50d, vol≥1.0×, ATR×1.5, RR=2', 'n_days': 50, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
]


def build_daily(path_1h: str) -> pd.DataFrame:
    """Resample 1h → daily OHLCV + ATR14."""
    df = pd.read_csv(path_1h)
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df = df.set_index('open_time').sort_index()

    daily = df.resample('1D').agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
    ).dropna()

    # ATR14 on daily
    tr = pd.concat([
        daily['high'] - daily['low'],
        (daily['high'] - daily['close'].shift(1)).abs(),
        (daily['low']  - daily['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    daily['atr14'] = tr.ewm(com=13, min_periods=14, adjust=False).mean()
    daily['vol20']  = daily['volume'].rolling(20, min_periods=20).mean()

    return daily.reset_index()


def run(daily: pd.DataFrame, n_days: int, vol_ratio: float,
        atr_mult: float, rr: float) -> list:
    equity, position, trades = INITIAL_CAPITAL, None, []

    # Pre-compute rolling N-day high (excluding current day → shift(1))
    daily = daily.copy()
    daily['nd_high'] = daily['close'].shift(1).rolling(n_days, min_periods=n_days).max()

    for i in range(len(daily)):
        row = daily.iloc[i]
        if pd.isna(row.get('atr14')) or pd.isna(row.get('nd_high')):
            continue

        if position is not None:
            # Check exit: SL or TP hit during the day
            hit_sl = row['low'] <= position['sl']
            hit_tp = row['high'] >= position['tp']

            if hit_sl or hit_tp:
                if hit_tp and hit_sl:
                    # Both hit — assume TP first (optimistic but standard)
                    exit_price, reason = position['tp'], 'TP'
                elif hit_tp:
                    exit_price, reason = position['tp'], 'TP'
                else:
                    exit_price, reason = position['sl'], 'SL'

                gross   = (exit_price - position['entry']) * position['qty']
                fee     = (position['entry'] + exit_price) * position['qty'] * FEE_PER_SIDE_PCT
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
                })
                position = None
            else:
                continue

        # Entry: breakout of N-day high + volume
        close  = row['close']
        nd_high = row['nd_high']
        vol20   = row.get('vol20')
        vol     = row.get('volume')

        if close <= nd_high:
            continue
        if not pd.isna(vol20) and vol20 > 0 and vol < vol_ratio * vol20:
            continue

        atr  = row['atr14']
        sl   = close - atr_mult * atr
        risk = close - sl
        if risk <= 0:
            continue
        tp = close + rr * risk

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'entry':     close,
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


def print_results(asset: str, results: list) -> bool:
    print(f"\n{'='*80}")
    print(f"  CAMINO 1 — {asset} 5 años | Breakout diario")
    print(f"  Criterio: PF≥{PF_THRESHOLD}, MaxDD<{MAX_DD_LIMIT}%, trades≥{MIN_TRADES}")
    print(f"{'='*80}")
    print(f"  {'Variante':<40} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  Veredicto")
    print(f"  {'-'*78}")
    for m in results:
        passes = m['trades'] >= MIN_TRADES and m['pf'] >= PF_THRESHOLD and m['max_dd'] < MAX_DD_LIMIT
        v = '✅ KEEP' if passes else '❌ FAIL'
        print(f"  {m['label']:<40} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  {v}")

    keepers = [m for m in results
               if m['trades'] >= MIN_TRADES and m['pf'] >= PF_THRESHOLD and m['max_dd'] < MAX_DD_LIMIT]
    if keepers:
        bk = max(keepers, key=lambda x: x['pf'])
        mb = monthly_breakdown(bk['trades_raw'])
        prof = sum(1 for r in mb if r['pf'] >= 1.0)
        print(f"\n  MEJOR KEEPER: {bk['label']}")
        print(f"  PF={bk['pf']}  trades={bk['trades']}  ret={bk['return_pct']:+.1f}%  MaxDD={bk['max_dd']:.1f}%")
        print(f"  Breakdown mensual ({prof}/{len(mb)} meses rentables):")
        print(f"  {'Mes':<10} {'N':>4} {'WR':>6} {'PF':>7} {'PnL':>9}")
        print(f"  {'-'*40}")
        for r in mb:
            flag = '✓' if r['pf'] >= 1.0 else '✗'
            print(f"  {r['month']:<10} {r['n']:>4} {r['wr']:>5.1f}% {r['pf']:>7.3f} ${r['pnl']:>+8.2f}  {flag}")

    any_pass = bool(keepers)
    print(f"\n  VEREDICTO {asset}: {'✅ KEEP' if any_pass else '❌ FAIL'}")
    return any_pass


if __name__ == '__main__':
    print("\nCAMINO 1 — Breakout diario | BTC + ETH 5 años | fees 0.05%")
    verdicts = {}
    for asset, (path_1h, _) in ASSETS.items():
        print(f"\n  Construyendo daily {asset}...", end='', flush=True)
        daily = build_daily(path_1h)
        print(f" {len(daily)} días")
        results = []
        for v in VARIANTS:
            print(f"    {v['label']}...", end='', flush=True)
            trades = run(daily, v['n_days'], v['vol_ratio'], v['atr_mult'], v['rr'])
            m = metrics(trades, v['label'])
            results.append(m)
            print(f" {m['trades']} trades  PF={m['pf']}  ret={m['return_pct']:+.1f}%")
        verdicts[asset] = print_results(asset, results)

    print(f"\n{'='*80}")
    print(f"  RESUMEN CAMINO 1")
    for asset, passes in verdicts.items():
        print(f"  {asset}: {'✅ VIABLE' if passes else '❌ DESCARTADO'}")
    print(f"{'='*80}\n")
