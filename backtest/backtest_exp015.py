"""
EXP015  —  Impacto real de los fees de trading (Binance USDM Futures)

Hipótesis:
    El backtest base (EXP009) no descuenta comisiones. En Binance USDM
    Futures, VIP0 paga 0.05% Taker por lado (ambas puntas son market orders).
    Round-trip = 0.10% del nocional. Este experimento mide cuánto erosionan
    los fees el PF real y si el sistema sigue siendo viable con fricciones reales.

    Fee aplicado: entry_notional * FEE + exit_notional * FEE
    donde FEE = 0.05% (taker sin descuento BNB — caso conservador).

    Con BNB el fee bajaría a 0.045% por lado (round-trip 0.09%).

Baseline (EXP009, sin fees):
  BTC longs : 99 trades | WR=39.4% | PF=1.297 | Return=+18.45% | MaxDD=7.78%
  ETH both  : 207 trades | WR=41.1% | PF=1.375 | Return=+57.95% | MaxDD=10.76%

Cambio: una sola variable — descontar fee real en cada cierre.
No se toca ningún filtro, SL/TP, ni parámetro de riesgo.

Criterio:
  INFORMATIVO — no hay "KEEP/REVERT" porque los fees son una realidad del mercado,
  no un filtro opcional. El resultado define el PF real del sistema en producción.
"""

import json
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend, is_trend_strong, is_pullback_quality,
    is_entry_trigger, is_candle_quality,
    is_range_sufficient, is_market_efficient,
)
from core.trade_logic import calculate_sl_tp, check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
MIN_SL_DIST_PCT  = 0.0015
FEE_PER_SIDE_PCT = 0.0005   # 0.05% taker, Binance USDM Futures VIP0


def run(path_1h: str, path_15m: str, longs_only: bool) -> list:
    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h  = prepare_1h(df_1h_raw)
    df_15m = prepare_15m(df_15m_raw)
    df     = align_1h_to_15m(df_15m, df_1h)

    equity   = INITIAL_CAPITAL
    position = None
    trades   = []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty = position['qty']

                gross_pnl = (
                    (exit_price - position['entry']) * qty
                    if position['direction'] == 'long'
                    else (position['entry'] - exit_price) * qty
                )
                fee = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross_pnl - fee

                equity += net_pnl
                trades.append({
                    'open_time':  position['open_time'],
                    'close_time': row['open_time'],
                    'direction':  position['direction'],
                    'entry':      position['entry'],
                    'exit':       exit_price,
                    'sl':         position['sl'],
                    'tp':         position['tp'],
                    'qty':        round(qty, 6),
                    'reason':     reason,
                    'gross_pnl':  round(gross_pnl, 4),
                    'fee_usd':    round(fee, 4),
                    'pnl':        round(net_pnl, 4),
                    'equity':     round(equity, 4),
                })
                position = None
            continue

        trend = get_trend(row)
        if trend is None:
            continue
        if longs_only and trend != 'up':
            continue
        if not is_trend_strong(row):
            continue
        if not is_pullback_quality(row, trend):
            continue
        if not is_entry_trigger(row, trend):
            continue
        if not is_candle_quality(row, trend):
            continue
        if not is_range_sufficient(row):
            continue
        if not is_market_efficient(row):
            continue

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None:
            continue
        risk_price = abs(entry - sl)
        if risk_price / entry < MIN_SL_DIST_PCT:
            continue

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       risk_usd / risk_price,
        }

    # Cierre forzado al final si queda posición abierta
    if position is not None:
        exit_price = df.iloc[-1]['close']
        qty = position['qty']
        gross_pnl = (
            (exit_price - position['entry']) * qty
            if position['direction'] == 'long'
            else (position['entry'] - exit_price) * qty
        )
        fee = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
        net_pnl = gross_pnl - fee
        equity += net_pnl
        trades.append({
            'open_time': position['open_time'], 'close_time': df.iloc[-1]['open_time'],
            'direction': position['direction'], 'entry': position['entry'],
            'exit': exit_price, 'sl': position['sl'], 'tp': position['tp'],
            'qty': round(qty, 6), 'reason': 'END',
            'gross_pnl': round(gross_pnl, 4), 'fee_usd': round(fee, 4),
            'pnl': round(net_pnl, 4), 'equity': round(equity, 4),
        })

    return trades


def metrics(trades: list) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    wins      = df[df['pnl'] > 0]
    losses    = df[df['pnl'] <= 0]
    gp        = wins['pnl'].sum()
    gl        = abs(losses['pnl'].sum())
    pf        = gp / gl if gl > 0 else float('inf')
    total_ret = (df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    peak, max_dd = INITIAL_CAPITAL, 0.0
    eq = INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    longs  = df[df['direction'] == 'long']
    shorts = df[df['direction'] == 'short']

    def side_pf(g):
        w = g[g['pnl'] > 0]['pnl'].sum()
        l = abs(g[g['pnl'] <= 0]['pnl'].sum())
        return round(w / l, 3) if l > 0 else float('inf')

    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(total_ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'avg_fee_usd':    round(df['fee_usd'].mean(), 2),
        'long_pf':        side_pf(longs) if len(longs) else 0,
        'short_pf':       side_pf(shorts) if len(shorts) else 0,
    }


def monthly(trades: list) -> list:
    if not trades:
        return []
    df = pd.DataFrame(trades)
    df['month'] = pd.to_datetime(df['close_time']).dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        wins = g[g['pnl'] > 0]
        gl   = abs(g[g['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        rows.append({
            'month':          str(month),
            'trades':         len(g),
            'win_rate_pct':   round(len(wins) / len(g) * 100, 1),
            'net_pnl':        round(g['pnl'].sum(), 2),
            'gross_pnl':      round(g['gross_pnl'].sum(), 2),
            'fees':           round(g['fee_usd'].sum(), 2),
            'profit_factor':  round(gp / gl, 3) if gl > 0 else float('inf'),
        })
    return rows


BASELINE = {
    'BTC': {'total_trades': 99,  'win_rate_pct': 39.4, 'return_pct': 18.45,
             'max_dd_pct': 7.78, 'profit_factor': 1.297, 'expectancy_usd': 18.63},
    'ETH': {'total_trades': 207, 'win_rate_pct': 41.1, 'return_pct': 57.95,
             'max_dd_pct': 10.76, 'profit_factor': 1.375, 'expectancy_usd': 27.99},
}


def print_report(asset: str, m: dict, mo: list) -> None:
    b = BASELINE[asset]
    print(f"\n{'='*72}")
    print(f"EXP015  |  {asset}  |  Con fees reales (Taker 0.05%/lado, round-trip 0.10%)")
    print(f"{'='*72}")
    print(f"\n{'Métrica':<25} {'EXP009 (sin fees)':>17} {'EXP015 (con fees)':>17} {'Delta':>10}")
    print(f"{'-'*70}")
    fields = [
        ('Trades',         'total_trades',   '{:d}'),
        ('Win rate %',     'win_rate_pct',    '{:.1f}'),
        ('Return %',       'return_pct',      '{:+.2f}'),
        ('Max DD %',       'max_dd_pct',      '{:.2f}'),
        ('Profit factor',  'profit_factor',   '{:.3f}'),
        ('Expectancy $',   'expectancy_usd',  '{:+.2f}'),
    ]
    for label, key, fmt in fields:
        bv    = b[key]
        nv    = m.get(key, 0)
        delta = nv - bv
        sign  = '+' if delta >= 0 else ''
        print(f"  {label:<23} {fmt.format(bv):>17} {fmt.format(nv):>17}  {sign}{fmt.format(delta):>8}")

    print(f"\n  Fees totales cobrados : ${m['total_fees_usd']:,.2f} USD en 180 días")
    print(f"  Fee promedio/trade    : ${m['avg_fee_usd']:.2f} USD")
    print(f"  Long  PF  : {m['long_pf']:.3f}  |  Short PF : {m['short_pf']:.3f}")

    print(f"\n── Breakdown mensual ────────────────────────────────────────────────")
    print(f"  {'Mes':<10} {'Trades':>6} {'WR':>6} {'Bruto':>10} {'Fees':>8} {'Neto':>10} {'PF':>7}")
    print(f"  {'-'*63}")
    for row in mo:
        pf_str = f"{row['profit_factor']:.3f}" if row['profit_factor'] != float('inf') else "   inf"
        flag   = '  *' if row['profit_factor'] < 1.0 else ''
        print(f"  {row['month']:<10} {row['trades']:>6} {row['win_rate_pct']:>5.1f}% "
              f"{row['gross_pnl']:>+9.2f} {row['fees']:>8.2f} {row['net_pnl']:>+9.2f}  {pf_str}{flag}")
    print(f"{'='*72}\n")


if __name__ == '__main__':
    configs = [
        {'name': 'BTC', 'path_1h': 'data/BTCUSDT_1h_last_200d.csv',
         'path_15m': 'data/BTCUSDT_15m_last_180d.csv', 'longs_only': True},
        {'name': 'ETH', 'path_1h': 'data/ETHUSDT_1h_last_200d.csv',
         'path_15m': 'data/ETHUSDT_15m_last_180d.csv', 'longs_only': False},
    ]

    all_results = {}
    for cfg in configs:
        print(f"\nRunning {cfg['name']}...")
        trades = run(cfg['path_1h'], cfg['path_15m'], cfg['longs_only'])
        m  = metrics(trades)
        mo = monthly(trades)
        print_report(cfg['name'], m, mo)
        all_results[cfg['name']] = {'metrics': m, 'monthly': mo}

    out_path = 'data/backtest_exp015.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"Resultados guardados en {out_path}")
