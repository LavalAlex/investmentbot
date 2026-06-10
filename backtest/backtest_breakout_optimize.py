"""
Breakout diario — Optimización de parámetros (BTC 5 años)

Problema: F2 (10d, vol≥1.0×) da PF=1.475 con 69 trades.
          F1 (20d, vol≥1.5×) da PF=2.204 con solo 37 trades.
Objetivo: encontrar el punto medio óptimo en el espacio (n_days × vol_ratio).

Grid search:
  n_days:    [10, 15, 20, 25, 30]
  vol_ratio: [1.0, 1.1, 1.2, 1.3, 1.5, 2.0]
  (ATR×1.5, RR=2 fijos — mejor combo en exploración anterior)

Para cada punto del grid: reportar PF, trades, MaxDD, return.
Identificar frontera Pareto: máximo PF dado mínimo de trades.

Criterio: trades≥30 (mínimo estadístico para 5 años), PF≥1.3, MaxDD<20%.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005
ATR_MULT         = 1.5
RR               = 2.0

PATH_1H  = 'data/BTCUSDT_1h_last_5y.csv'

MIN_TRADES   = 30
PF_THRESHOLD = 1.3
MAX_DD_LIMIT = 20.0

N_DAYS_GRID    = [10, 15, 20, 25, 30]
VOL_RATIO_GRID = [1.0, 1.1, 1.2, 1.3, 1.5, 2.0]


def build_daily(path_1h: str) -> pd.DataFrame:
    df = pd.read_csv(path_1h)
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df = df.set_index('open_time').sort_index()
    daily = df.resample('1D').agg(
        open=('open','first'), high=('high','max'),
        low=('low','min'), close=('close','last'), volume=('volume','sum'),
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
                    'pnl': round(net_pnl, 4), 'equity': round(equity, 4),
                    'fee_usd': round(fee, 4),
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
            'sl': sl, 'tp': tp, 'qty': equity * RISK_PCT / risk,
        }
    return trades


def metrics(trades: list) -> dict:
    if not trades:
        return {'trades': 0, 'pf': 0.0, 'return_pct': 0.0, 'max_dd': 0.0, 'win_rate': 0.0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp, gl = wins['pnl'].sum(), abs(loss['pnl'].sum())
    pf = round(gp / gl, 3) if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    return {
        'trades': len(df),
        'win_rate': round(len(wins)/len(df)*100, 1),
        'pf': pf,
        'return_pct': round((df['equity'].iloc[-1]-INITIAL_CAPITAL)/INITIAL_CAPITAL*100, 2),
        'max_dd': round(max_dd, 2),
    }


if __name__ == '__main__':
    print("\nBREAKOUT OPTIMIZE — Grid search BTC 5 años | ATR×1.5, RR=2")
    print(f"Criterio: trades≥{MIN_TRADES}, PF≥{PF_THRESHOLD}, MaxDD<{MAX_DD_LIMIT}%\n")
    print("Construyendo daily...", end='', flush=True)
    daily = build_daily(PATH_1H)
    print(f" {len(daily)} días\n")

    grid_results = []
    total = len(N_DAYS_GRID) * len(VOL_RATIO_GRID)
    done = 0
    for n in N_DAYS_GRID:
        for vr in VOL_RATIO_GRID:
            trades = run(daily, n, vr)
            m = metrics(trades)
            m['n_days'] = n
            m['vol_ratio'] = vr
            m['passes'] = (m['trades'] >= MIN_TRADES and m['pf'] >= PF_THRESHOLD
                           and m['max_dd'] < MAX_DD_LIMIT and m['return_pct'] > 0)
            grid_results.append(m)
            done += 1
            print(f"  [{done:2d}/{total}] n={n:2d}d vol≥{vr:.1f}× → "
                  f"{m['trades']:3d} trades  PF={m['pf']:.3f}  WR={m['win_rate']:.1f}%  "
                  f"MaxDD={m['max_dd']:.1f}%  {'✅' if m['passes'] else '❌'}")

    # ── Summary table ──────────────────────────────────────────────────────────
    keepers = [r for r in grid_results if r['passes']]
    print(f"\n{'='*75}")
    print(f"  GRID SEARCH RESULTS — BTC 5y (ATR×1.5, RR=2:1)")
    print(f"  {len(keepers)}/{total} combinaciones pasan los criterios")
    print(f"{'='*75}")

    # Matrix view: n_days vs vol_ratio
    print(f"\n  PF por (n_days × vol_ratio)  [✅ = keeper]")
    header = f"  {'n\\vol':>6}" + "".join(f"  {vr:.1f}×" for vr in VOL_RATIO_GRID)
    print(header)
    print(f"  {'-'*65}")
    for n in N_DAYS_GRID:
        row_str = f"  {n:4d}d  "
        for vr in VOL_RATIO_GRID:
            r = next(x for x in grid_results if x['n_days'] == n and x['vol_ratio'] == vr)
            mark = '✅' if r['passes'] else '  '
            row_str += f" {r['pf']:5.3f}{mark}"
        print(row_str)

    print(f"\n  Trades por (n_days × vol_ratio)")
    print(header)
    print(f"  {'-'*65}")
    for n in N_DAYS_GRID:
        row_str = f"  {n:4d}d  "
        for vr in VOL_RATIO_GRID:
            r = next(x for x in grid_results if x['n_days'] == n and x['vol_ratio'] == vr)
            mark = '✅' if r['passes'] else '  '
            row_str += f"  {r['trades']:3d}  {mark}"
        print(row_str)

    # Pareto: best PF for each level of trades
    print(f"\n{'='*75}")
    print(f"  FRONTERA PARETO — máximo PF dado mínimo trades (keepers)")
    print(f"{'='*75}")
    if keepers:
        keepers_sorted = sorted(keepers, key=lambda x: -x['pf'])
        print(f"  {'n_days':>6} {'vol':>6} {'Trades':>7} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}")
        print(f"  {'-'*55}")
        for r in keepers_sorted:
            print(f"  {r['n_days']:>6} {r['vol_ratio']:>5.1f}× {r['trades']:>7} "
                  f"{r['win_rate']:>5.1f}% {r['pf']:>7.3f} "
                  f"{r['return_pct']:>+7.1f}% {r['max_dd']:>6.1f}%")

        best = keepers_sorted[0]
        print(f"\n  RECOMENDACIÓN: n_days={best['n_days']}, vol_ratio={best['vol_ratio']}×")
        print(f"  PF={best['pf']}  trades={best['trades']}/5y ({best['trades']/5:.0f}/año)")
        print(f"  MaxDD={best['max_dd']:.1f}%  return={best['return_pct']:+.1f}%")
    else:
        print(f"  No hay keepers. Mejor PF:")
        by_pf = sorted(grid_results, key=lambda x: -x['pf'] if x['trades'] >= MIN_TRADES else 0)[:3]
        for r in by_pf:
            if r['trades'] >= MIN_TRADES:
                print(f"  n={r['n_days']}d vol≥{r['vol_ratio']}× → PF={r['pf']} trades={r['trades']} MaxDD={r['max_dd']:.1f}%")
    print(f"{'='*75}\n")
