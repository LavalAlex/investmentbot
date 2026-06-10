"""
Breakout diario — Walk-forward 3 ventanas (BTC + ETH)

Divide los 5 años en 3 segmentos aproximadamente iguales (~609 días c/u).
Usa los parámetros óptimos definidos en el IS 5y SIN re-optimizar:
  BTC: 10d, vol≥1.5×, ATR×1.5, RR=2
  ETH: 10d, vol≥1.5×, ATR×1.5, RR=2

Objetivo: verificar que el edge no está concentrado solo en un período.
Si las 3 ventanas tienen PF>1.0 → edge robusto y no sobreajustado.
Si 1-2 ventanas fallan → el edge depende del régimen de mercado específico.

Criterio por ventana: PF>1.0, trades≥5.
Criterio global: PF>1.3 sobre todos los trades combinados.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

CONFIGS = {
    'BTC': {'path': 'data/BTCUSDT_1h_last_5y.csv',  'n_days': 10, 'vol_ratio': 1.5, 'atr_mult': 1.5, 'rr': 2.0},
    'ETH': {'path': 'data/ETHUSDT_1h_last_5y.csv',  'n_days': 10, 'vol_ratio': 1.5, 'atr_mult': 1.5, 'rr': 2.0},
}

N_WINDOWS = 3


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


def run(daily: pd.DataFrame, n_days: int, vol_ratio: float,
        atr_mult: float, rr: float) -> list:
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
                    'open_time': row['open_time'],
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


def metrics_window(trades: list) -> dict:
    if not trades:
        return {'trades': 0, 'pf': 0.0, 'return_pct': 0.0,
                'max_dd': 0.0, 'win_rate': 0.0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp, gl = wins['pnl'].sum(), abs(loss['pnl'].sum())
    pf = round(gp / gl, 3) if gl > 0 else float('inf')
    eq, peak, max_dd = INITIAL_CAPITAL, INITIAL_CAPITAL, 0.0
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    total_pnl = df['pnl'].sum()
    return {
        'trades': len(df),
        'win_rate': round(len(wins) / len(df) * 100, 1),
        'pf': pf,
        'return_pct': round(total_pnl / INITIAL_CAPITAL * 100, 2),
        'max_dd': round(max_dd, 2),
    }


def split_windows(daily: pd.DataFrame, n_windows: int) -> list:
    """Divide el dataframe en n_windows partes iguales."""
    total = len(daily)
    size  = total // n_windows
    windows = []
    for i in range(n_windows):
        start = i * size
        end   = (i + 1) * size if i < n_windows - 1 else total
        windows.append(daily.iloc[start:end].reset_index(drop=True))
    return windows


if __name__ == '__main__':
    print(f"\nBREAKOUT — Walk-forward {N_WINDOWS} ventanas (BTC + ETH 5y) | fees 0.05%")
    print("Config fija: 10d, vol≥1.5×, ATR×1.5, RR=2 (sin re-optimizar por ventana)\n")

    for asset, cfg in CONFIGS.items():
        print(f"  {asset}: cargando datos...", end='', flush=True)
        daily = build_daily(cfg['path'])
        print(f" {len(daily)} días")

        windows = split_windows(daily, N_WINDOWS)

        print(f"\n  {'='*72}")
        print(f"  {asset} — Walk-forward {N_WINDOWS} ventanas")
        print(f"  {'='*72}")
        print(f"  {'Ventana':<35} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  WF")
        print(f"  {'-'*70}")

        window_results = []
        all_trades     = []

        for idx, wdf in enumerate(windows):
            w_start = wdf['open_time'].iloc[0].strftime('%Y-%m-%d') if hasattr(wdf['open_time'].iloc[0], 'strftime') else str(wdf['open_time'].iloc[0])[:10]
            w_end   = wdf['open_time'].iloc[-1].strftime('%Y-%m-%d') if hasattr(wdf['open_time'].iloc[-1], 'strftime') else str(wdf['open_time'].iloc[-1])[:10]
            label   = f"W{idx+1} [{w_start} → {w_end}]"

            trades = run(wdf, cfg['n_days'], cfg['vol_ratio'], cfg['atr_mult'], cfg['rr'])
            m      = metrics_window(trades)
            window_results.append(m)
            all_trades.extend(trades)

            passes = m['trades'] >= 5 and m['pf'] >= 1.0
            flag   = '✅' if passes else '❌'
            print(f"  {label:<35} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
                  f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  {flag}")

        # Resultado global sobre todos los trades de las 3 ventanas
        m_all = metrics_window(all_trades)
        print(f"  {'-'*70}")
        global_pass = m_all['pf'] >= 1.3 and m_all['trades'] >= 15
        flag_g = '✅' if global_pass else '❌'
        print(f"  {'TOTAL 5y':<35} {m_all['trades']:>5} {m_all['win_rate']:>5.1f}% {m_all['pf']:>7.3f} "
              f"{m_all['return_pct']:>+7.1f}% {m_all['max_dd']:>6.1f}%  {flag_g}")

        n_pass = sum(1 for r in window_results if r['trades'] >= 5 and r['pf'] >= 1.0)
        print(f"\n  Ventanas rentables: {n_pass}/{N_WINDOWS}")

        if n_pass == N_WINDOWS:
            print(f"  ✅ Edge consistente en las {N_WINDOWS} ventanas — robusto inter-temporal")
        elif n_pass >= 2:
            print(f"  ⚠️  {N_WINDOWS - n_pass} ventana(s) fallan — edge concentrado en ciertos regímenes")
        else:
            print(f"  ❌ Edge no es robusto — el config depende demasiado del período")

    print(f"\n{'='*74}")
    print("  CRITERIO GLOBAL: PF>1.3 total + PF>1.0 en las 3 ventanas = ROBUSTO")
    print(f"{'='*74}\n")
