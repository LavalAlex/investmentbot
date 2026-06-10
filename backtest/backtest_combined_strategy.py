"""
Tres estrategias — Comparativa directa BTC + ETH (5y + 730d)

  1. Pullback only   — EXP017-B config, longs only, sin filtro de régimen
  2. Breakout only   — 10d vol≥1.5× ATR×1.5 RR=2, sin filtro de régimen
  3. Combined ADX    — ADX(14) diario como router:
                         ADX > umbral  →  breakout
                         ADX ≤ umbral  →  pullback
                       Umbrales testeados: 20, 25, 30

Hipótesis: el router ADX mejora sobre ambas estrategias solas porque:
  - En tendencia fuerte (ADX alto) el breakout captura el movimiento completo
  - En tendencia moderada (ADX bajo) el pullback captura retracciones al EMA

Fees: 0.05% por lado. Todos los tests sobre mismos datos, mismo capital inicial.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from backtest.backtest_v2 import load_data
from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend, is_trend_strong, is_pullback_quality,
    is_entry_trigger, is_candle_quality, is_range_sufficient, is_market_efficient,
)
from core.trade_logic import calculate_sl_tp, check_exit
from core.indicators_v2 import adx as compute_adx

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005

# Pullback filters
MIN_SL_PCT_BTC = 0.0030  # EXP017-B
MIN_SL_PCT_ETH = 0.0050  # EXP016A
MIN_RISK_PRICE  = 1.0

# Breakout params (validados IS+OOS+WF)
BO_N_DAYS   = 10
BO_VOL_RATIO = 1.5
BO_ATR_MULT  = 1.5
BO_RR        = 2.0

PERIODS = {
    '5y':   {'BTC': ('data/BTCUSDT_1h_last_5y.csv',  'data/BTCUSDT_15m_last_5y.csv'),
              'ETH': ('data/ETHUSDT_1h_last_5y.csv',  'data/ETHUSDT_15m_last_5y.csv')},
    '730d': {'BTC': ('data/BTCUSDT_1h_last_740d.csv', 'data/BTCUSDT_15m_last_730d.csv'),
              'ETH': ('data/ETHUSDT_1h_last_740d.csv', 'data/ETHUSDT_15m_last_730d.csv')},
}


# ── Preparación de datos ──────────────────────────────────────────────────────

def build_daily_context(df_1h_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Construye el frame diario con:
      - ATR14, vol20, nd_high (para señal breakout)
      - ADX(14) diario (para router de régimen)
      - available_at = open_time + 1 día (timestamp de disponibilidad)
    """
    df = df_1h_raw.copy()
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
    daily['nd_high'] = daily['close'].shift(1).rolling(BO_N_DAYS, min_periods=BO_N_DAYS).max()

    # Señal de breakout: el router la usa al día siguiente
    daily['bo_signal'] = (
        (daily['close'] > daily['nd_high']) &
        (daily['volume'] >= BO_VOL_RATIO * daily['vol20']) &
        daily['atr14'].notna() &
        daily['nd_high'].notna()
    )
    # Precio de entrada breakout = close del día de señal
    daily['bo_entry']  = daily['close']
    daily['bo_sl']     = daily['close'] - BO_ATR_MULT * daily['atr14']

    # ADX(14) sobre velas diarias
    daily['adx_daily'] = compute_adx(daily.reset_index(), period=14).values

    # available_at: la vela diaria D está disponible al inicio del día D+1
    daily['available_at'] = daily.index + pd.Timedelta(days=1)

    return daily.reset_index()


def merge_daily_onto_15m(df_15m: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """
    Adjunta a cada vela 15m el contexto del último día completo disponible.
    Usa merge_asof (no lookahead): la vela del día D solo está disponible
    a partir del inicio del día D+1.
    """
    dc = daily[['available_at','adx_daily','bo_signal','bo_entry','bo_sl']].dropna(
        subset=['adx_daily']
    ).sort_values('available_at')

    left = df_15m.sort_values('open_time')
    merged = pd.merge_asof(
        left, dc,
        left_on='open_time', right_on='available_at',
        direction='backward',
    )
    # Marcar primera vela del día (para trigger de entrada breakout)
    merged['date'] = pd.to_datetime(merged['open_time']).dt.date
    merged['is_day_start'] = merged['date'] != merged['date'].shift(1)
    return merged


# ── Motor de backtest ─────────────────────────────────────────────────────────

def run(df: pd.DataFrame, mode: str, longs_only: bool,
        min_sl_pct: float, adx_threshold: float = 25.0) -> list:
    """
    mode:
      'pullback'  — solo pullback, sin router
      'breakout'  — solo breakout, sin router
      'combined'  — ADX > adx_threshold → breakout / ADX ≤ adx_threshold → pullback
    """
    equity   = INITIAL_CAPITAL
    position = None
    trades   = []
    breakout_entered_today = None  # fecha para dedup de entrada breakout

    for _, row in df.iterrows():
        # ── Gestión de posición abierta ───────────────────────────────────
        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                if position['direction'] == 'long':
                    gross = (exit_price - position['entry']) * position['qty']
                else:
                    gross = (position['entry'] - exit_price) * position['qty']
                fee     = (position['entry'] + exit_price) * position['qty'] * FEE_PER_SIDE_PCT
                pnl     = gross - fee
                equity += pnl
                trades.append({
                    'open_ts':   position['open_ts'],
                    'close_ts':  str(row['open_time']),
                    'strategy':  position['strategy'],
                    'direction': position['direction'],
                    'entry':     position['entry'],
                    'exit':      exit_price,
                    'reason':    reason,
                    'pnl':       round(pnl, 4),
                    'fee_usd':   round(fee, 4),
                    'equity':    round(equity, 4),
                })
                position = None
            continue  # nunca abrir nueva posición en la misma vela que una salida

        # ── Determinar régimen ────────────────────────────────────────────
        adx_val = row.get('adx_daily')
        adx_ok  = adx_val is not None and not pd.isna(adx_val)

        use_breakout = False
        use_pullback = False

        if mode == 'breakout':
            use_breakout = True
        elif mode == 'pullback':
            use_pullback = True
        else:  # combined
            if adx_ok:
                if float(adx_val) > adx_threshold:
                    use_breakout = True
                else:
                    use_pullback = True
            # Si ADX no disponible aún: no operar

        # ── Breakout entry ────────────────────────────────────────────────
        if use_breakout:
            is_start   = row.get('is_day_start', False)
            bo_signal  = row.get('bo_signal', False)
            bo_entry   = row.get('bo_entry')
            bo_sl      = row.get('bo_sl')
            today_date = row.get('date')

            if (is_start and bo_signal and
                    bo_entry is not None and not pd.isna(bo_entry) and
                    bo_sl is not None and not pd.isna(bo_sl) and
                    breakout_entered_today != today_date):

                entry = float(bo_entry)
                sl    = float(bo_sl)
                risk  = entry - sl

                if risk > 0:
                    tp       = entry + BO_RR * risk
                    risk_usd = equity * RISK_PCT
                    qty      = risk_usd / risk
                    breakout_entered_today = today_date
                    position = {
                        'strategy':  'breakout',
                        'direction': 'long',
                        'entry': entry, 'sl': sl, 'tp': tp, 'qty': qty,
                        'open_ts': str(row['open_time']),
                    }
            continue  # en modo breakout no evaluar también el pullback

        # ── Pullback entry ────────────────────────────────────────────────
        if use_pullback:
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

            entry     = float(row['close'])
            direction = 'long' if trend == 'up' else 'short'
            sl, tp    = calculate_sl_tp(entry, direction, row['low'], row['high'])

            if sl is None:
                continue
            risk_price = abs(entry - sl)
            if risk_price < MIN_RISK_PRICE:
                continue
            if risk_price / entry < min_sl_pct:
                continue

            risk_usd = equity * RISK_PCT
            qty      = risk_usd / risk_price
            position = {
                'strategy':  'pullback',
                'direction': direction,
                'entry': entry, 'sl': sl, 'tp': tp, 'qty': qty,
                'open_ts': str(row['open_time']),
            }

    return trades


# ── Métricas ──────────────────────────────────────────────────────────────────

def metrics(trades: list, label: str) -> dict:
    if not trades:
        return {'label': label, 'trades': 0, 'pf': 0.0, 'return_pct': 0.0,
                'max_dd': 0.0, 'win_rate': 0.0, 'fees': 0.0,
                'bo_trades': 0, 'pb_trades': 0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    loss = df[df['pnl'] <= 0]
    gp, gl = wins['pnl'].sum(), abs(loss['pnl'].sum())
    pf = round(gp / gl, 3) if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    ret = round((df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2)
    return {
        'label':      label,
        'trades':     len(df),
        'win_rate':   round(len(wins) / len(df) * 100, 1),
        'pf':         pf,
        'return_pct': ret,
        'max_dd':     round(max_dd, 2),
        'fees':       round(df['fee_usd'].sum(), 2),
        'bo_trades':  int((df['strategy'] == 'breakout').sum()),
        'pb_trades':  int((df['strategy'] == 'pullback').sum()),
    }


def print_results(asset: str, period: str, results: list) -> None:
    print(f"\n{'='*90}")
    print(f"  {asset} — {period} | fees 0.05%/lado")
    print(f"{'='*90}")
    print(f"  {'Estrategia':<32} {'T':>5} {'WR':>6} {'PF':>7} {'Ret':>8} {'MaxDD':>7} {'Fees':>7}  {'BO/PB':>8}")
    print(f"  {'-'*88}")
    for m in results:
        bopb = f"{m['bo_trades']}/{m['pb_trades']}" if m['bo_trades'] + m['pb_trades'] > 0 else '—'
        passes = m['pf'] >= 1.2 and m['max_dd'] < 20 and m['return_pct'] > 0
        flag = '✅' if passes else '  '
        print(f"  {flag} {m['label']:<30} {m['trades']:>5} {m['win_rate']:>5.1f}% "
              f"{m['pf']:>7.3f} {m['return_pct']:>+7.1f}% {m['max_dd']:>6.1f}% "
              f"${m['fees']:>6.0f}  {bopb:>8}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\nCOMBINED STRATEGY — Pullback / Breakout / ADX Router")
    print("Config: Pullback=EXP017-B longs-only | Breakout=10d vol≥1.5× ATR×1.5 RR=2\n")

    for period_label, asset_paths in PERIODS.items():
        for asset, (path_1h, path_15m) in asset_paths.items():
            longs_only  = True   # longs only para ambos assets
            min_sl_pct  = MIN_SL_PCT_BTC if asset == 'BTC' else MIN_SL_PCT_ETH

            print(f"\n  Cargando {asset} {period_label}...", end='', flush=True)
            df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
            print(f" {len(df_15m_raw)} velas 15m")

            # Preparación pullback
            df_1h_prep  = prepare_1h(df_1h_raw)
            df_15m_prep = prepare_15m(df_15m_raw)
            df_aligned  = align_1h_to_15m(df_15m_prep, df_1h_prep)

            # Preparación daily (breakout + ADX)
            daily = build_daily_context(df_1h_raw)

            # Merge daily context onto 15m
            df = merge_daily_onto_15m(df_aligned, daily)

            # Ejecutar las 5 variantes
            configs = [
                ('Pullback solo',         'pullback',  None),
                ('Breakout solo',         'breakout',  None),
                ('Combined ADX>20',       'combined',  20.0),
                ('Combined ADX>25',       'combined',  25.0),
                ('Combined ADX>30',       'combined',  30.0),
            ]

            results = []
            for label, mode, threshold in configs:
                kw = {'adx_threshold': threshold} if threshold is not None else {}
                t  = run(df, mode, longs_only, min_sl_pct, **kw)
                m  = metrics(t, label)
                results.append(m)

            print_results(asset, period_label, results)

            # Best combined vs best baseline
            pb = next(m for m in results if 'Pullback' in m['label'])
            bk = next(m for m in results if 'Breakout' in m['label'])
            comb = [m for m in results if 'Combined' in m['label']]
            best_comb = max(comb, key=lambda x: x['pf']) if comb else None

            if best_comb:
                print(f"\n  Resumen {asset} {period_label}:")
                print(f"    Pullback:          PF={pb['pf']:.3f}  ret={pb['return_pct']:+.1f}%  MaxDD={pb['max_dd']:.1f}%  fees=${pb['fees']:.0f}")
                print(f"    Breakout:          PF={bk['pf']:.3f}  ret={bk['return_pct']:+.1f}%  MaxDD={bk['max_dd']:.1f}%  fees=${bk['fees']:.0f}")
                print(f"    Mejor combined:    PF={best_comb['pf']:.3f}  ret={best_comb['return_pct']:+.1f}%  MaxDD={best_comb['max_dd']:.1f}%  ({best_comb['label']})")
                winner_pf = max(pb['pf'], bk['pf'], best_comb['pf'])
                winner = 'Pullback' if winner_pf == pb['pf'] else ('Breakout' if winner_pf == bk['pf'] else best_comb['label'])
                print(f"    → Ganador por PF: {winner}")

    print(f"\n{'='*90}\n")
