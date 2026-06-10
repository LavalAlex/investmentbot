"""
Breakout diario — Sistema combinado BTC + ETH (5 años + 730d)

Pregunta: ¿Operar BTC y ETH con sus mejores configs de breakout en paralelo
mejora el sistema? ¿Hay correlación destructiva o se complementan?

Modelo: cada asset opera con su propia cuenta de 50% del capital total.
Capital total: $10,000. BTC: $5,000. ETH: $5,000.
Risk 1% por trade sobre el sub-capital del asset.

Configs:
  BTC: F2 (10d, vol≥1.0×, ATR×1.5, RR=2)  → PF=1.475 en 5y
  ETH: F0 (20d, vol≥1.0×, ATR×1.5, RR=2)  → PF=1.549 en 5y

Métricas reportadas:
  - BTC individual, ETH individual
  - Sistema combinado: equity BTC + ETH sumados
  - Correlación de trades (¿entran al mismo tiempo?)
  - Diversificación real: ¿el MaxDD combinado es menor que el peor individual?

Períodos: 5 años (2021-2026) y 730d (2024-2026) por separado.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from backtest.backtest_v2 import load_data

TOTAL_CAPITAL    = 10_000.0
SPLIT            = 0.5      # 50% cada asset
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

PERIODS = {
    '5y':   {'BTC': ('data/BTCUSDT_1h_last_5y.csv',   'data/BTCUSDT_15m_last_5y.csv'),
              'ETH': ('data/ETHUSDT_1h_last_5y.csv',   'data/ETHUSDT_15m_last_5y.csv')},
    '730d': {'BTC': ('data/BTCUSDT_1h_last_740d.csv',  'data/BTCUSDT_15m_last_730d.csv'),
              'ETH': ('data/ETHUSDT_1h_last_740d.csv',  'data/ETHUSDT_15m_last_730d.csv')},
}

CONFIGS = {
    'BTC': {'n_days': 10, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
    'ETH': {'n_days': 20, 'vol_ratio': 1.0, 'atr_mult': 1.5, 'rr': 2.0},
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


def run_asset(daily: pd.DataFrame, initial_cap: float, n_days: int, vol_ratio: float,
              atr_mult: float, rr: float) -> list:
    equity, position, trades = initial_cap, None, []
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
                    'date':  str(row['open_time'])[:10],
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
        sl   = close - atr_mult * atr
        risk = close - sl
        if risk <= 0:
            continue
        tp = close + rr * risk
        position = {
            'open_time': row['open_time'], 'entry': close,
            'sl': sl, 'tp': tp, 'qty': equity * RISK_PCT / risk,
        }
    return trades


def metrics_individual(trades: list, label: str, init_cap: float) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0.0, 'return_pct': 0.0,
                'max_dd': 0.0, 'win_rate': 0.0, 'net_pnl': 0.0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp, gl = wins['pnl'].sum(), abs(loss['pnl'].sum())
    pf = round(gp / gl, 3) if gl > 0 else float('inf')
    peak, max_dd, eq = init_cap, 0.0, init_cap
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    return {
        'label': label, 'trades': len(df),
        'win_rate': round(len(wins)/len(df)*100, 1),
        'pf': pf,
        'return_pct': round((df['equity'].iloc[-1] - init_cap)/init_cap*100, 2),
        'max_dd': round(max_dd, 2),
        'net_pnl': round(df['pnl'].sum(), 2),
        'fees': round(df['fee_usd'].sum(), 2),
    }


def combined_metrics(btc_trades: list, eth_trades: list, total_cap: float) -> dict:
    """Merge trade streams by date and compute combined equity curve."""
    if not btc_trades and not eth_trades:
        return {}
    all_t = []
    for t in btc_trades:
        all_t.append({'date': t['date'], 'pnl': t['pnl'], 'asset': 'BTC'})
    for t in eth_trades:
        all_t.append({'date': t['date'], 'pnl': t['pnl'], 'asset': 'ETH'})
    all_t.sort(key=lambda x: x['date'])

    eq = total_cap
    peak, max_dd = total_cap, 0.0
    net_pnl = 0.0
    for t in all_t:
        eq += t['pnl']
        net_pnl += t['pnl']
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)

    total_trades = len(all_t)
    wins = sum(1 for t in all_t if t['pnl'] > 0)
    gp = sum(t['pnl'] for t in all_t if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in all_t if t['pnl'] <= 0))

    # Overlap: days where both assets have a trade
    btc_dates = {t['date'] for t in btc_trades}
    eth_dates = {t['date'] for t in eth_trades}
    overlap_days = len(btc_dates & eth_dates)

    return {
        'trades': total_trades,
        'win_rate': round(wins/total_trades*100, 1) if total_trades else 0,
        'pf': round(gp/gl, 3) if gl > 0 else float('inf'),
        'return_pct': round(net_pnl/total_cap*100, 2),
        'max_dd': round(max_dd, 2),
        'net_pnl': round(net_pnl, 2),
        'overlap_days': overlap_days,
    }


def monthly_pnl(btc_trades: list, eth_trades: list) -> pd.DataFrame:
    all_t = []
    for t in btc_trades:
        all_t.append({'month': t['open_time'][:7], 'pnl': t['pnl'], 'asset': 'BTC'})
    for t in eth_trades:
        all_t.append({'month': t['open_time'][:7], 'pnl': t['pnl'], 'asset': 'ETH'})
    if not all_t:
        return pd.DataFrame()
    df = pd.DataFrame(all_t)
    pivot = df.groupby(['month','asset'])['pnl'].sum().unstack(fill_value=0)
    if 'BTC' not in pivot: pivot['BTC'] = 0
    if 'ETH' not in pivot: pivot['ETH'] = 0
    pivot['total'] = pivot['BTC'] + pivot['ETH']
    pivot['profitable'] = pivot['total'] > 0
    return pivot.reset_index()


if __name__ == '__main__':
    print("\nBREAKOUT COMBINADO — BTC (F2) + ETH (F0) | 5y + 730d\n")

    for period_label, asset_paths in PERIODS.items():
        init_each = TOTAL_CAPITAL * SPLIT
        print(f"  {'='*70}")
        print(f"  PERÍODO: {period_label.upper()}")
        print(f"  Capital total ${TOTAL_CAPITAL:,.0f} | BTC ${init_each:,.0f} | ETH ${init_each:,.0f}")
        print(f"  {'='*70}")

        btc_trades, eth_trades = [], []
        for asset, (path_1h, _) in asset_paths.items():
            cfg = CONFIGS[asset]
            print(f"  {asset}: construyendo daily...", end='', flush=True)
            daily = build_daily(path_1h)
            print(f" {len(daily)} días", end='  ', flush=True)
            trades = run_asset(daily, init_each, cfg['n_days'], cfg['vol_ratio'],
                               cfg['atr_mult'], cfg['rr'])
            m = metrics_individual(trades, asset, init_each)
            print(f"→ {m['trades']} trades  PF={m['pf']}  MaxDD={m['max_dd']:.1f}%  ret={m['return_pct']:+.1f}%")
            if asset == 'BTC':
                btc_trades = trades
                btc_m = m
            else:
                eth_trades = trades
                eth_m = m

        comb = combined_metrics(btc_trades, eth_trades, TOTAL_CAPITAL)

        print(f"\n  {'Métrica':<22} {'BTC':>10} {'ETH':>10} {'COMBINADO':>12}")
        print(f"  {'-'*56}")
        print(f"  {'Trades':<22} {btc_m['trades']:>10} {eth_m['trades']:>10} {comb['trades']:>12}")
        print(f"  {'Win rate':<22} {btc_m['win_rate']:>9.1f}% {eth_m['win_rate']:>9.1f}% {comb['win_rate']:>11.1f}%")
        print(f"  {'PF':<22} {btc_m['pf']:>10.3f} {eth_m['pf']:>10.3f} {comb['pf']:>12.3f}")
        print(f"  {'Return':<22} {btc_m['return_pct']:>+9.1f}% {eth_m['return_pct']:>+9.1f}% {comb['return_pct']:>+11.1f}%")
        print(f"  {'MaxDD':<22} {btc_m['max_dd']:>9.1f}% {eth_m['max_dd']:>9.1f}% {comb['max_dd']:>11.1f}%")
        print(f"  {'Net PnL':<22} ${btc_m['net_pnl']:>+9,.2f} ${eth_m['net_pnl']:>+9,.2f} ${comb['net_pnl']:>+11,.2f}")
        print(f"  {'Días con overlap':<22} {'—':>10} {'—':>10} {comb['overlap_days']:>12}")

        # Monthly breakdown
        mb = monthly_pnl(btc_trades, eth_trades)
        if not mb.empty:
            prof = mb['profitable'].sum()
            total_months = len(mb)
            print(f"\n  Meses rentables combinados: {prof}/{total_months} ({prof/total_months*100:.0f}%)")
            print(f"\n  {'Mes':<10} {'BTC PnL':>10} {'ETH PnL':>10} {'Total':>10}  ")
            print(f"  {'-'*44}")
            for _, row in mb.iterrows():
                flag = '✓' if row['profitable'] else '✗'
                print(f"  {row['month']:<10} ${row['BTC']:>+9,.2f} ${row['ETH']:>+9,.2f} ${row['total']:>+9,.2f}  {flag}")

        verdict = '✅ SISTEMA VIABLE' if comb['pf'] >= 1.2 and comb['max_dd'] < 25 and comb['return_pct'] > 0 else '❌ NO APTO'
        print(f"\n  VEREDICTO {period_label}: {verdict}")
        print()
