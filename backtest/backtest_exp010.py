"""
EXP010-v2  —  ATR Expansion + EMA200 Regime Filter (Crash Detector)

Hypothesis:
    The Nov 2025 BTC crash (-28%) was preceded and accompanied by two
    measurable structural signals that were present from Oct 10 — a full
    month before the worst losses:

      1. ATR spike: 1h ATR-14 exceeded 2x its rolling 200-bar baseline,
         indicating panic / liquidation / abnormal volatility.
      2. Price below EMA200: macro trend already broken.

    When BOTH conditions hold simultaneously, the system is entering trades
    in a damaged market where EMA20 pullback logic fires on dead-cat bounces.
    The correct response is to pause all entries until the regime normalizes.

    Regime is considered "normalized" when:
      - ATR-14 drops back below 1.5x baseline  (requires sustained calm)
      - AND close is back above EMA200

    We apply this filter to BOTH BTC and ETH since both can enter crash regimes.

Baseline   : EXP009
  BTC longs-only: 99 trades | WR=39.4% | PF=1.297 | Return=+18.45% | MaxDD=7.78%
  ETH both dirs : 207 trades | WR=41.1% | PF=1.375 | Return=+57.95% | MaxDD=10.76%

Parameters:
  ATR_PERIOD       = 14       (1h bars)
  ATR_BASELINE     = 200      (rolling window for "normal" ATR, ~8 days)
  ATR_ENTRY_MULT   = 2.0      (block entries when ATR > 2x baseline)
  ATR_EXIT_MULT    = 1.5      (resume entries when ATR < 1.5x baseline, hysteresis)
  EMA200_PERIOD    = 200      (1h bars)

Decision criteria:
  KEEP if:
    - MaxDD improves on both assets
    - PF maintained or improves on both assets
    - Trade count not below 70% of EXP009 baseline
    - No new losing months introduced
  REVERT if PF drops or new drawdown appears
  CONDITIONAL if improvement is asset-specific
"""

import json
import pandas as pd
import numpy as np

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
from core.logger_v2 import setup_logger, log_open, log_close
from backtest.backtest_v2 import load_data
from core.indicators_v2 import ema as calc_ema

# ── Config ────────────────────────────────────────────────────────────────────
INITIAL_CAPITAL  = 10_000.0
RISK_PCT         = 0.01
MIN_RISK_PRICE   = 1.0
MIN_SL_DIST_PCT  = 0.0015       # EXP007

# ── EXP010 parameters ─────────────────────────────────────────────────────────
ATR_PERIOD      = 14
ATR_BASELINE    = 200           # rolling bars for "normal ATR" reference (~8 days on 1h)
ATR_ENTRY_MULT  = 2.0           # block when ATR > 2x baseline
ATR_EXIT_MULT   = 1.5           # resume when ATR < 1.5x baseline (hysteresis)
EMA200_PERIOD   = 200


# ── Extended 1h prep ─────────────────────────────────────────────────────────

def prepare_1h_exp010(df: pd.DataFrame) -> pd.DataFrame:
    out = prepare_1h(df)
    # ATR-14
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift()).abs(),
        (out['low']  - out['close'].shift()).abs(),
    ], axis=1).max(axis=1)
    out['atr14']      = tr.rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean()
    out['atr_base']   = out['atr14'].rolling(ATR_BASELINE, min_periods=ATR_BASELINE).mean()
    out['atr_ratio']  = out['atr14'] / out['atr_base']
    # EMA200
    out['ema200']     = calc_ema(out['close'], EMA200_PERIOD)
    return out


def align_1h_to_15m_exp010(df_15m: pd.DataFrame, df_1h_prep: pd.DataFrame) -> pd.DataFrame:
    left  = df_15m.sort_values('open_time').reset_index(drop=True)
    right = (
        df_1h_prep[[
            'available_at', 'ema20', 'ema20_slope',
            'ema50', 'ema50_slope_pct', 'er24',
            'close', 'low', 'high',
            'ema200', 'atr14', 'atr_base', 'atr_ratio',
        ]]
        .rename(columns={'close': 'close_1h', 'low': 'low_1h', 'high': 'high_1h'})
        .dropna(subset=['ema20', 'ema20_slope'])
        .sort_values('available_at')
        .reset_index(drop=True)
    )
    return pd.merge_asof(
        left, right,
        left_on='open_time', right_on='available_at',
        direction='backward',
    )


# ── Regime state machine ──────────────────────────────────────────────────────

def is_regime_blocked(row, currently_blocked: bool) -> bool:
    """
    Stateful regime filter with hysteresis.
    Enters blocked state  : ATR_ratio > ATR_ENTRY_MULT AND price < EMA200
    Exits  blocked state  : ATR_ratio < ATR_EXIT_MULT  AND price > EMA200
    While blocked: no new entries allowed (existing positions managed normally).
    """
    atr_ratio = row.get('atr_ratio')
    ema200    = row.get('ema200')
    close_1h  = row.get('close_1h')

    if pd.isna(atr_ratio) or pd.isna(ema200) or pd.isna(close_1h):
        return currently_blocked

    price_below_ema200 = close_1h < ema200

    if not currently_blocked:
        # Enter blocked: spike AND price already broken
        if atr_ratio > ATR_ENTRY_MULT and price_below_ema200:
            return True
        return False
    else:
        # Exit blocked: ATR calmed AND price recovered (hysteresis)
        if atr_ratio < ATR_EXIT_MULT and not price_below_ema200:
            return False
        return True


# ── Core backtest loop ────────────────────────────────────────────────────────

def run_flat(path_1h: str, path_15m: str, asset: str, longs_only: bool = False) -> dict:
    log_file = f'logs/exp010_{asset}.log'
    logger   = setup_logger(f'exp010_{asset}', log_file=log_file)

    mode = 'LONGS ONLY' if longs_only else 'BOTH DIRECTIONS'
    logger.info(f"\n{'='*60}")
    logger.info(f"EXP010-v2  |  {asset}  |  {mode}")
    logger.info(f"Filters: EXP009 + ATR regime gate (ATR>2x + price<EMA200)")
    logger.info(f"{'='*60}\n")

    df_1h_raw, df_15m_raw = load_data(path_1h, path_15m)
    df_1h_prep  = prepare_1h_exp010(df_1h_raw)
    df_15m_prep = prepare_15m(df_15m_raw)
    df          = align_1h_to_15m_exp010(df_15m_prep, df_1h_prep)

    equity         = INITIAL_CAPITAL
    position       = None
    trades         = []
    equity_curve   = []
    regime_blocked = False
    rej_regime     = 0
    rej_direction  = 0

    # Track regime transitions for the log
    last_regime_state = False

    for _, row in df.iterrows():
        ts = row['open_time']

        # Update regime state
        regime_blocked = is_regime_blocked(row, regime_blocked)
        if regime_blocked != last_regime_state:
            state_str = 'BLOCKED (ATR spike + price < EMA200)' if regime_blocked else 'OPEN (regime normalized)'
            logger.info(f"[REGIME] {ts}  →  {state_str}  |  ATR_ratio={row.get('atr_ratio', float('nan')):.2f}  close={row.get('close_1h', 0):.0f}  EMA200={row.get('ema200', 0):.0f}")
            last_regime_state = regime_blocked

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result
                pnl = (
                    (exit_price - position['entry']) * position['qty']
                    if position['direction'] == 'long'
                    else (position['entry'] - exit_price) * position['qty']
                )
                equity += pnl
                log_close(logger, position['direction'], position['entry'], exit_price, reason, pnl, equity)
                trades.append({
                    'open_ts':     position['open_ts'],
                    'close_ts':    str(ts),
                    'direction':   position['direction'],
                    'entry':       position['entry'],
                    'exit':        exit_price,
                    'sl':          position['sl'],
                    'tp':          position['tp'],
                    'sl_dist_pct': position['sl_dist_pct'],
                    'reason':      reason,
                    'pnl':         round(pnl, 4),
                    'equity':      round(equity, 4),
                })
                position = None
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # ── EXP010: regime gate (no new entries when blocked) ─────────────────
        if regime_blocked:
            rej_regime += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # ── EXP002 + EXP003 filters ───────────────────────────────────────────
        trend = get_trend(row)
        if trend is None:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue
        if not is_trend_strong(row):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue
        if not is_pullback_quality(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue
        if not is_entry_trigger(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue
        if not is_candle_quality(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue
        if not is_range_sufficient(row):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue
        if not is_market_efficient(row):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        entry     = row['close']
        direction = 'long' if trend == 'up' else 'short'

        # ── EXP009: longs only for BTC ────────────────────────────────────────
        if longs_only and direction == 'short':
            rej_direction += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_price = abs(entry - sl)
        if risk_price < MIN_RISK_PRICE:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        sl_dist_pct = risk_price / entry
        if sl_dist_pct < MIN_SL_DIST_PCT:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_usd = equity * RISK_PCT
        qty      = risk_usd / risk_price
        position = {
            'direction':   direction,
            'entry':       entry,
            'sl':          sl,
            'tp':          tp,
            'qty':         qty,
            'open_ts':     str(ts),
            'sl_dist_pct': round(sl_dist_pct * 100, 4),
        }
        log_open(logger, direction, ts, entry, sl, tp)
        equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})

    if position is not None:
        last_row   = df.iloc[-1]
        exit_price = last_row['close']
        pnl = (
            (exit_price - position['entry']) * position['qty']
            if position['direction'] == 'long'
            else (position['entry'] - exit_price) * position['qty']
        )
        equity += pnl
        log_close(logger, position['direction'], position['entry'], exit_price, 'END', pnl, equity)
        trades.append({
            'open_ts': position['open_ts'], 'close_ts': str(last_row['open_time']),
            'direction': position['direction'], 'entry': position['entry'],
            'exit': exit_price, 'sl': position['sl'], 'tp': position['tp'],
            'sl_dist_pct': position['sl_dist_pct'], 'reason': 'END',
            'pnl': round(pnl, 4), 'equity': round(equity, 4),
        })

    logger.info(f"\nRejected by regime filter  : {rej_regime}")
    logger.info(f"Rejected by direction filter: {rej_direction}")

    return {
        'asset': asset, 'trades': trades,
        'equity_curve': equity_curve,
        'final_equity': round(equity, 4),
        'rej_regime': rej_regime,
        'rej_direction': rej_direction,
    }


# ── Metrics helpers ───────────────────────────────────────────────────────────

def metrics(trades: list) -> dict:
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    wins = df[df['pnl'] > 0]
    gl   = abs(df[df['pnl'] <= 0]['pnl'].sum())
    gp   = wins['pnl'].sum() if len(wins) else 0.0
    eq   = df['equity'].values
    peak, max_dd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak * 100)
    return {
        'total_trades':   len(df),
        'win_rate_pct':   round(len(wins) / len(df) * 100, 1),
        'net_pnl':        round(df['pnl'].sum(), 2),
        'return_pct':     round(df['pnl'].sum() / INITIAL_CAPITAL * 100, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(gp / gl if gl > 0 else float('inf'), 3),
        'expectancy_usd': round(df['pnl'].mean(), 2),
    }


def monthly(trades: list) -> list:
    if not trades:
        return []
    df = pd.DataFrame(trades)
    df['close_ts'] = pd.to_datetime(df['close_ts'])
    df['month']    = df['close_ts'].dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        wins = g[g['pnl'] > 0]
        gl   = abs(g[g['pnl'] <= 0]['pnl'].sum())
        gp   = wins['pnl'].sum() if len(wins) else 0.0
        pf   = gp / gl if gl > 0 else float('inf')
        rows.append({
            'month': str(month), 'trades': len(g),
            'win_rate_pct': round(len(wins) / len(g) * 100, 1),
            'net_pnl': round(g['pnl'].sum(), 2),
            'profit_factor': round(pf, 3),
        })
    return rows


# ── Baselines (from EXP009) ───────────────────────────────────────────────────

BASELINE = {
    'BTC': {
        'total_trades': 99, 'win_rate_pct': 39.4, 'return_pct': 18.45,
        'max_dd_pct': 7.78, 'profit_factor': 1.297, 'expectancy_usd': 18.63,
        'monthly': {
            '2025-09': -100.00, '2025-10': 278.74, '2025-11': -697.14,
            '2025-12': 272.77,  '2026-01': 999.21, '2026-02': 92.45, '2026-03': 998.52,
        },
    },
    'ETH': {
        'total_trades': 207, 'win_rate_pct': 41.1, 'return_pct': 57.95,
        'max_dd_pct': 10.76, 'profit_factor': 1.375, 'expectancy_usd': 27.99,
        'monthly': {
            '2025-09': -299.90, '2025-10': 1971.19, '2025-11': 561.32,
            '2025-12': -279.11, '2026-01': 814.04,  '2026-02': 2459.05, '2026-03': 568.01,
        },
    },
}


def print_report(asset: str, result: dict, m: dict, mo: list) -> None:
    b = BASELINE[asset]
    print(f"\n{'='*65}")
    print(f"EXP010-v2  |  {asset}  |  ATR regime filter + {'longs only' if asset == 'BTC' else 'both dirs'}")
    print(f"{'='*65}")

    print(f"\n{'Metric':<22} {'EXP009 base':>13} {'EXP010':>13} {'Delta':>10}")
    print(f"{'-'*60}")
    fields = [
        ('Trades',        'total_trades',   '{:d}'),
        ('Win rate %',    'win_rate_pct',    '{:.1f}'),
        ('Return %',      'return_pct',      '{:+.2f}'),
        ('Max DD %',      'max_dd_pct',      '{:.2f}'),
        ('Profit factor', 'profit_factor',   '{:.3f}'),
        ('Expectancy $',  'expectancy_usd',  '{:+.2f}'),
    ]
    for label, key, fmt in fields:
        bv   = b[key]
        new  = m[key]
        delta = new - bv
        sign  = '+' if delta >= 0 else ''
        print(f"  {label:<20} {fmt.format(bv):>13} {fmt.format(new):>13}  {sign}{fmt.format(delta):>8}")

    print(f"\n  Blocked by regime filter : {result['rej_regime']} candles")
    print(f"  Final equity             : ${result['final_equity']:,.2f}")

    print(f"\n── Monthly breakdown ────────────────────────────────────────")
    print(f"  {'Month':<10} {'Trades':>6} {'WR':>6} {'PnL':>10} {'PF':>7}  {'vs EXP009':>10}")
    print(f"  {'-'*58}")
    for row in mo:
        pf_str = f"{row['profit_factor']:.3f}" if row['profit_factor'] != float('inf') else "  inf"
        flag   = '  *' if row['profit_factor'] < 1.0 else ''
        base_pnl = b['monthly'].get(row['month'], 0.0)
        delta_pnl = row['net_pnl'] - base_pnl
        print(f"  {row['month']:<10} {row['trades']:>6} {row['win_rate_pct']:>5.1f}% {row['net_pnl']:>+9.2f}  {pf_str}{flag}  {delta_pnl:>+9.2f}")
    print(f"{'='*65}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

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
        result = run_flat(cfg['path_1h'], cfg['path_15m'], cfg['name'], cfg['longs_only'])
        m      = metrics(result['trades'])
        mo     = monthly(result['trades'])
        print_report(cfg['name'], result, m, mo)
        all_results[cfg['name']] = {
            'metrics': m, 'monthly': mo,
            'final_equity': result['final_equity'],
            'rej_regime':   result['rej_regime'],
        }

    out_path = 'data/backtest_exp010.json'
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to {out_path}")
