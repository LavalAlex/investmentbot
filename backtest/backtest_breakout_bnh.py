"""
Breakout diario — Alpha vs Buy & Hold

Compara la estrategia de breakout (mejor config validada IS+OOS) contra
una estrategia pasiva de buy & hold para el mismo período y capital.

Configs de breakout:
  BTC: 10d, vol≥1.5×, ATR×1.5, RR=2  (PF=1.735 en 5y, PF=1.627 en 730d)
  ETH: 10d, vol≥1.5×, ATR×1.5, RR=2  (PF=1.711 en 5y, PF=1.442 en 730d)

Buy & Hold: compra al precio del primer día disponible, vende al último.
Métricas de comparación:
  - Return total
  - MaxDD
  - Calmar ratio = return_anualizado / MaxDD (mayor = mejor riesgo/retorno)
  - % tiempo en mercado
  - Return por unidad de riesgo (Calmar)

Períodos: 5 años (2021-2026) y 730d (2024-2026).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

CONFIGS = {
    'BTC': {'n_days': 10, 'vol_ratio': 1.5, 'atr_mult': 1.5, 'rr': 2.0},
    'ETH': {'n_days': 10, 'vol_ratio': 1.5, 'atr_mult': 1.5, 'rr': 2.0},
}

PERIODS = {
    '5y':   {'BTC': 'data/BTCUSDT_1h_last_5y.csv',  'ETH': 'data/ETHUSDT_1h_last_5y.csv'},
    '730d': {'BTC': 'data/BTCUSDT_1h_last_740d.csv', 'ETH': 'data/ETHUSDT_1h_last_740d.csv'},
}


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


def run_breakout(daily: pd.DataFrame, n_days: int, vol_ratio: float,
                 atr_mult: float, rr: float) -> tuple[list, int]:
    """Retorna (trades, days_in_market)."""
    equity, position, trades = INITIAL_CAPITAL, None, []
    days_in_market = 0
    daily = daily.copy()
    daily['nd_high'] = daily['close'].shift(1).rolling(n_days, min_periods=n_days).max()

    for i in range(len(daily)):
        row = daily.iloc[i]
        if pd.isna(row.get('atr14')) or pd.isna(row.get('nd_high')):
            continue

        if position is not None:
            days_in_market += 1
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
                    'open_time': str(position['open_time'])[:10],
                    'entry': position['entry'], 'exit': exit_price,
                    'reason': reason,
                    'pnl': round(net_pnl, 4), 'equity': round(equity, 4),
                    'fee_usd': round((position['entry'] + exit_price) * position['qty'] * FEE_PER_SIDE_PCT, 4),
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

    return trades, days_in_market


def breakout_metrics(trades: list, days_in_market: int, total_days: int) -> dict:
    if not trades:
        return {'trades': 0, 'pf': 0.0, 'return_pct': 0.0, 'max_dd': 0.0,
                'win_rate': 0.0, 'calmar': 0.0, 'time_in_mkt_pct': 0.0, 'fees': 0.0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp, gl = wins['pnl'].sum(), abs(loss['pnl'].sum())
    pf = round(gp / gl, 3) if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    ret_pct  = (df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    years    = total_days / 365.25
    ann_ret  = ((1 + ret_pct / 100) ** (1 / years) - 1) * 100 if years > 0 else 0
    calmar   = round(ann_ret / max_dd, 3) if max_dd > 0 else float('inf')
    time_pct = round(days_in_market / total_days * 100, 1) if total_days > 0 else 0
    return {
        'trades': len(df),
        'win_rate': round(len(wins) / len(df) * 100, 1),
        'pf': pf,
        'return_pct': round(ret_pct, 2),
        'ann_return': round(ann_ret, 2),
        'max_dd': round(max_dd, 2),
        'calmar': calmar,
        'time_in_mkt_pct': time_pct,
        'fees': round(df['fee_usd'].sum(), 2),
    }


def bnh_metrics(daily: pd.DataFrame) -> dict:
    """Buy & Hold: compra el primer día, vende el último."""
    prices = daily['close'].dropna().values
    if len(prices) < 2:
        return {}
    buy_price  = prices[0]
    sell_price = prices[-1]
    qty        = INITIAL_CAPITAL / buy_price
    fee_in     = INITIAL_CAPITAL * FEE_PER_SIDE_PCT
    final_val  = qty * sell_price - fee_in - (qty * sell_price * FEE_PER_SIDE_PCT)
    ret_pct    = (final_val - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # MaxDD sobre el equity curve diario de BnH
    equity_curve = qty * daily['close'].dropna().values
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        peak   = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)

    total_days = len(daily)
    years      = total_days / 365.25
    ann_ret    = ((1 + ret_pct / 100) ** (1 / years) - 1) * 100 if years > 0 else 0
    calmar     = round(ann_ret / max_dd, 3) if max_dd > 0 else float('inf')

    return {
        'buy_price':  round(buy_price, 2),
        'sell_price': round(sell_price, 2),
        'return_pct': round(ret_pct, 2),
        'ann_return': round(ann_ret, 2),
        'max_dd':     round(max_dd, 2),
        'calmar':     calmar,
        'time_in_mkt_pct': 100.0,
    }


def print_comparison(asset: str, period: str, bk: dict, bnh: dict, total_days: int) -> None:
    print(f"\n  {'─'*68}")
    print(f"  {asset} — {period}  ({total_days} días)")
    print(f"  {'─'*68}")
    print(f"  {'Métrica':<28} {'Breakout':>14} {'Buy & Hold':>14}")
    print(f"  {'─'*58}")
    print(f"  {'Return total':<28} {bk['return_pct']:>+13.1f}% {bnh['return_pct']:>+13.1f}%")
    print(f"  {'Return anualizado':<28} {bk['ann_return']:>+13.1f}% {bnh['ann_return']:>+13.1f}%")
    print(f"  {'MaxDD':<28} {bk['max_dd']:>13.1f}% {bnh['max_dd']:>13.1f}%")
    print(f"  {'Calmar (ret_ann/MaxDD)':<28} {bk['calmar']:>14.3f} {bnh['calmar']:>14.3f}")
    print(f"  {'Tiempo en mercado':<28} {bk['time_in_mkt_pct']:>13.1f}% {bnh['time_in_mkt_pct']:>13.1f}%")
    if bk.get('trades'):
        print(f"  {'Trades':<28} {bk['trades']:>14} {'—':>14}")
        print(f"  {'Win rate':<28} {bk['win_rate']:>13.1f}% {'—':>14}")
        print(f"  {'PF':<28} {bk['pf']:>14.3f} {'—':>14}")
        print(f"  {'Fees pagados':<28} ${bk['fees']:>12.0f} {'~$10':>14}")

    # Veredicto
    calmar_win = bk['calmar'] > bnh['calmar']
    dd_win     = bk['max_dd'] < bnh['max_dd']
    ret_win    = bk['return_pct'] > bnh['return_pct']
    print(f"\n  Ventajas del breakout vs BnH:")
    print(f"    {'✅' if calmar_win else '❌'} Calmar superior  ({bk['calmar']:.3f} vs {bnh['calmar']:.3f})")
    print(f"    {'✅' if dd_win else '❌'} Menor MaxDD      ({bk['max_dd']:.1f}% vs {bnh['max_dd']:.1f}%)")
    print(f"    {'✅' if ret_win else '❌'} Mayor retorno    ({bk['return_pct']:+.1f}% vs {bnh['return_pct']:+.1f}%)")
    score = sum([calmar_win, dd_win, ret_win])
    print(f"\n  Score: {score}/3  →  {'✅ Breakout gana en riesgo-retorno' if score >= 2 else '❌ BnH es mejor o comparable'}")


if __name__ == '__main__':
    print("\nBREAKOUT vs BUY & HOLD — Alpha real | fees 0.05%\n")

    for period_label, asset_paths in PERIODS.items():
        print(f"\n{'='*70}")
        print(f"  PERÍODO: {period_label.upper()}")
        print(f"{'='*70}")

        for asset, path in asset_paths.items():
            cfg = CONFIGS[asset]
            print(f"\n  Cargando {asset} {period_label}...", end='', flush=True)
            daily = build_daily(path)
            total_days = len(daily)
            print(f" {total_days} días")

            trades, days_in_mkt = run_breakout(
                daily, cfg['n_days'], cfg['vol_ratio'], cfg['atr_mult'], cfg['rr'])
            bk  = breakout_metrics(trades, days_in_mkt, total_days)
            bnh = bnh_metrics(daily)

            print_comparison(asset, period_label, bk, bnh, total_days)

    print(f"\n{'='*70}")
    print("  NOTA: Calmar = retorno_anualizado / MaxDD — el mejor indicador de")
    print("  eficiencia riesgo/retorno para estrategias con diferentes exposiciones.")
    print(f"{'='*70}\n")
