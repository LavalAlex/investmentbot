"""
EXP017  —  BTC investigación: 12 meses con fees (ciclo completo Apr 2025 → Apr 2026)

Contexto:
    EXP015/016 testearon BTC sobre 180d (Sep 2025 → Mar 2026) — período bajista.
    El walk-forward (EXP006) mostró que el sistema no generaliza a períodos anteriores.
    EXP017 extiende el análisis a 12 meses completos: incluye el bull recovery
    (Apr-Sep 2025) Y el bear market (Oct 2025-Mar 2026).

    Con esta ventana podemos responder: ¿BTC tiene edge en alguna configuración
    que sea robusta a través de ambos regímenes?

Datos requeridos:
    data/BTCUSDT_15m_last_370d.csv   ← python fetch_all.py --extended
    data/BTCUSDT_1h_last_380d.csv

Variantes testeadas (todas con fees 0.05%/lado, longs only = EXP009):
    BASE : MIN_SL=0.15%,  RR=2:1  ← EXP015 baseline (con fees)
    A    : MIN_SL=0.50%,  RR=2:1  ← EXP016A (actual producción ETH)
    B    : MIN_SL=0.30%,  RR=2:1  ← intermedio — menos trades filtrados que A
    C    : MIN_SL=0.30%,  RR=3:1  ← intermedio + TP más largo
    D    : MIN_SL=0.50%,  RR=3:1  ← EXP016C (solo 23 trades en 180d — revisar en 12m)

Criterio de KEEP:
    PF > 1.0 con fees, MaxDD < 15%, trades suficientes (>= 40 en 12 meses).
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
FEE_PER_SIDE_PCT = 0.0005   # 0.05% taker


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
                    'open_time':   str(position['open_time']),
                    'close_time':  str(row['open_time']),
                    'direction':   position['direction'],
                    'entry':       position['entry'],
                    'exit':        exit_price,
                    'sl':          position['sl'],
                    'tp':          position['tp'],
                    'sl_dist_pct': position['sl_dist_pct'],
                    'qty':         round(qty, 6),
                    'reason':      reason,
                    'gross_pnl':   round(gross_pnl, 4),
                    'fee_usd':     round(fee, 4),
                    'pnl':         round(net_pnl, 4),
                    'equity':      round(equity, 4),
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

    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(total_ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'avg_fee_usd':    round(df['fee_usd'].mean(), 2),
        'avg_sl_pct':     round(df['sl_dist_pct'].mean(), 3),
        'long_pf':        side_pf(longs) if len(longs) else 0,
        'short_pf':       side_pf(shorts) if len(shorts) else 0,
    }


def regime_split(trades: list) -> dict:
    """
    Divide en 3 regímenes:
      bull_2024     : Apr 2024 → Sep 2024  (bull pre-ATH)
      ath_2024_25   : Oct 2024 → Mar 2025  (ATH + post-ATH correction)
      recovery_2025 : Apr 2025 → Sep 2025  (bull recovery hacia ATH)
      bear_2025_26  : Oct 2025 → Apr 2026  (bear market)
    """
    if not trades:
        return {}
    bull_2024    = [t for t in trades if t['close_time'] < '2024-10-01']
    ath_2024_25  = [t for t in trades if '2024-10-01' <= t['close_time'] < '2025-04-01']
    recovery     = [t for t in trades if '2025-04-01' <= t['close_time'] < '2025-10-01']
    bear         = [t for t in trades if t['close_time'] >= '2025-10-01']
    return {
        'bull_2024':    metrics(bull_2024),
        'ath_2024_25':  metrics(ath_2024_25),
        'recovery_2025': metrics(recovery),
        'bear_2025_26': metrics(bear),
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


VARIANT_CONFIGS = {
    'BASE': {'min_sl_pct': 0.0015, 'rr': 2.0, 'label': 'SL≥0.15%  RR=2:1  (EXP015 baseline)'},
    'A':    {'min_sl_pct': 0.0050, 'rr': 2.0, 'label': 'SL≥0.50%  RR=2:1  (EXP016A)'},
    'B':    {'min_sl_pct': 0.0030, 'rr': 2.0, 'label': 'SL≥0.30%  RR=2:1  (intermedio)'},
    'C':    {'min_sl_pct': 0.0030, 'rr': 3.0, 'label': 'SL≥0.30%  RR=3:1'},
    'D':    {'min_sl_pct': 0.0050, 'rr': 3.0, 'label': 'SL≥0.50%  RR=3:1  (EXP016C)'},
}


def print_report(variants: dict) -> None:
    print(f"\n{'='*100}")
    print(f"EXP017  |  BTC/USDT LONGS ONLY  |  12 meses con fees (Apr 2025 → Apr 2026)")
    print(f"{'='*100}")

    vnames = list(VARIANT_CONFIGS.keys())
    header = f"  {'Métrica':<22}"
    for v in vnames:
        header += f"  {v:>14}"
    print(header)
    print(f"  {'':22}" + ''.join(f"  {VARIANT_CONFIGS[v]['label'][:14]:>14}" for v in vnames))
    print(f"  {'-'*95}")

    fields = [
        ('Trades',        'total_trades',   '{:d}'),
        ('Win rate %',    'win_rate_pct',    '{:.1f}'),
        ('Return %',      'return_pct',      '{:+.2f}'),
        ('Max DD %',      'max_dd_pct',      '{:.2f}'),
        ('Profit factor', 'profit_factor',   '{:.3f}'),
        ('Expectancy $',  'expectancy_usd',  '{:+.2f}'),
        ('Avg SL %',      'avg_sl_pct',      '{:.3f}'),
        ('Total fees $',  'total_fees_usd',  '{:.0f}'),
        ('Long PF',       'long_pf',         '{:.3f}'),
    ]

    for label, key, fmt in fields:
        row = f"  {label:<22}"
        for v in vnames:
            m = variants[v]['metrics']
            val = m.get(key, 0) if m else 0
            row += f"  {fmt.format(val):>14}"
        print(row)

    # Regime breakdown
    print(f"\n── DESGLOSE POR RÉGIMEN ──────────────────────────────────────────────────────────────────────────────")
    regimes = [
        ('bull_2024',    'Bull 2024 (Apr-Sep)'),
        ('ath_2024_25',  'ATH 2024-25 (Oct-Mar)'),
        ('recovery_2025','Recovery 2025 (Apr-Sep)'),
        ('bear_2025_26', 'Bear 2025-26 (Oct-Apr)'),
    ]
    hdr = f"  {'Variante':<6}  {'':28}"
    for _, rlabel in regimes:
        hdr += f"  {rlabel:>22}"
    print(hdr)
    print(f"  {'-'*110}")
    for v, cfg in VARIANT_CONFIGS.items():
        r = variants[v].get('regime', {})
        row = f"  [{v}]  {cfg['label']:<28}"
        for rkey, _ in regimes:
            rm = r.get(rkey, {})
            if rm and rm.get('total_trades', 0) > 0:
                s = f"{rm['total_trades']}t {rm['win_rate_pct']:.0f}% PF={rm['profit_factor']:.2f}"
            else:
                s = "—"
            row += f"  {s:>22}"
        print(row)

    # Breakdown mensual de la mejor variante (por PF)
    best_v = max(
        [v for v in vnames if variants[v]['metrics']],
        key=lambda v: variants[v]['metrics'].get('profit_factor', 0)
    )
    best_cfg = VARIANT_CONFIGS[best_v]
    print(f"\n── BREAKDOWN MENSUAL — mejor variante [{best_v}] {best_cfg['label']} ──────────────────────────")
    print(f"  {'Mes':<10} {'T':>4} {'WR':>6} {'Bruto':>10} {'Fees':>8} {'Neto':>10} {'PF':>7}")
    print(f"  {'-'*60}")
    for row in variants[best_v]['monthly']:
        pf_str = f"{row['profit_factor']:.3f}" if row['profit_factor'] != float('inf') else "   inf"
        flag   = '  ✗' if row['profit_factor'] < 1.0 else '  ✓'
        print(f"  {row['month']:<10} {row['trades']:>4} {row['win_rate_pct']:>5.1f}% "
              f"{row['gross_pnl']:>+9.2f} {row['fees']:>8.2f} {row['net_pnl']:>+9.2f}  {pf_str}{flag}")

    print(f"\n{'='*100}\n")


if __name__ == '__main__':
    PATH_1H  = 'data/BTCUSDT_1h_last_740d.csv'
    PATH_15M = 'data/BTCUSDT_15m_last_730d.csv'

    # Fallback a 370d si no están los 730d
    if not os.path.exists(PATH_15M):
        PATH_1H  = 'data/BTCUSDT_1h_last_380d.csv'
        PATH_15M = 'data/BTCUSDT_15m_last_370d.csv'
        if not os.path.exists(PATH_15M):
            print(f"ERROR: datos no encontrados.")
            print("Ejecutar primero: python fetch_all.py --2y")
            sys.exit(1)
        print(f"[WARN] Usando datos de 370d (730d no disponibles)")
    else:
        print(f"Usando datos de 730d (2 años)")

    print(f"\nEXP017 — BTC con fees | {len(VARIANT_CONFIGS)} variantes\n")

    all_variants = {}
    for vname, vcfg in VARIANT_CONFIGS.items():
        trades = run(PATH_1H, PATH_15M, longs_only=True,
                     min_sl_pct=vcfg['min_sl_pct'], rr=vcfg['rr'])
        m  = metrics(trades)
        mo = monthly(trades)
        rg = regime_split(trades)
        all_variants[vname] = {'metrics': m, 'monthly': mo, 'regime': rg}
        print(f"  [{vname}] {vcfg['label']:<40} → "
              f"trades={m.get('total_trades',0):>3}  "
              f"PF={m.get('profit_factor',0):.3f}  "
              f"ret={m.get('return_pct',0):+.1f}%  "
              f"dd={m.get('max_dd_pct',0):.1f}%")

    print_report(all_variants)

    out_path = 'data/backtest_exp017.json'
    with open(out_path, 'w') as f:
        json.dump(all_variants, f, indent=2, default=str)
    print(f"Resultados guardados en {out_path}")
