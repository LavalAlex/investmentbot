"""
EXP_C — Mean Reversion Strategy B (ETH + BTC, 730d)

Pregunta: ¿Tiene edge una estrategia de reversión a la media cuando ADX_1h < 20?

Config:
  - Régimen: ADX_1h < 20 (ranging)
  - Señal long:  precio ≤ BB_lower + toque%, RSI < 35, vela de reversión en 15m
  - Señal short: precio ≥ BB_upper - toque%, RSI > 65, vela de reversión en 15m
  - SL: swing del lado contrario (candle low/high)
  - TP: BB mid (SMA20 en 1h) — RR variable, mínimo 1.2:1
  - Fees: 0.05%/lado

Assets: ETH y BTC, testeados por separado.

Criterio KEEP: PF≥1.2 con ≥80 trades en 730d por asset.

Variantes (para parametrizar umbrales):
  C0 — ADX<20, RSI<35/>65, BB touch 0.2%  (base)
  C1 — ADX<25, RSI<35/>65, BB touch 0.2%  (más permisivo en régimen)
  C2 — ADX<20, RSI<30/>70, BB touch 0.2%  (más extremo en RSI)
  C3 — ADX<20, RSI<35/>65, BB touch 0.5%  (más cercano a la banda)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from core.strategy_pullback import prepare_1h, prepare_15m, align_1h_to_15m
from core.strategy_mean_reversion import (
    prepare_1h_mr, align_1h_mr_to_15m,
    calculate_mr_sl_tp,
)
from core.trade_logic import check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

MIN_TRADES_THRESHOLD = 80
PF_THRESHOLD         = 1.2

ASSETS = {
    'BTC': ('data/BTCUSDT_1h_last_740d.csv',  'data/BTCUSDT_15m_last_730d.csv'),
    'ETH': ('data/ETHUSDT_1h_last_740d.csv',  'data/ETHUSDT_15m_last_730d.csv'),
}

VARIANTS = [
    {'label': 'C0 — ADX<20, RSI<35/>65, touch 0.2%', 'adx_max': 20, 'rsi_os': 35, 'rsi_ob': 65, 'bb_touch': 0.002},
    {'label': 'C1 — ADX<25, RSI<35/>65, touch 0.2%', 'adx_max': 25, 'rsi_os': 35, 'rsi_ob': 65, 'bb_touch': 0.002},
    {'label': 'C2 — ADX<20, RSI<30/>70, touch 0.2%', 'adx_max': 20, 'rsi_os': 30, 'rsi_ob': 70, 'bb_touch': 0.002},
    {'label': 'C3 — ADX<20, RSI<35/>65, touch 0.5%', 'adx_max': 20, 'rsi_os': 35, 'rsi_ob': 65, 'bb_touch': 0.005},
]


def build_df(path_1h: str, path_15m: str) -> pd.DataFrame:
    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h    = prepare_1h(df_1h_raw)
    df_1h_mr = prepare_1h_mr(df_1h)
    df_15m   = prepare_15m(df_15m_raw)
    df       = align_1h_to_15m(df_15m, df_1h)
    df       = align_1h_mr_to_15m(df, df_1h_mr)
    return df


def run(df: pd.DataFrame, adx_max: float, rsi_os: float, rsi_ob: float,
        bb_touch: float) -> list:
    equity, position, trades = INITIAL_CAPITAL, None, []

    for _, row in df.iterrows():
        # Require all MR indicators to be populated
        if any(pd.isna(row.get(c)) for c in ['adx_1h', 'bb_upper', 'bb_lower', 'rsi14', 'bb_mid']):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty   = position['qty']
                if position['direction'] == 'long':
                    gross = (exit_price - position['entry']) * qty
                else:
                    gross = (position['entry'] - exit_price) * qty
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'open_time':  str(position['open_time']),
                    'direction':  position['direction'],
                    'entry':      position['entry'],
                    'exit':       exit_price,
                    'reason':     reason,
                    'gross_pnl':  round(gross, 4),
                    'fee_usd':    round(fee, 4),
                    'pnl':        round(net_pnl, 4),
                    'equity':     round(equity, 4),
                    'adx_1h':     position.get('adx_1h'),
                    'rsi14':      position.get('rsi14'),
                })
                position = None
            continue

        # ── Régimen gate ──────────────────────────────────────────────────────
        adx_val = row.get('adx_1h')
        if pd.isna(adx_val) or adx_val >= adx_max:
            continue

        close    = row['close']
        bb_upper = row.get('bb_upper')
        bb_lower = row.get('bb_lower')
        bb_mid   = row.get('bb_mid')
        rsi_val  = row.get('rsi14')

        # ── Señal ─────────────────────────────────────────────────────────────
        is_long  = (close <= bb_lower * (1 + bb_touch)) and (rsi_val < rsi_os)
        is_short = (close >= bb_upper * (1 - bb_touch)) and (rsi_val > rsi_ob)

        if not is_long and not is_short:
            continue

        # Vela de reversión en 15m
        o, h, l = row.get('open'), row.get('high'), row.get('low')
        if any(pd.isna(v) for v in [o, h, l]):
            continue
        candle_range = h - l
        if candle_range <= 0:
            continue
        body = abs(close - o)
        if body / candle_range < 0.50:
            continue

        if is_long and close <= o:    # necesita vela alcista
            continue
        if is_short and close >= o:   # necesita vela bajista
            continue

        # Prioridad: long si ambas condiciones, tomar long
        direction = 'long' if is_long else 'short'

        # SL/TP
        entry = close
        if direction == 'long':
            sl = l
            tp = bb_mid
            if sl >= entry or tp <= entry:
                continue
        else:
            sl = h
            tp = bb_mid
            if sl <= entry or tp >= entry:
                continue

        risk   = abs(entry - sl)
        reward = abs(tp - entry)
        if risk <= 0 or reward / risk < 1.2:
            continue

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       risk_usd / risk,
            'adx_1h':    adx_val,
            'rsi14':     rsi_val,
        }

    return trades


def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0, 'return_pct': 0,
                'max_dd': 0, 'win_rate': 0, 'fees': 0, 'longs': 0, 'shorts': 0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum()
    gl   = abs(loss['pnl'].sum())
    pf   = round(gp / gl, 3) if gl > 0 else float('inf')

    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
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

    return {
        'label':      label,
        'trades':     len(df),
        'win_rate':   round(len(wins) / len(df) * 100, 1),
        'pf':         pf,
        'return_pct': round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd':     round(max_dd, 2),
        'fees':       round(df['fee_usd'].sum(), 2),
        'longs':      len(longs),
        'shorts':     len(shorts),
        'long_pf':    side_pf(longs),
        'short_pf':   side_pf(shorts),
        'trades_raw': trades,
    }


def monthly_breakdown(trades: list) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    df['month'] = pd.to_datetime(df['open_time']).dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        wins = g[g['pnl'] > 0]
        gl   = abs(g[g['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        rows.append({
            'month': str(month),
            'n':     len(g),
            'wr':    round(len(wins) / len(g) * 100, 1),
            'pf':    round(gp / gl, 3) if gl > 0 else float('inf'),
            'pnl':   round(g['pnl'].sum(), 2),
        })
    return pd.DataFrame(rows)


def print_asset_results(asset: str, results: list) -> None:
    print(f"\n{'='*80}")
    print(f"  EXP_C — {asset} 730d | Mean Reversion | fees 0.05%/lado")
    print(f"  Criterio: PF≥{PF_THRESHOLD} con ≥{MIN_TRADES_THRESHOLD} trades")
    print(f"{'='*80}")
    print(f"  {'Variante':<40} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  Veredicto")
    print(f"  {'-'*78}")
    for m in results:
        passes = m['trades'] >= MIN_TRADES_THRESHOLD and m['pf'] >= PF_THRESHOLD
        v = '✅ KEEP' if passes else '❌ FAIL'
        t = m['trades'] if m['trades'] else 0
        wr = f"{m['win_rate']:.1f}%" if m['trades'] else '—'
        pf = f"{m['pf']:.3f}" if m['trades'] else '—'
        ret = f"{m['return_pct']:+.1f}%" if m['trades'] else '—'
        dd = f"{m['max_dd']:.1f}%" if m['trades'] else '—'
        print(f"  {m['label']:<40} {t:>5} {wr:>6} {pf:>7} {ret:>8} {dd:>7}  {v}")

    best = max(results, key=lambda x: x['pf'] if x['trades'] >= MIN_TRADES_THRESHOLD else 0)
    passes_best = best['trades'] >= MIN_TRADES_THRESHOLD and best['pf'] >= PF_THRESHOLD

    if best['trades'] >= MIN_TRADES_THRESHOLD:
        print(f"\n  LONGS vs SHORTS (mejor variante):")
        print(f"  {best['label']}")
        print(f"  Longs: {best['longs']} (PF={best['long_pf']})  Shorts: {best['shorts']} (PF={best['short_pf']})")

        mb = monthly_breakdown(best['trades_raw'])
        print(f"\n  Breakdown mensual (mejor variante):")
        print(f"  {'Mes':<10} {'N':>4} {'WR':>6} {'PF':>7} {'PnL':>9}")
        print(f"  {'-'*40}")
        for _, row in mb.iterrows():
            flag = '✓' if row['pf'] >= 1.0 else '✗'
            print(f"  {row['month']:<10} {row['n']:>4} {row['wr']:>5.1f}% {row['pf']:>7.3f} ${row['pnl']:>+8.2f}  {flag}")

    any_pass = any(m['trades'] >= MIN_TRADES_THRESHOLD and m['pf'] >= PF_THRESHOLD for m in results)
    print(f"\n  VEREDICTO {asset}: {'✅ KEEP — mean reversion tiene edge' if any_pass else '❌ FAIL — sin edge en ranging'}")
    return any_pass, best


if __name__ == '__main__':
    print("\nEXP_C — Mean Reversion Strategy B | BTC + ETH 730d")
    print("Construyendo dataframes (esto tarda ~30s)...\n")

    asset_verdicts = {}
    for asset, (path_1h, path_15m) in ASSETS.items():
        print(f"  Procesando {asset}...")
        df = build_df(path_1h, path_15m)
        results = []
        for v in VARIANTS:
            print(f"    {v['label']}...", end='', flush=True)
            trades = run(df, v['adx_max'], v['rsi_os'], v['rsi_ob'], v['bb_touch'])
            m = metrics(trades, v['label'])
            results.append(m)
            print(f" {m['trades']} trades  PF={m['pf']}")

        any_pass, best = print_asset_results(asset, results)
        asset_verdicts[asset] = {'passes': any_pass, 'best': best}

    # ── Resumen final ─────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  RESUMEN EXP_C")
    print(f"{'='*80}")
    for asset, v in asset_verdicts.items():
        status = '✅ KEEP' if v['passes'] else '❌ FAIL'
        best   = v['best']
        if best['trades'] > 0:
            print(f"  {asset}: {status}  →  {best['label']}")
            print(f"       PF={best['pf']}  trades={best['trades']}  ret={best['return_pct']:+.1f}%  MaxDD={best['max_dd']:.1f}%")
        else:
            print(f"  {asset}: ❌ FAIL — 0 trades generados")

    print(f"\n  Siguiente paso:")
    all_pass = all(v['passes'] for v in asset_verdicts.values())
    if all_pass:
        print(f"  ✅ Ambos assets pasan → EXP_D: sistema combinado (pullback + MR)")
    else:
        failing = [a for a, v in asset_verdicts.items() if not v['passes']]
        print(f"  ❌ {', '.join(failing)} no pasan → ajustar parámetros antes de EXP_D")
    print(f"{'='*80}\n")
