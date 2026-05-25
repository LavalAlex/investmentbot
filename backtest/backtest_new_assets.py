"""
NEW ASSETS — SOL / BNB / XRP  (730d, fees incluidas)

Aplica el stack completo de producción (EXP016/017 + SLOPE_CAP + TIME-B + DYN-B)
a tres activos candidatos. Sin filtro 4h (solo BTC lo usa).

Variantes por activo:
    LONGS_ONLY   : solo longs (como BTC)
    LONGS_SHORTS : longs + shorts (como ETH)

SL mínimo calibrado por volatilidad típica de cada activo.

Referencia: BTC=PF1.787 (BASE, sin 4h), ETH=PF1.568 ambos en 730d.
"""

import json, os, sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend, is_trend_strong, is_pullback_quality,
    is_entry_trigger, is_candle_quality,
    is_range_sufficient, is_market_efficient,
)
from core.trade_logic import check_exit


def load_data(path_1h: str, path_15m: str):
    """Load OHLCV CSVs — supports both 'open_time' and 'timestamp' column names."""
    def _load(path):
        df = pd.read_csv(path)
        if 'timestamp' in df.columns and 'open_time' not in df.columns:
            df = df.rename(columns={'timestamp': 'open_time'})
        df['open_time'] = pd.to_datetime(df['open_time'], utc=True)
        df = df.sort_values('open_time').reset_index(drop=True)
        return df
    return _load(path_1h), _load(path_15m)

INITIAL_CAPITAL   = 10_000.0
RISK_PCT          = 0.01
FEE_PER_SIDE_PCT  = 0.0005
MAX_SLOPE_PCT     = 0.20       # EXP019 SLOPE_CAP
ATR_PERIOD        = 14
ATR_MEAN_WINDOW   = 50
SCALE_MIN         = 0.6
SCALE_MAX         = 1.2
TIME_B_START      = 7
TIME_B_END        = 21
VOL_MIN_RATIO     = 1.0        # Task007 ETH-SHORT-C (aplica a shorts de todos los activos)
FIXED_RR          = 2.0

# Activos candidatos — SL mínimo estimado por volatilidad (a afinar si hay señal)
# BTC=0.30%, ETH=0.50%; altcoins más volátiles → 0.50% como punto de partida
ASSET_CONFIGS = {
    'SOL': {
        'path_1h':  'data/SOLUSDT_1h_last_740d.csv',
        'path_15m': 'data/SOLUSDT_15m_last_730d.csv',
        'min_sl_pct': 0.0050,
    },
    'BNB': {
        'path_1h':  'data/BNBUSDT_1h_last_740d.csv',
        'path_15m': 'data/BNBUSDT_15m_last_730d.csv',
        'min_sl_pct': 0.0040,
    },
    'XRP': {
        'path_1h':  'data/XRPUSDT_1h_last_740d.csv',
        'path_15m': 'data/XRPUSDT_15m_last_730d.csv',
        'min_sl_pct': 0.0050,
    },
}

# Referencia: BTC y ETH con mismos parámetros del backtest Task010b BASE
REFERENCE_CONFIGS = {
    'BTC': {
        'path_1h':  'data/BTCUSDT_1h_last_740d.csv',
        'path_15m': 'data/BTCUSDT_15m_last_730d.csv',
        'min_sl_pct': 0.0030,
        'longs_only_only': True,   # BTC siempre longs only
    },
    'ETH': {
        'path_1h':  'data/ETHUSDT_1h_last_740d.csv',
        'path_15m': 'data/ETHUSDT_15m_last_730d.csv',
        'min_sl_pct': 0.0050,
        'longs_only_only': False,
    },
}

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]


def add_atr_ratio(df):
    out = df.copy()
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low']  - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr14']      = tr.ewm(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False).mean()
    out['atr50_mean'] = out['atr14'].rolling(ATR_MEAN_WINDOW, min_periods=ATR_MEAN_WINDOW).mean()
    out['atr_ratio']  = out['atr14'] / out['atr50_mean'].replace(0, float('nan'))
    return out


def add_vol_ratios(df):
    out = df.copy()
    out['vol_mean50']  = out['volume'].rolling(50, min_periods=50).mean()
    out['vol_ratio50'] = out['volume'] / out['vol_mean50'].replace(0, float('nan'))
    return out


def get_scale(atr_ratio):
    if pd.isna(atr_ratio) or atr_ratio <= 0:
        return 1.0
    return max(SCALE_MIN, min(SCALE_MAX, 1.0 / atr_ratio))


def calculate_sl_tp(entry, direction, low, high, rr=FIXED_RR):
    if direction == 'long':
        sl = low; risk = entry - sl
        if risk <= 0: return None, None
        return sl, entry + rr * risk
    else:
        sl = high; risk = sl - entry
        if risk <= 0: return None, None
        return sl, entry - rr * risk


def run(df, longs_only, min_sl_pct, asset_name, start=None, end=None):
    if start and end:
        start_ts = pd.Timestamp(start, tz='UTC')
        end_ts   = pd.Timestamp(end,   tz='UTC')
        df = df[(df['open_time'] >= start_ts) & (df['open_time'] < end_ts)].reset_index(drop=True)

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
                qty   = position['qty']
                gross = (exit_price - position['entry']) * qty if position['direction'] == 'long' \
                        else (position['entry'] - exit_price) * qty
                fee   = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                pnl   = gross - fee
                equity += pnl
                trades.append({
                    'open_time':  str(position['open_time']),
                    'close_time': str(row['open_time']),
                    'direction':  position['direction'],
                    'entry':      position['entry'],
                    'exit':       exit_price,
                    'reason':     reason,
                    'pnl':        round(pnl, 4),
                    'equity':     round(equity, 4),
                })
                position = None
            continue

        trend = get_trend(row)
        if trend is None: continue
        if longs_only and trend != 'up': continue
        if not is_trend_strong(row): continue
        if not is_pullback_quality(row, trend): continue
        if not is_entry_trigger(row, trend): continue
        if not is_candle_quality(row, trend): continue
        if not is_range_sufficient(row): continue
        if not is_market_efficient(row): continue

        slope = row.get('ema50_slope_pct')
        if slope is not None and not pd.isna(slope) and abs(slope) > MAX_SLOPE_PCT:
            continue

        ts   = pd.Timestamp(row['open_time'])
        hour = ts.hour if ts.tzinfo is None else ts.tz_convert('UTC').hour
        if not (TIME_B_START <= hour < TIME_B_END):
            continue

        direction = 'long' if trend == 'up' else 'short'

        # Volume filter on shorts (Task007 ETH-SHORT-C — apply to all assets)
        if direction == 'short':
            vr50 = row.get('vol_ratio50')
            if vr50 is None or pd.isna(vr50) or vr50 < VOL_MIN_RATIO:
                continue

        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None: continue

        risk_price = abs(entry - sl)
        if risk_price / entry < min_sl_pct: continue

        scale    = get_scale(row.get('atr_ratio', float('nan')))
        risk_usd = equity * RISK_PCT * scale
        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry': entry, 'sl': sl, 'tp': tp,
            'qty': risk_usd / risk_price,
        }
    return trades


def metrics(trades):
    if not trades:
        return {'total_trades': 0, 'profit_factor': 0.0, 'win_rate_pct': 0.0,
                'return_pct': 0.0, 'max_dd_pct': 0.0, 'expectancy_usd': 0.0,
                'longs': 0, 'shorts': 0}
    df   = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]; loss = df[df['pnl'] <= 0]
    gp   = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    pf   = gp / gl if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    ret = (df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    return {
        'total_trades':   len(df),
        'longs':          len(df[df['direction'] == 'long']),
        'shorts':         len(df[df['direction'] == 'short']),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
    }


def window_pf(trades, start, end):
    t = [x for x in trades if start <= x['close_time'] < end]
    if not t: return 0.0
    gp = sum(x['pnl'] for x in t if x['pnl'] > 0)
    gl = abs(sum(x['pnl'] for x in t if x['pnl'] <= 0))
    return round(gp / gl, 3) if gl > 0 else float('inf')


if __name__ == '__main__':
    print(f"\nNEW ASSETS BACKTEST — SOL / BNB / XRP  |  730d  |  fees incluidas\n")
    print(f"Stack: EXP002 pullback + SLOPE_CAP + TIME-B + DYN-B + vol_filter_shorts\n")

    all_results = {}

    # ── Referencia BTC / ETH ──────────────────────────────────────────────────
    print("=" * 70)
    print("REFERENCIA: BTC y ETH (producción actual)")
    print("=" * 70)
    for asset_name, cfg in REFERENCE_CONFIGS.items():
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = add_atr_ratio(prepare_1h(df_1h_raw))
        df_15m = add_vol_ratios(prepare_15m(df_15m_raw))
        df     = align_1h_to_15m(df_15m, df_1h)
        longs_only = cfg.get('longs_only_only', False)
        trades = run(df, longs_only, cfg['min_sl_pct'], asset_name)
        m = metrics(trades)
        print(f"  [{asset_name}] trades={m['total_trades']:>3} (L={m['longs']}/S={m['shorts']})  "
              f"PF={m['profit_factor']:.3f}  WR={m['win_rate_pct']:.1f}%  "
              f"Return={m['return_pct']:+.1f}%  MaxDD={m['max_dd_pct']:.2f}%")
        all_results[asset_name] = {'PROD': {'metrics': m, 'trades': trades}}

    # ── Nuevos activos ────────────────────────────────────────────────────────
    for asset_name, cfg in ASSET_CONFIGS.items():
        print()
        print("=" * 70)
        print(f"  {asset_name}  |  SL_min={cfg['min_sl_pct']*100:.2f}%")
        print("=" * 70)

        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = add_atr_ratio(prepare_1h(df_1h_raw))
        df_15m = add_vol_ratios(prepare_15m(df_15m_raw))
        df     = align_1h_to_15m(df_15m, df_1h)

        asset_results = {}
        for label, longs_only in [('LONGS_ONLY', True), ('LONGS_SHORTS', False)]:
            trades = run(df, longs_only, cfg['min_sl_pct'], asset_name)
            m = metrics(trades)
            asset_results[label] = {'metrics': m, 'trades': trades}
            print(f"  [{label:<12}]  trades={m['total_trades']:>3} (L={m['longs']}/S={m['shorts']})  "
                  f"PF={m['profit_factor']:.3f}  WR={m['win_rate_pct']:.1f}%  "
                  f"Return={m['return_pct']:+.1f}%  MaxDD={m['max_dd_pct']:.2f}%  "
                  f"E=${m['expectancy_usd']:+.2f}")

        best_label = max(asset_results, key=lambda k: asset_results[k]['metrics']['profit_factor'])
        best_trades = asset_results[best_label]['trades']

        print(f"\n  Walk-forward 4×182d  [{best_label}]:")
        windows_pass = 0
        for wid, start, end, label in WINDOWS:
            wpf  = window_pf(best_trades, start, end)
            flag = '✅' if wpf >= 1.0 else '❌'
            print(f"    {wid} {label:<20}  PF={wpf:.3f} {flag}")
            if wpf >= 1.0: windows_pass += 1
        print(f"  Windows pasadas: {windows_pass}/4")

        all_results[asset_name] = asset_results

    # ── Resumen final ─────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  RESUMEN — Decisión de incorporación")
    print("=" * 70)
    criteria_pf   = 1.5   # umbral PF para considerar incorporar
    criteria_win  = 4     # walk-forward windows mínimas
    print(f"  Criterios: PF ≥ {criteria_pf}  |  WF windows ≥ {criteria_win}/4\n")

    for asset_name in ASSET_CONFIGS:
        asset_r = all_results.get(asset_name, {})
        for label, d in asset_r.items():
            m = d['metrics']
            pf = m['profit_factor']
            verdict = '🟢 CANDIDATO' if pf >= criteria_pf else ('🟡 MARGINAL' if pf >= 1.2 else '🔴 RECHAZAR')
            print(f"  {asset_name} {label:<14} PF={pf:.3f}  {verdict}")

    out_path = 'data/backtest_new_assets.json'
    with open(out_path, 'w') as f:
        json.dump(
            {a: {v: r['metrics'] for v, r in vr.items()} for a, vr in all_results.items()},
            f, indent=2, default=str,
        )
    print(f"\nResultados guardados en {out_path}")
