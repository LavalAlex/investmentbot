"""
EXP_E — Camino B: Mean Reversion v2 — Pin bar / wick rejection

Problema con EXP_C: BB+RSI da WR=11-22%, insuficiente para MR viable.
WR necesaria con RR 1.2:1 = 45.5% break-even. Estábamos muy lejos.

Hipótesis: el precio que toca una banda de BB no es suficiente señal.
Se necesita RECHAZO confirmado: vela con mecha larga que muestra que
los compradores/vendedores defendieron ese nivel en esa vela específica.

Señal v2:
  Long:  mecha inferior > 2× body, close en 70% superior del range,
         precio bajo la BB lower (o dentro de touch_pct%), ADX_1h < adx_max
  Short: mecha superior > 2× body, close en 30% inferior del range,
         precio sobre la BB upper, ADX_1h < adx_max
  + Volumen de la vela de señal ≥ vol_ratio × media(50 barras) en 15m

TP: BB mid (SMA20 en 1h). SL: extremo de la mecha (low para long, high para short).
Mínimo RR: 1.5:1 (más exigente que EXP_C para compensar la selectividad).

Variantes:
  E0 — ADX<25, mecha>2×body, vol≥1.0×, RR≥1.5
  E1 — ADX<20, mecha>2×body, vol≥1.0×, RR≥1.5
  E2 — ADX<25, mecha>2×body, vol≥1.5×, RR≥1.5  (más volumen)
  E3 — ADX<25, mecha>3×body, vol≥1.0×, RR≥1.5  (mecha más extrema)
  E4 — ADX<25, mecha>2×body, vol≥1.0×, RR≥2.0  (RR más conservador)

Assets: BTC y ETH 730d.
Criterio KEEP: PF≥1.2, WR≥40%, trades≥60 por asset.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from core.strategy_pullback import prepare_1h, prepare_15m, align_1h_to_15m
from core.strategy_mean_reversion import prepare_1h_mr, align_1h_mr_to_15m
from core.trade_logic import check_exit
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

PF_THRESHOLD  = 1.2
WR_THRESHOLD  = 40.0
MIN_TRADES    = 60

ASSETS = {
    'BTC': ('data/BTCUSDT_1h_last_740d.csv', 'data/BTCUSDT_15m_last_730d.csv'),
    'ETH': ('data/ETHUSDT_1h_last_740d.csv', 'data/ETHUSDT_15m_last_730d.csv'),
}

VARIANTS = [
    {'label': 'E0 — ADX<25, mecha>2x, vol≥1.0, RR≥1.5', 'adx_max': 25, 'wick_ratio': 2.0, 'vol_ratio': 1.0, 'min_rr': 1.5},
    {'label': 'E1 — ADX<20, mecha>2x, vol≥1.0, RR≥1.5', 'adx_max': 20, 'wick_ratio': 2.0, 'vol_ratio': 1.0, 'min_rr': 1.5},
    {'label': 'E2 — ADX<25, mecha>2x, vol≥1.5, RR≥1.5', 'adx_max': 25, 'wick_ratio': 2.0, 'vol_ratio': 1.5, 'min_rr': 1.5},
    {'label': 'E3 — ADX<25, mecha>3x, vol≥1.0, RR≥1.5', 'adx_max': 25, 'wick_ratio': 3.0, 'vol_ratio': 1.0, 'min_rr': 1.5},
    {'label': 'E4 — ADX<25, mecha>2x, vol≥1.0, RR≥2.0', 'adx_max': 25, 'wick_ratio': 2.0, 'vol_ratio': 1.0, 'min_rr': 2.0},
]


def build_df(path_1h: str, path_15m: str) -> pd.DataFrame:
    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h    = prepare_1h(df_1h_raw)
    df_1h_mr = prepare_1h_mr(df_1h)
    df_15m   = prepare_15m(df_15m_raw)
    df       = align_1h_to_15m(df_15m, df_1h)
    df       = align_1h_mr_to_15m(df, df_1h_mr)
    return df


def is_pin_bar_long(row, wick_ratio: float) -> bool:
    """Lower wick > wick_ratio × body, close in upper 70% of range."""
    o, c, h, l = row.get('open'), row.get('close'), row.get('high'), row.get('low')
    if any(pd.isna(v) for v in [o, c, h, l]):
        return False
    candle_range = h - l
    if candle_range <= 0:
        return False
    body       = abs(c - o)
    lower_wick = min(o, c) - l
    upper_pos  = (c - l) / candle_range  # 1.0 = at high, 0.0 = at low

    if body == 0:
        return False
    return lower_wick >= wick_ratio * body and upper_pos >= 0.70


def is_pin_bar_short(row, wick_ratio: float) -> bool:
    """Upper wick > wick_ratio × body, close in lower 30% of range."""
    o, c, h, l = row.get('open'), row.get('close'), row.get('high'), row.get('low')
    if any(pd.isna(v) for v in [o, c, h, l]):
        return False
    candle_range = h - l
    if candle_range <= 0:
        return False
    body       = abs(c - o)
    upper_wick = h - max(o, c)
    upper_pos  = (c - l) / candle_range

    if body == 0:
        return False
    return upper_wick >= wick_ratio * body and upper_pos <= 0.30


def has_volume_confirmation(row, vol_ratio: float) -> bool:
    vol     = row.get('volume')
    vol_m50 = row.get('vol_mean50')
    if any(pd.isna(v) for v in [vol, vol_m50]) or vol_m50 == 0:
        return vol_ratio <= 1.0   # si no hay media, solo bloqueamos si requerimos >1×
    return vol >= vol_ratio * vol_m50


def run(df: pd.DataFrame, adx_max: float, wick_ratio: float,
        vol_ratio: float, min_rr: float) -> list:
    equity, position, trades = INITIAL_CAPITAL, None, []

    for _, row in df.iterrows():
        if any(pd.isna(row.get(c)) for c in ['adx_1h', 'bb_upper', 'bb_lower', 'bb_mid']):
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
                    'open_time': str(position['open_time']),
                    'direction': position['direction'],
                    'entry':     position['entry'],
                    'exit':      exit_price,
                    'reason':    reason,
                    'gross_pnl': round(gross, 4),
                    'fee_usd':   round(fee, 4),
                    'pnl':       round(net_pnl, 4),
                    'equity':    round(equity, 4),
                })
                position = None
            continue

        # ── Regime gate ───────────────────────────────────────────────────────
        adx_val = row.get('adx_1h')
        if pd.isna(adx_val) or adx_val >= adx_max:
            continue

        # ── Volume gate ───────────────────────────────────────────────────────
        if not has_volume_confirmation(row, vol_ratio):
            continue

        close    = row['close']
        bb_upper = row.get('bb_upper')
        bb_lower = row.get('bb_lower')
        bb_mid   = row.get('bb_mid')
        h, l     = row.get('high'), row.get('low')

        # ── Long signal: pin bar + price at/below BB lower ────────────────────
        is_long = (close <= bb_lower * 1.005) and is_pin_bar_long(row, wick_ratio)
        # ── Short signal: pin bar + price at/above BB upper ───────────────────
        is_short = (close >= bb_upper * 0.995) and is_pin_bar_short(row, wick_ratio)

        if not is_long and not is_short:
            continue

        direction = 'long' if is_long else 'short'
        entry = close

        if direction == 'long':
            sl = l   # SL at the wick low (actual rejection level)
            tp = bb_mid
            if sl >= entry or tp <= entry:
                continue
        else:
            sl = h   # SL at the wick high
            tp = bb_mid
            if sl <= entry or tp >= entry:
                continue

        risk   = abs(entry - sl)
        reward = abs(tp - entry)
        if risk <= 0 or reward / risk < min_rr:
            continue

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       risk_usd / risk,
        }

    return trades


def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0.0, 'win_rate': 0.0,
                'return_pct': 0.0, 'max_dd': 0.0, 'fees': 0.0,
                'longs': 0, 'shorts': 0, 'long_pf': 0.0, 'short_pf': 0.0,
                'trades_raw': []}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum()
    gl   = abs(loss['pnl'].sum())
    pf   = round(gp / gl, 3) if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
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


def monthly_breakdown(trades: list) -> list:
    df = pd.DataFrame(trades)
    df['month'] = pd.to_datetime(df['open_time']).dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        wins = g[g['pnl'] > 0]
        gl   = abs(g[g['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        rows.append({'month': str(month), 'n': len(g),
                     'wr': round(len(wins)/len(g)*100,1),
                     'pf': round(gp/gl,3) if gl>0 else float('inf'),
                     'pnl': round(g['pnl'].sum(),2)})
    return rows


def print_asset_results(asset: str, results: list) -> bool:
    print(f"\n{'='*82}")
    print(f"  EXP_E — {asset} 730d | Pin bar MR | fees 0.05%")
    print(f"  Criterio: PF≥{PF_THRESHOLD}, WR≥{WR_THRESHOLD}%, trades≥{MIN_TRADES}")
    print(f"{'='*82}")
    print(f"  {'Variante':<42} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  Veredicto")
    print(f"  {'-'*82}")
    for m in results:
        passes = (m['trades'] >= MIN_TRADES and m['pf'] >= PF_THRESHOLD
                  and m['win_rate'] >= WR_THRESHOLD)
        v = '✅ KEEP' if passes else '❌ FAIL'
        print(f"  {m['label']:<42} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  {v}")

    keepers = [m for m in results if m['trades'] >= MIN_TRADES
               and m['pf'] >= PF_THRESHOLD and m['win_rate'] >= WR_THRESHOLD]
    best    = max(results, key=lambda x: x['pf'] if x['trades'] >= MIN_TRADES else 0)

    if best['trades'] > 0:
        print(f"\n  Longs vs Shorts (mejor variante: {best['label']}):")
        print(f"  Longs={best['longs']} PF={best['long_pf']}  Shorts={best['shorts']} PF={best['short_pf']}")

    if keepers:
        bk = max(keepers, key=lambda x: x['pf'])
        mb = monthly_breakdown(bk['trades_raw'])
        prof = sum(1 for r in mb if r['pf'] >= 1.0)
        print(f"\n  Breakdown mensual mejor keeper ({prof}/{len(mb)} meses rentables):")
        print(f"  {'Mes':<10} {'N':>4} {'WR':>6} {'PF':>7} {'PnL':>9}")
        print(f"  {'-'*40}")
        for r in mb:
            flag = '✓' if r['pf'] >= 1.0 else '✗'
            print(f"  {r['month']:<10} {r['n']:>4} {r['wr']:>5.1f}% {r['pf']:>7.3f} ${r['pnl']:>+8.2f}  {flag}")

    any_pass = bool(keepers)
    print(f"\n  VEREDICTO {asset}: {'✅ KEEP' if any_pass else '❌ FAIL'}")
    return any_pass


if __name__ == '__main__':
    print("\nEXP_E — Pin bar Mean Reversion v2 | BTC + ETH 730d")
    print("Construyendo dataframes...\n")

    verdicts = {}
    for asset, (path_1h, path_15m) in ASSETS.items():
        print(f"  {asset}: cargando datos...", end='', flush=True)
        df = build_df(path_1h, path_15m)
        print(f" {len(df):,} filas")
        results = []
        for v in VARIANTS:
            print(f"    {v['label']}...", end='', flush=True)
            trades = run(df, v['adx_max'], v['wick_ratio'], v['vol_ratio'], v['min_rr'])
            m = metrics(trades, v['label'])
            results.append(m)
            print(f" {m['trades']} trades  PF={m['pf']}  WR={m['win_rate']}%")
        verdicts[asset] = print_asset_results(asset, results)

    # ── Resumen final ─────────────────────────────────────────────────────────
    print(f"\n{'='*82}")
    print(f"  RESUMEN EXP_E")
    print(f"{'='*82}")
    for asset, passes in verdicts.items():
        print(f"  {asset}: {'✅ KEEP — pin bar MR tiene edge' if passes else '❌ FAIL — sin edge'}")
    if all(verdicts.values()):
        print(f"\n  ✅ Camino B viable → integrar con pullback en sistema combinado")
    elif any(verdicts.values()):
        print(f"\n  ⚠️  Parcial — solo integrar el asset que pasa")
    else:
        print(f"\n  ❌ Camino B descartado — revisar tipo de señal o timeframe")
    print(f"{'='*82}\n")
