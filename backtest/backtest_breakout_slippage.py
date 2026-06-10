"""
Breakout diario — test de slippage en entrada

El backtest base entra al close del día de breakout. En producción esto no es
posible: la señal se detecta cuando cierra el día, y la entrada real sería al
open del día siguiente.

Modelos de entrada comparados:
  A — Baseline: entry = close del día de breakout (optimista, lo que tenemos)
  B — Next-open: entry = open del día D+1 (realista, market order)
  C — Limit at breakout: entry = nd_high (optimista, limit order pre-colocado)

Configs testeadas (las mejores configs validadas IS+OOS):
  BTC: 10d, vol≥1.5×, ATR×1.5, RR=2
  ETH: 10d, vol≥1.5×, ATR×1.5, RR=2

Datos: 5 años (IS full) + 730d OOS por separado.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

CONFIGS = {
    'BTC': {
        '5y':   'data/BTCUSDT_1h_last_5y.csv',
        '730d': 'data/BTCUSDT_1h_last_740d.csv',
        'n_days': 10, 'vol_ratio': 1.5, 'atr_mult': 1.5, 'rr': 2.0,
    },
    'ETH': {
        '5y':   'data/ETHUSDT_1h_last_5y.csv',
        '730d': 'data/ETHUSDT_1h_last_740d.csv',
        'n_days': 10, 'vol_ratio': 1.5, 'atr_mult': 1.5, 'rr': 2.0,
    },
}

# Modelos de entrada
ENTRY_MODELS = ['baseline', 'next_open', 'limit']


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


def run(daily: pd.DataFrame, n_days: int, vol_ratio: float, atr_mult: float,
        rr: float, entry_model: str) -> list:
    """
    entry_model:
      'baseline'  — entry = close del día de breakout
      'next_open' — entry = open del día siguiente (realista)
      'limit'     — entry = nd_high (limit order al nivel de breakout)
    """
    equity, position, trades = INITIAL_CAPITAL, None, []
    daily = daily.copy()
    daily['nd_high'] = daily['close'].shift(1).rolling(n_days, min_periods=n_days).max()

    # Pre-calcular next_open para el modelo realista
    daily['next_open'] = daily['open'].shift(-1)

    for i in range(len(daily)):
        row = daily.iloc[i]
        if pd.isna(row.get('atr14')) or pd.isna(row.get('nd_high')):
            continue

        if position is not None:
            # Para next_open, la entrada fue al open del día siguiente;
            # el seguimiento de SL/TP arranca desde ese día, no desde el día de señal.
            # Simplificación: usamos el mismo chequeo intra-día (high/low).
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
                    'entry_model': entry_model,
                })
                position = None
            else:
                continue

        close   = row['close']
        nd_high = row['nd_high']

        # Verificar señal de breakout (siempre basada en close vs nd_high)
        if close <= nd_high:
            continue
        vol20 = row.get('vol20')
        if not pd.isna(vol20) and vol20 > 0 and row['volume'] < vol_ratio * vol20:
            continue

        atr = row['atr14']

        # Precio de entrada según el modelo
        if entry_model == 'baseline':
            entry_price = close
        elif entry_model == 'next_open':
            next_op = row.get('next_open')
            if pd.isna(next_op):
                continue  # última barra
            entry_price = next_op
        elif entry_model == 'limit':
            entry_price = nd_high
        else:
            entry_price = close

        # SL siempre basado en ATR del día de breakout
        sl   = close - atr_mult * atr
        risk = entry_price - sl
        if risk <= 0:
            continue
        tp = entry_price + rr * risk

        position = {
            'open_time': row['open_time'], 'entry': entry_price,
            'sl': sl, 'tp': tp,
            'qty': equity * RISK_PCT / risk,
        }

    return trades


def metrics(trades: list) -> dict:
    if not trades:
        return {'trades': 0, 'pf': 0.0, 'return_pct': 0.0,
                'max_dd': 0.0, 'win_rate': 0.0, 'fees': 0.0, 'avg_entry_vs_close': 0.0}
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
        'win_rate': round(len(wins) / len(df) * 100, 1),
        'pf': pf,
        'return_pct': round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd': round(max_dd, 2),
        'fees': round(df['fee_usd'].sum(), 2),
    }


def print_comparison(asset: str, period: str, results: dict) -> None:
    print(f"\n  {asset} — {period}")
    print(f"  {'Modelo':<20} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  Fees")
    print(f"  {'-'*65}")

    baseline_pf  = results.get('baseline', {}).get('pf', 0)
    baseline_ret = results.get('baseline', {}).get('return_pct', 0)

    for model, m in results.items():
        delta_pf  = m['pf'] - baseline_pf if model != 'baseline' else 0
        delta_ret = m['return_pct'] - baseline_ret if model != 'baseline' else 0
        delta_str = f"  Δpf={delta_pf:+.3f} Δret={delta_ret:+.1f}%" if model != 'baseline' else ""
        print(f"  {model:<20} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  ${m['fees']:.0f}{delta_str}")


if __name__ == '__main__':
    print("\nBREAKOUT — Test de slippage en entrada | fees 0.05%")
    print("Baseline: entry=close | Next-open: entry=open D+1 | Limit: entry=nd_high\n")

    for asset, cfg in CONFIGS.items():
        n_days    = cfg['n_days']
        vol_ratio = cfg['vol_ratio']
        atr_mult  = cfg['atr_mult']
        rr        = cfg['rr']

        for period_key in ['5y', '730d']:
            path = cfg[period_key]
            print(f"  Cargando {asset} {period_key}...", end='', flush=True)
            daily = build_daily(path)
            print(f" {len(daily)} días")

            period_results = {}
            for model in ENTRY_MODELS:
                trades = run(daily, n_days, vol_ratio, atr_mult, rr, model)
                period_results[model] = metrics(trades)

            print_comparison(asset, f"{period_key} | config: {n_days}d vol≥{vol_ratio}×", period_results)

    print(f"\n{'='*70}")
    print("  INTERPRETACIÓN:")
    print("  baseline  → optimista (detección + entrada instantánea al close)")
    print("  next_open → realista  (se detecta al close, se entra al open D+1)")
    print("  limit     → ideal     (pre-colocamos limit en nd_high, price toca y sigue)")
    print("  El impacto de Δpf indica cuánto edge se pierde por latencia de entrada.")
    print(f"{'='*70}\n")
