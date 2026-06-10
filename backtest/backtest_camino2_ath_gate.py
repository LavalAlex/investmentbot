"""
Camino 2 — ATH proximity gate sobre pullback EXP017-B (BTC 5 años)

Hipótesis: el edge del pullback aparece cuando BTC está en price discovery
(cerca de su ATH de N días). Cuando está lejos del ATH, el mercado es
ranging o bear y la estrategia solo pierde fees.

Gate: solo entrar si close_diario >= ATH(N días) × (1 - umbral)
  → significa que el precio está a no más de X% por debajo del ATH reciente

Variantes (combinan N días de ATH + umbral de proximidad):
  G0 — ATH90d, umbral 15%  (base)
  G1 — ATH90d, umbral 10%  (más estricto)
  G2 — ATH90d, umbral 20%  (más permisivo)
  G3 — ATH180d, umbral 15% (ATH de 6 meses)
  G4 — ATH30d,  umbral 10% (ATH de 1 mes — muy reciente)
  G5 — ATH365d, umbral 20% (ATH anual — macro)

Config base: EXP017-B (longs only, SL≥0.30%, RR=2:1, fees 0.05%/lado)
Datos: BTCUSDT_15m + BTCUSDT_1h (5 años)

Criterio KEEP: PF≥1.2, MaxDD<25%, trades≥150.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
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
FEE_PER_SIDE_PCT = 0.0005
MIN_SL_PCT       = 0.0030
RR               = 2.0

PATH_1H  = 'data/BTCUSDT_1h_last_5y.csv'
PATH_15M = 'data/BTCUSDT_15m_last_5y.csv'

PF_THRESHOLD = 1.2
MIN_TRADES   = 150
MAX_DD_LIMIT = 25.0

VARIANTS = [
    {'label': 'G0 — ATH90d,  umbral 15%', 'ath_days': 90,  'threshold': 0.15},
    {'label': 'G1 — ATH90d,  umbral 10%', 'ath_days': 90,  'threshold': 0.10},
    {'label': 'G2 — ATH90d,  umbral 20%', 'ath_days': 90,  'threshold': 0.20},
    {'label': 'G3 — ATH180d, umbral 15%', 'ath_days': 180, 'threshold': 0.15},
    {'label': 'G4 — ATH30d,  umbral 10%', 'ath_days': 30,  'threshold': 0.10},
    {'label': 'G5 — ATH365d, umbral 20%', 'ath_days': 365, 'threshold': 0.20},
]


def build_daily_ath(path_1h: str) -> pd.DataFrame:
    """Compute rolling ATH for multiple windows from 1h data resampled to daily."""
    df = pd.read_csv(path_1h)
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df = df.set_index('open_time').sort_index()

    daily = df['close'].resample('1D').last().dropna().to_frame()
    for n in [30, 90, 180, 365]:
        daily[f'ath_{n}d'] = daily['close'].shift(1).rolling(n, min_periods=n).max()

    daily = daily.reset_index().rename(columns={'open_time': 'date'})
    daily['available_date'] = daily['date'].dt.normalize() + pd.Timedelta(days=1)
    return daily[['available_date'] + [f'ath_{n}d' for n in [30, 90, 180, 365]]]


def align_ath_to_15m(df_15m: pd.DataFrame, df_ath: pd.DataFrame) -> pd.DataFrame:
    df = df_15m.copy()
    df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
    df_ath = df_ath.copy()
    df_ath['available_date'] = pd.to_datetime(df_ath['available_date'], utc=True)
    return pd.merge_asof(
        df.sort_values('open_time'),
        df_ath.sort_values('available_date'),
        left_on='open_time',
        right_on='available_date',
        direction='backward',
    )


def run(df: pd.DataFrame, ath_days: int, threshold: float) -> list:
    ath_col  = f'ath_{ath_days}d'
    equity, position, trades = INITIAL_CAPITAL, None, []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty   = position['qty']
                gross = (exit_price - position['entry']) * qty
                fee     = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'open_time': str(position['open_time']),
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

        # ── ATH proximity gate ────────────────────────────────────────────────
        ath = row.get(ath_col)
        if pd.isna(ath) or ath <= 0:
            continue
        if row['close'] < ath * (1 - threshold):
            continue

        # ── Pullback filters ──────────────────────────────────────────────────
        trend = get_trend(row)
        if trend is None or trend != 'up': continue
        if not is_trend_strong(row): continue
        if not is_pullback_quality(row, trend): continue
        if not is_entry_trigger(row, trend): continue
        if not is_candle_quality(row, trend): continue
        if not is_range_sufficient(row): continue
        if not is_market_efficient(row): continue

        entry = row['close']
        sl    = row['low']
        risk  = entry - sl
        if risk <= 0 or risk / entry < MIN_SL_PCT: continue
        tp = entry + RR * risk

        risk_usd = equity * RISK_PCT
        position = {
            'open_time': row['open_time'],
            'direction': 'long',
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       risk_usd / risk,
        }

    return trades


def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0.0, 'return_pct': 0.0,
                'max_dd': 0.0, 'win_rate': 0.0, 'fees': 0.0, 'trades_raw': []}
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
    return {
        'label':      label,
        'trades':     len(df),
        'win_rate':   round(len(wins) / len(df) * 100, 1),
        'pf':         pf,
        'return_pct': round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'max_dd':     round(max_dd, 2),
        'fees':       round(df['fee_usd'].sum(), 2),
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
                     'wr':  round(len(wins)/len(g)*100, 1),
                     'pf':  round(gp/gl, 3) if gl > 0 else float('inf'),
                     'pnl': round(g['pnl'].sum(), 2)})
    return rows


if __name__ == '__main__':
    print("\nCAMINO 2 — ATH proximity gate | BTC 5 años | EXP017-B base | fees 0.05%")
    print(f"Criterio: PF≥{PF_THRESHOLD}, MaxDD<{MAX_DD_LIMIT}%, trades≥{MIN_TRADES}\n")
    print("Cargando datos...", end='', flush=True)

    df_1h_raw, df_15m_raw = load_data(PATH_1H, PATH_15M)
    df_1h    = prepare_1h(df_1h_raw)
    df_15m   = prepare_15m(df_15m_raw)
    df       = align_1h_to_15m(df_15m, df_1h)
    df_ath   = build_daily_ath(PATH_1H)
    df       = align_ath_to_15m(df, df_ath)
    print(f" {len(df):,} filas\n")

    results = []
    for v in VARIANTS:
        print(f"  {v['label']}...", end='', flush=True)
        trades = run(df, v['ath_days'], v['threshold'])
        m = metrics(trades, v['label'])
        results.append(m)
        print(f" {m['trades']} trades  PF={m['pf']}  ret={m['return_pct']:+.1f}%")

    print(f"\n{'='*80}")
    print(f"  RESULTADOS CAMINO 2 — ATH gate | BTC 5 años")
    print(f"{'='*80}")
    print(f"  {'Variante':<32} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7}  Veredicto")
    print(f"  {'-'*75}")
    for m in results:
        passes = m['trades'] >= MIN_TRADES and m['pf'] >= PF_THRESHOLD and m['max_dd'] < MAX_DD_LIMIT
        v = '✅ KEEP' if passes else '❌ FAIL'
        print(f"  {m['label']:<32} {m['trades']:>5} {m['win_rate']:>5.1f}% {m['pf']:>7.3f} "
              f"{m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}%  {v}")

    keepers = [m for m in results
               if m['trades'] >= MIN_TRADES and m['pf'] >= PF_THRESHOLD and m['max_dd'] < MAX_DD_LIMIT]
    best = max(results, key=lambda x: x['pf'] if x['trades'] >= MIN_TRADES else 0)

    print(f"\n{'='*80}")
    if keepers:
        bk = max(keepers, key=lambda x: x['pf'])
        mb = monthly_breakdown(bk['trades_raw'])
        prof = sum(1 for r in mb if r['pf'] >= 1.0)
        print(f"  MEJOR KEEPER: {bk['label']}")
        print(f"  PF={bk['pf']}  trades={bk['trades']}  ret={bk['return_pct']:+.1f}%  MaxDD={bk['max_dd']:.1f}%")
        print(f"  Meses rentables: {prof}/{len(mb)}")
        print(f"\n  {'Mes':<10} {'N':>4} {'WR':>6} {'PF':>7} {'PnL':>9}")
        print(f"  {'-'*40}")
        for r in mb:
            flag = '✓' if r['pf'] >= 1.0 else '✗'
            print(f"  {r['month']:<10} {r['n']:>4} {r['wr']:>5.1f}% {r['pf']:>7.3f} ${r['pnl']:>+8.2f}  {flag}")
        print(f"\n  VEREDICTO: ✅ ATH gate funciona — Camino 2 viable")
    else:
        print(f"  MEJOR: {best['label']}  PF={best['pf']}  trades={best['trades']}")
        print(f"  VEREDICTO: ❌ ATH gate no alcanza criterios")
    print(f"{'='*80}\n")
