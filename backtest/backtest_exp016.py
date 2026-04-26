"""
EXP016  —  Corrección de fee/edge ratio: SL mínimo y/o R:R mayor

Raíz del problema (EXP015):
    Con fees Taker 0.05%/lado, el fee por trade como múltiplo del riesgo R es:
        fee_ratio = 0.10% / SL_dist_pct

    Con R:R=2:1, el edge bruto por trade = 0.20R (WR=40%).
    Para que net_edge > 0: SL_dist_pct > 0.10% / 0.20 = 0.50%
    El sistema actual usa MIN_SL_DIST_PCT=0.15% → la mayoría de trades tienen
    fee > edge → sistema pierde dinero con fees reales.

Hipótesis:
    Dos palancas atacan la raíz:
    1. Subir MIN_SL_DIST_PCT de 0.15% a 0.50%: filtra trades donde fee > edge.
       Reduce volumen de trades pero mejora la calidad de cada uno.
    2. Subir R:R de 2:1 a 3:1: edge bruto sube de 0.20R a 0.60R.
       Threshold de SL viable baja de 0.50% a 0.33%.
       Riesgo: el precio puede no alcanzar el TP con la misma frecuencia.

Variantes testeadas (todas con fees 0.05%/lado):
    A: MIN_SL_DIST_PCT=0.50%, R:R=2:1   ← solo filtro SL
    B: MIN_SL_DIST_PCT=0.15%, R:R=3:1   ← solo R:R mayor
    C: MIN_SL_DIST_PCT=0.50%, R:R=3:1   ← combinado

Baseline de comparación: EXP015 (con fees, params actuales):
    BTC: PF=0.777, Return=-15.83%, MaxDD=21.77%
    ETH: PF=0.951, Return=-7.28%,  MaxDD=25.44%

Criterio de KEEP (vs EXP015 con fees):
    PF > 1.0 en ambos assets, MaxDD no empeora vs EXP015, trades >= 50% de EXP009.
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
from core.trade_logic import check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005   # 0.05% taker, Binance USDM Futures VIP0


def calculate_sl_tp(entry, direction, candle_low, candle_high, rr: float):
    if direction == 'long':
        sl   = candle_low
        risk = entry - sl
        if risk <= 0:
            return None, None
        tp = entry + rr * risk
    else:
        sl   = candle_high
        risk = sl - entry
        if risk <= 0:
            return None, None
        tp = entry - rr * risk
    return sl, tp


def run(path_1h: str, path_15m: str, longs_only: bool,
        min_sl_pct: float, rr: float) -> list:
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
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
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
                    'sl_dist_pct': position['sl_dist_pct'],
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
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'], rr)
        if sl is None:
            continue
        risk_price  = abs(entry - sl)
        sl_dist_pct = risk_price / entry
        if sl_dist_pct < min_sl_pct:
            continue

        risk_usd = equity * RISK_PCT
        position = {
            'open_time':   row['open_time'],
            'direction':   direction,
            'entry':       entry,
            'sl':          sl,
            'tp':          tp,
            'qty':         risk_usd / risk_price,
            'sl_dist_pct': round(sl_dist_pct * 100, 4),
        }

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
            'sl_dist_pct': position['sl_dist_pct'],
            'qty': round(qty, 6), 'reason': 'END',
            'gross_pnl': round(gross_pnl, 4), 'fee_usd': round(fee, 4),
            'pnl': round(net_pnl, 4), 'equity': round(equity, 4),
        })

    return trades


def metrics(trades: list) -> dict:
    if not trades:
        return {}
    df        = pd.DataFrame(trades)
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
        peak   = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    longs  = df[df['direction'] == 'long']
    shorts = df[df['direction'] == 'short']

    def side_pf(g):
        w = g[g['pnl'] > 0]['pnl'].sum()
        l = abs(g[g['pnl'] <= 0]['pnl'].sum())
        return round(w / l, 3) if l > 0 else float('inf')

    avg_sl = df['sl_dist_pct'].mean()
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(total_ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'avg_fee_usd':    round(df['fee_usd'].mean(), 2),
        'avg_sl_pct':     round(avg_sl, 3),
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
            'month':         str(month),
            'trades':        len(g),
            'win_rate_pct':  round(len(wins) / len(g) * 100, 1),
            'net_pnl':       round(g['pnl'].sum(), 2),
            'gross_pnl':     round(g['gross_pnl'].sum(), 2),
            'fees':          round(g['fee_usd'].sum(), 2),
            'profit_factor': round(gp / gl, 3) if gl > 0 else float('inf'),
        })
    return rows


# Baseline con fees (EXP015)
EXP015 = {
    'BTC': {'total_trades': 99,  'win_rate_pct': 39.4, 'return_pct': -15.83,
             'max_dd_pct': 21.77, 'profit_factor': 0.777, 'expectancy_usd': -15.99},
    'ETH': {'total_trades': 207, 'win_rate_pct': 41.1, 'return_pct': -7.28,
             'max_dd_pct': 25.44, 'profit_factor': 0.951, 'expectancy_usd': -3.52},
}

# Baseline sin fees (EXP009) — referencia de volumen
EXP009 = {
    'BTC': {'total_trades': 99},
    'ETH': {'total_trades': 207},
}


def print_report(asset: str, variants: dict) -> None:
    print(f"\n{'='*90}")
    print(f"EXP016  |  {asset}  |  Fee/edge fix: SL mínimo y/o R:R mayor  (fees 0.05%/lado incluidos)")
    print(f"{'='*90}")

    b15 = EXP015[asset]
    header = f"  {'Métrica':<22} {'EXP015 (base)':>13}"
    for label in ['A: SL≥0.50%\n  RR=2:1', 'B: SL≥0.15%\n  RR=3:1', 'C: SL≥0.50%\n  RR=3:1']:
        header += f" {'':>15}"
    print(f"\n  {'Métrica':<22} {'EXP015':>12} {'A: SL≥0.50%':>14} {'B: RR=3:1':>14} {'C: SL≥0.50%+RR3':>16}")
    print(f"  {'':22} {'(con fees)':>12} {'RR=2:1':>14} {'SL≥0.15%':>14} {'combinado':>16}")
    print(f"  {'-'*80}")

    fields = [
        ('Trades',        'total_trades',   '{:d}'),
        ('Win rate %',    'win_rate_pct',    '{:.1f}'),
        ('Return %',      'return_pct',      '{:+.2f}'),
        ('Max DD %',      'max_dd_pct',      '{:.2f}'),
        ('Profit factor', 'profit_factor',   '{:.3f}'),
        ('Expectancy $',  'expectancy_usd',  '{:+.2f}'),
        ('Avg SL %',      'avg_sl_pct',      '{:.3f}'),
        ('Avg fee $',     'avg_fee_usd',     '{:.2f}'),
    ]

    for label, key, fmt in fields:
        bv = b15.get(key, 0)
        row = f"  {label:<22} {fmt.format(bv):>12}"
        for vname in ['A', 'B', 'C']:
            m = variants[vname]['metrics']
            nv = m.get(key, 0)
            delta = nv - bv
            sign  = '+' if delta >= 0 else ''
            row += f"  {fmt.format(nv):>8} ({sign}{fmt.format(delta):>6})"
        print(row)

    for vname, cfg in [('A', 'SL≥0.50%, RR=2:1'), ('B', 'SL≥0.15%, RR=3:1'), ('C', 'SL≥0.50%, RR=3:1')]:
        m = variants[vname]['metrics']
        print(f"\n  [{vname}] {cfg} — Long PF={m.get('long_pf',0):.3f} | Short PF={m.get('short_pf',0):.3f} | Fees totales=${m.get('total_fees_usd',0):,.0f}")

    for vname, cfg in [('A', 'SL≥0.50%, RR=2:1'), ('B', 'SL≥0.15%, RR=3:1'), ('C', 'SL≥0.50%, RR=3:1')]:
        mo = variants[vname]['monthly']
        print(f"\n── [{vname}] {cfg} — breakdown mensual ──────────────────────────────────")
        print(f"  {'Mes':<10} {'T':>4} {'WR':>6} {'Bruto':>10} {'Fees':>8} {'Neto':>10} {'PF':>7}")
        print(f"  {'-'*58}")
        for row in mo:
            pf_str = f"{row['profit_factor']:.3f}" if row['profit_factor'] != float('inf') else "   inf"
            flag   = '  *' if row['profit_factor'] < 1.0 else ''
            print(f"  {row['month']:<10} {row['trades']:>4} {row['win_rate_pct']:>5.1f}% "
                  f"{row['gross_pnl']:>+9.2f} {row['fees']:>8.2f} {row['net_pnl']:>+9.2f}  {pf_str}{flag}")

    print(f"\n{'='*90}\n")


if __name__ == '__main__':
    asset_configs = [
        {'name': 'BTC', 'path_1h': 'data/BTCUSDT_1h_last_200d.csv',
         'path_15m': 'data/BTCUSDT_15m_last_180d.csv', 'longs_only': True},
        {'name': 'ETH', 'path_1h': 'data/ETHUSDT_1h_last_200d.csv',
         'path_15m': 'data/ETHUSDT_15m_last_180d.csv', 'longs_only': False},
    ]

    variant_configs = {
        'A': {'min_sl_pct': 0.0050, 'rr': 2.0},
        'B': {'min_sl_pct': 0.0015, 'rr': 3.0},
        'C': {'min_sl_pct': 0.0050, 'rr': 3.0},
    }

    all_results = {}
    for asset_cfg in asset_configs:
        asset = asset_cfg['name']
        print(f"\nRunning {asset}...")
        variants = {}
        for vname, vcfg in variant_configs.items():
            trades = run(
                asset_cfg['path_1h'], asset_cfg['path_15m'],
                asset_cfg['longs_only'],
                vcfg['min_sl_pct'], vcfg['rr'],
            )
            m  = metrics(trades)
            mo = monthly(trades)
            variants[vname] = {'metrics': m, 'monthly': mo}
            print(f"  [{vname}] min_sl={vcfg['min_sl_pct']*100:.2f}% rr={vcfg['rr']} → "
                  f"trades={m.get('total_trades',0)} PF={m.get('profit_factor',0):.3f} "
                  f"ret={m.get('return_pct',0):+.1f}%")

        print_report(asset, variants)
        all_results[asset] = variants

    out_path = 'data/backtest_exp016.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Resultados guardados en {out_path}")
