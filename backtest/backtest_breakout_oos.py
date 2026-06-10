"""
Breakout diario — OOS 730d (BTC + ETH)

Pregunta: ¿Los configs ganadores de 5 años (F0/F2) funcionan en los últimos
730 días? Este es el período más reciente, genuinamente OOS respecto al diseño.

Configs testeadas (las mejores de Camino 1):
  BTC F2 — 10d, vol≥1.0×, ATR×1.5, RR=2  (keeper 5y: PF=1.475)
  BTC F1 — 20d, vol≥1.5×, ATR×1.5, RR=2  (mejor PF 5y: PF=2.204, pocas señales)
  ETH F0 — 20d, vol≥1.0×, ATR×1.5, RR=2  (keeper 5y ETH: PF=1.549)
  ETH F4 — 20d, vol≥1.0×, ATR×1.5, RR=3  (mejor PF 5y ETH: PF=1.792)

Criterio OOS PASS: PF≥1.2, dirección correcta (positivo), MaxDD<25%.
Si pasa: estrategia candidata a producción.
Si falla: el 5y tenía overfitting al período 2021-2024.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

PF_THRESHOLD = 1.2
MAX_DD_LIMIT = 25.0

ASSETS = {
    'BTC': {
        'path_1h': 'data/BTCUSDT_1h_last_740d.csv',
        'path_15m': 'data/BTCUSDT_15m_last_730d.csv',
        'variants': [
            {'label': 'BTC-F2 — 10d, vol≥1.0×, ATR×1.5, RR=2', 'n_days': 10, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
            {'label': 'BTC-F1 — 20d, vol≥1.5×, ATR×1.5, RR=2', 'n_days': 20, 'vol_ratio': 1.5, 'atr_mult': 1.5, 'rr': 2.0},
            {'label': 'BTC-F0 — 20d, vol≥1.0×, ATR×1.5, RR=2', 'n_days': 20, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
        ],
    },
    'ETH': {
        'path_1h': 'data/ETHUSDT_1h_last_740d.csv',
        'path_15m': 'data/ETHUSDT_15m_last_730d.csv',
        'variants': [
            {'label': 'ETH-F0 — 20d, vol≥1.0×, ATR×1.5, RR=2', 'n_days': 20, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
            {'label': 'ETH-F4 — 20d, vol≥1.0×, ATR×1.5, RR=3', 'n_days': 20, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 3.0},
            {'label': 'ETH-F2 — 10d, vol≥1.0×, ATR×1.5, RR=2', 'n_days': 10, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
        ],
    },
}


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


def run(daily: pd.DataFrame, n_days: int, vol_ratio: float, atr_mult: float, rr: float) -> list:
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
                exit_price = position['tp'] if hit_tp else position['sl']
                reason     = 'TP' if hit_tp else 'SL'
                if hit_tp and hit_sl:
                    exit_price, reason = position['tp'], 'TP'
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
        sl   = close - atr_mult * atr
        risk = close - sl
        if risk <= 0:
            continue
        tp = close + rr * risk

        position = {
            'open_time': row['open_time'], 'entry': close,
            'sl': sl, 'tp': tp,
            'qty': equity * RISK_PCT / risk,
        }
    return trades


def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0.0, 'return_pct': 0.0,
                'max_dd': 0.0, 'win_rate': 0.0, 'fees': 0.0}
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
        'label': label, 'trades': len(df),
        'win_rate': round(len(wins)/len(df)*100, 1),
        'pf': pf,
        'return_pct': round((df['equity'].iloc[-1] - INITIAL_CAPITAL)/INITIAL_CAPITAL*100, 2),
        'max_dd': round(max_dd, 2),
        'fees': round(df['fee_usd'].sum(), 2),
    }


if __name__ == '__main__':
    print("\nBREAKOUT OOS — 730d (Apr 2024 → Apr 2026) | fees 0.05%")
    print(f"Criterio OOS PASS: PF≥{PF_THRESHOLD}, MaxDD<{MAX_DD_LIMIT}%, retorno positivo\n")

    all_results = []
    for asset, cfg in ASSETS.items():
        print(f"  {asset}: construyendo daily...", end='', flush=True)
        daily = build_daily(cfg['path_1h'])
        print(f" {len(daily)} días")
        for v in cfg['variants']:
            print(f"    {v['label']}...", end='', flush=True)
            trades = run(daily, v['n_days'], v['vol_ratio'], v['atr_mult'], v['rr'])
            m = metrics(trades, v['label'])
            all_results.append(m)
            print(f" {m['trades']} trades  PF={m['pf']}  ret={m['return_pct']:+.1f}%")

    print(f"\n{'='*82}")
    print(f"  RESULTADOS OOS 730d — Breakout diario")
    print(f"{'='*82}")
    print(f"  {'Config':<42} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  OOS")
    print(f"  {'-'*80}")
    for m in all_results:
        passes = m['trades'] >= 5 and m['pf'] >= PF_THRESHOLD and m['max_dd'] < MAX_DD_LIMIT and m['return_pct'] > 0
        v = '✅ PASS' if passes else '❌ FAIL'
        print(f"  {m['label']:<42} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  {v}")

    keepers = [m for m in all_results
               if m['trades'] >= 5 and m['pf'] >= PF_THRESHOLD and m['max_dd'] < MAX_DD_LIMIT and m['return_pct'] > 0]
    print(f"\n{'='*82}")
    if keepers:
        print(f"  ✅ {len(keepers)} config(s) pasan OOS — candidatas a producción:")
        for k in keepers:
            print(f"    → {k['label']}  PF={k['pf']}  trades={k['trades']}  MaxDD={k['max_dd']:.1f}%")
    else:
        print(f"  ❌ Ninguna config pasa OOS — el 5y tenía overfitting al período 2021-2024")
    print(f"{'='*82}\n")
