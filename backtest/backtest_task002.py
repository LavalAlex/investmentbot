"""
TASK 002 — Dynamic Position Sizing por volatilidad

Base: EXP019 SLOPE_CAP (0.20%). Task001 reverted — base unchanged.

Hypothesis:
    Scaling position size inversely with ATR ratio (ATR14 / ATR50_mean on 1h)
    reduces MaxDD in high-volatility periods without degrading PF.
    Same edge, smoother equity curve.

Formula:
    scale = clamp(1 / atr_ratio, scale_min, scale_max)
    risk_usd = equity * 0.01 * scale

Variants:
    BASE   : scale=1.0 fixed (EXP019 reference)
    DYN-A  : clamp(1/atr_ratio, 0.5, 1.5)   wide range
    DYN-B  : clamp(1/atr_ratio, 0.6, 1.2)   moderate
    DYN-C  : clamp(1/atr_ratio, 0.5, 1.0)   only reduce, never increase
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
from backtest.backtest_v2 import load_data

INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
FEE_PER_SIDE_PCT = 0.0005
MAX_SLOPE_PCT    = 0.20

ATR_PERIOD       = 14
ATR_MEAN_WINDOW  = 50

VARIANTS = {
    'BASE':  {'scale_min': 1.0, 'scale_max': 1.0},
    'DYN-A': {'scale_min': 0.5, 'scale_max': 1.5},
    'DYN-B': {'scale_min': 0.6, 'scale_max': 1.2},
    'DYN-C': {'scale_min': 0.5, 'scale_max': 1.0},
}

WINDOWS = [
    ('W1', '2024-04-27', '2024-10-25', 'Bull 2024'),
    ('W2', '2024-10-25', '2025-04-24', 'ATH 2024-25'),
    ('W3', '2025-04-24', '2025-10-21', 'Recovery 2025'),
    ('W4', '2025-10-21', '2026-04-19', 'Bear 2025-26'),
]


def add_atr_ratio(df_1h: pd.DataFrame) -> pd.DataFrame:
    out = df_1h.copy()
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low']  - out['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    out['atr14']      = tr.ewm(com=ATR_PERIOD - 1, min_periods=ATR_PERIOD, adjust=False).mean()
    out['atr50_mean'] = out['atr14'].rolling(ATR_MEAN_WINDOW, min_periods=ATR_MEAN_WINDOW).mean()
    out['atr_ratio']  = out['atr14'] / out['atr50_mean'].replace(0, float('nan'))
    return out


def align_with_atr(df_15m, df_1h_prep):
    from core.strategy_pullback import align_1h_to_15m
    df = align_1h_to_15m(df_15m, df_1h_prep)
    right = (
        df_1h_prep[['available_at', 'atr_ratio']]
        .dropna(subset=['atr_ratio'])
        .sort_values('available_at')
        .reset_index(drop=True)
    )
    df = df.sort_values('open_time').reset_index(drop=True)
    df = pd.merge_asof(df, right, left_on='open_time', right_on='available_at',
                       direction='backward', suffixes=('', '_dup'))
    return df


def calculate_sl_tp(entry, direction, low, high, rr=2.0):
    if direction == 'long':
        sl = low; risk = entry - sl
        if risk <= 0: return None, None
        return sl, entry + rr * risk
    else:
        sl = high; risk = sl - entry
        if risk <= 0: return None, None
        return sl, entry - rr * risk


def get_scale(atr_ratio, vcfg):
    if vcfg['scale_min'] == vcfg['scale_max'] == 1.0:
        return 1.0
    if pd.isna(atr_ratio) or atr_ratio <= 0:
        return 1.0
    raw = 1.0 / atr_ratio
    return max(vcfg['scale_min'], min(vcfg['scale_max'], raw))


def run(df, longs_only, min_sl_pct, vcfg, start=None, end=None):
    if start and end:
        df = df[(df['open_time'] >= start) & (df['open_time'] < end)].reset_index(drop=True)
    equity = INITIAL_CAPITAL
    position = None
    trades = []

    for _, row in df.iterrows():
        if pd.isna(row.get('ema20')) or pd.isna(row.get('er24')):
            continue

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                qty = position['qty']
                gross = (exit_price - position['entry']) * qty if position['direction'] == 'long' \
                        else (position['entry'] - exit_price) * qty
                fee = (position['entry'] + exit_price) * qty * FEE_PER_SIDE_PCT
                net_pnl = gross - fee
                equity += net_pnl
                trades.append({
                    'open_time':  str(position['open_time']),
                    'close_time': str(row['open_time']),
                    'direction':  position['direction'],
                    'entry':      position['entry'],
                    'exit':       exit_price,
                    'reason':     reason,
                    'scale':      position['scale'],
                    'atr_ratio':  position['atr_ratio'],
                    'gross_pnl':  round(gross, 4),
                    'fee_usd':    round(fee, 4),
                    'pnl':        round(net_pnl, 4),
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
        if not pd.isna(slope) and abs(slope) > MAX_SLOPE_PCT:
            continue

        direction = 'long' if trend == 'up' else 'short'
        entry = row['close']
        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None: continue
        risk_price = abs(entry - sl)
        if risk_price / entry < min_sl_pct: continue

        atr_ratio_val = row.get('atr_ratio', float('nan'))
        scale = get_scale(atr_ratio_val, vcfg)
        risk_usd = equity * RISK_PCT * scale

        position = {
            'open_time': row['open_time'],
            'direction': direction,
            'entry': entry, 'sl': sl, 'tp': tp,
            'qty': risk_usd / risk_price,
            'scale': round(scale, 3),
            'atr_ratio': round(float(atr_ratio_val), 3) if not pd.isna(atr_ratio_val) else None,
        }
    return trades


def metrics(trades):
    if not trades: return {'total_trades': 0}
    df = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]; loss = df[df['pnl'] <= 0]
    gp = wins['pnl'].sum(); gl = abs(loss['pnl'].sum())
    pf = gp / gl if gl > 0 else float('inf')
    peak, max_dd, eq = INITIAL_CAPITAL, 0.0, INITIAL_CAPITAL
    for p in df['pnl']:
        eq += p; peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)
    ret = (df['equity'].iloc[-1] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    monthly_rets = df.groupby(df['close_time'].str[:7])['pnl'].sum() / INITIAL_CAPITAL * 100
    sharpe = monthly_rets.mean() / monthly_rets.std() * (12 ** 0.5) if monthly_rets.std() > 0 else 0
    calmar = ret / max_dd if max_dd > 0 else 0
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'return_pct':     round(ret, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(pf, 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
        'total_fees_usd': round(df['fee_usd'].sum(), 2),
        'sharpe':         round(sharpe, 3),
        'calmar':         round(calmar, 3),
        'avg_scale':      round(df['scale'].mean(), 3),
    }


def wf_combined_pf(btc_trades, eth_trades, start, end):
    all_t = [t for t in btc_trades + eth_trades if start <= t['close_time'] < end]
    if not all_t: return 0.0
    gp = sum(t['pnl'] for t in all_t if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in all_t if t['pnl'] <= 0))
    return round(gp / gl, 3) if gl > 0 else float('inf')


ASSET_CONFIGS = {
    'BTC': {'path_1h': 'data/BTCUSDT_1h_last_740d.csv', 'path_15m': 'data/BTCUSDT_15m_last_730d.csv',
            'longs_only': True,  'min_sl_pct': 0.0030, 'label': 'BTC/USDT', 'base_pf': 1.344},
    'ETH': {'path_1h': 'data/ETHUSDT_1h_last_740d.csv', 'path_15m': 'data/ETHUSDT_15m_last_730d.csv',
            'longs_only': False, 'min_sl_pct': 0.0050, 'label': 'ETH/USDT', 'base_pf': 1.318},
}


if __name__ == '__main__':
    print(f"\nTASK002 — Dynamic Sizing  |  SLOPE_CAP=0.20%  |  730d con fees\n")
    all_results = {}

    for asset_name, cfg in ASSET_CONFIGS.items():
        print(f"[{asset_name}] Preparando datos...", flush=True)
        df_1h_raw, df_15m_raw = load_data(cfg['path_1h'], cfg['path_15m'])
        df_1h  = add_atr_ratio(prepare_1h(df_1h_raw))
        df_15m = prepare_15m(df_15m_raw)
        df     = align_with_atr(df_15m, df_1h)

        asset_results = {}
        for vname, vcfg in VARIANTS.items():
            trades = run(df, cfg['longs_only'], cfg['min_sl_pct'], vcfg)
            m = metrics(trades)
            asset_results[vname] = {'metrics': m, 'trades': trades}
            print(f"  [{vname:6}] trades={m['total_trades']:>3}  PF={m['profit_factor']:.3f}  "
                  f"Return={m['return_pct']:+.1f}%  MaxDD={m['max_dd_pct']:.1f}%  "
                  f"Sharpe={m['sharpe']:.2f}  scale_avg={m.get('avg_scale',1):.2f}×")
        all_results[asset_name] = asset_results

        # Report
        w = 10
        print(f"\n{'='*75}")
        print(f"  TASK002  |  {cfg['label']}  |  BASE PF={cfg['base_pf']:.3f}")
        print(f"{'='*75}")
        print(f"  {'Métrica':<20}" + ''.join(f"  {v:>{w}}" for v in VARIANTS))
        print(f"  {'-'*65}")
        for label, key, fmt in [
            ('Trades',       'total_trades',   '{:d}'),
            ('Win rate %',   'win_rate_pct',   '{:.1f}'),
            ('Return %',     'return_pct',     '{:+.2f}'),
            ('Max DD %',     'max_dd_pct',     '{:.2f}'),
            ('Profit factor','profit_factor',  '{:.3f}'),
            ('Sharpe',       'sharpe',         '{:.3f}'),
            ('Calmar',       'calmar',         '{:.3f}'),
            ('Avg scale',    'avg_scale',      '{:.3f}×'),
        ]:
            row = f"  {label:<20}"
            for v in VARIANTS:
                val = asset_results[v]['metrics'].get(key, 0)
                row += f"  {fmt.format(val):>{w}}"
            print(row)
        print()

    # Walk-forward
    print(f"\n{'='*75}")
    print(f"  TASK002  |  Walk-forward combinado BTC+ETH (4×182d)")
    print(f"{'='*75}")
    print(f"  {'Ventana':<6}  {'Período':<22}" + ''.join(f"  {v:>12}" for v in VARIANTS))
    print(f"  {'-'*72}")
    for wid, start, end, label in WINDOWS:
        row = f"  {wid:<6}  {label:<22}"
        for vname in VARIANTS:
            btc_t = all_results.get('BTC', {}).get(vname, {}).get('trades', [])
            eth_t = all_results.get('ETH', {}).get(vname, {}).get('trades', [])
            cpf = wf_combined_pf(btc_t, eth_t, start, end)
            flag = '✅' if cpf >= 1.0 else '❌'
            row += f"  {cpf:>9.3f} {flag}"
        print(row)

    out_path = 'data/backtest_task002.json'
    with open(out_path, 'w') as f:
        json.dump({a: {v: r['metrics'] for v, r in vr.items()}
                   for a, vr in all_results.items()}, f, indent=2, default=str)
    print(f"\nResultados guardados en {out_path}")
