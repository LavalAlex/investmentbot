"""
Breakout diario — ETH 5 años, enfoque en vol≥1.5×

Pregunta: ¿Las configs con vol≥1.5× que pasaron OOS en ETH también tienen
un IS sólido en 5 años? La sesión anterior solo testó ETH con vol≥1.0× en IS.

Variantes testeadas:
  n_days: 10, 15, 20, 25, 30
  vol_ratio: 1.0, 1.5, 2.0 (para ver el impacto del filtro de volumen)
  atr_mult=1.5, rr=2 fijos (mismos parámetros que BTC ganador)

Criterio IS: PF≥1.3, MaxDD<25%, trades≥30 en 5 años.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

PF_THRESHOLD = 1.3
MIN_TRADES   = 30
MAX_DD_LIMIT = 25.0

PATH_1H = 'data/ETHUSDT_1h_last_5y.csv'

ATR_MULT = 1.5
RR       = 2.0


def build_daily(path_1h: str) -> pd.DataFrame:
    df = pd.read_csv(path_1h)
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df = df.set_index('open_time').sort_index()
    daily = df.resample('1D').agg(
        open=('open', 'first'), high=('high', 'max'),
        low=('low', 'min'), close=('close', 'last'), volume=('volume', 'sum'),
    ).dropna()
    tr = pd.concat([
        daily['high'] - daily['low'],
        (daily['high'] - daily['close'].shift(1)).abs(),
        (daily['low']  - daily['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    daily['atr14'] = tr.ewm(com=13, min_periods=14, adjust=False).mean()
    daily['vol20']  = daily['volume'].rolling(20, min_periods=20).mean()
    return daily.reset_index()


def run(daily: pd.DataFrame, n_days: int, vol_ratio: float) -> list:
    equity, position, trades = INITIAL_CAPITAL, None, []
    daily = daily.copy()
    daily['nd_high'] = daily['close'].shift(1).rolling(n_days, min_periods=n_days).max()

    for i in range(len(daily)):
        row = daily.iloc[i]
        if pd.isna(row.get('atr14')) or pd.isna(row.get('nd_high')):
            continue

        if position is not None:
            hit_sl = row['low'] <= position['sl']
            hit_tp = row['high'] >= position['tp']
            if hit_sl or hit_tp:
                if hit_tp and hit_sl:
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
                    'entry': position['entry'], 'exit': exit_price,
                    'reason': reason,
                    'gross_pnl': round(gross, 4), 'fee_usd': round(fee, 4),
                    'pnl': round(net_pnl, 4), 'equity': round(equity, 4),
                })
                position = None
            else:
                continue

        close = row['close']
        if close <= row['nd_high']:
            continue
        vol20 = row.get('vol20')
        if not pd.isna(vol20) and vol20 > 0 and row['volume'] < vol_ratio * vol20:
            continue

        atr  = row['atr14']
        sl   = close - ATR_MULT * atr
        risk = close - sl
        if risk <= 0:
            continue
        tp = close + RR * risk

        position = {
            'open_time': row['open_time'], 'entry': close,
            'sl': sl, 'tp': tp,
            'qty': equity * RISK_PCT / risk,
        }
    return trades


def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0.0, 'return_pct': 0.0,
                'max_dd': 0.0, 'win_rate': 0.0, 'fees': 0.0, 'passes': False}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp, gl = wins['pnl'].sum(), abs(loss['pnl'].sum())
    pf = round(gp / gl, 3) if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    passes = len(df) >= MIN_TRADES and pf >= PF_THRESHOLD and max_dd < MAX_DD_LIMIT
    return {
        'label': label, 'trades': len(df),
        'win_rate': round(len(wins) / len(df) * 100, 1),
        'pf': pf,
        'return_pct': round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd': round(max_dd, 2),
        'fees': round(df['fee_usd'].sum(), 2),
        'passes': passes,
    }


if __name__ == '__main__':
    print("\nBREAKOUT ETH 5y — grid vol × n_days | ATR×1.5, RR=2 | fees 0.05%")
    print(f"Criterio IS: PF≥{PF_THRESHOLD}, MaxDD<{MAX_DD_LIMIT}%, trades≥{MIN_TRADES}\n")

    daily = build_daily(PATH_1H)
    print(f"  ETH: {len(daily)} días cargados")

    n_days_list  = [10, 15, 20, 25, 30]
    vol_ratios   = [1.0, 1.5, 2.0]

    results = []
    for nd in n_days_list:
        for vr in vol_ratios:
            label = f"ETH {nd}d vol≥{vr}×"
            trades = run(daily, nd, vr)
            m = metrics(trades, label)
            results.append(m)

    print(f"\n{'='*82}")
    print(f"  RESULTADOS ETH 5 años — Breakout diario")
    print(f"{'='*82}")
    print(f"  {'Config':<28} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  IS")
    print(f"  {'-'*78}")
    for m in results:
        v = '✅ KEEP' if m['passes'] else '❌ FAIL'
        print(f"  {m['label']:<28} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  {v}")

    keepers = [m for m in results if m['passes']]
    print(f"\n{'='*82}")
    if keepers:
        print(f"  ✅ {len(keepers)} config(s) pasan IS 5y:")
        for k in keepers:
            print(f"    → {k['label']}  PF={k['pf']}  trades={k['trades']}  "
                  f"ret={k['return_pct']:+.1f}%  MaxDD={k['max_dd']:.1f}%")
        bk = max(keepers, key=lambda x: x['pf'])
        print(f"\n  MEJOR: {bk['label']}  PF={bk['pf']}  trades={bk['trades']}")
    else:
        print(f"  ❌ Ninguna config pasa IS — el ETH breakout no tiene edge robusto")
    print(f"{'='*82}\n")
