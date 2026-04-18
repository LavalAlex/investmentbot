"""
EXP006-v2 — Walk-Forward Robustness Validation

Strategy : EXP002-v2 pullback continuation (unchanged, zero parameter tuning)
Purpose  : Test whether the system edge is stable over time or regime-dependent.

Walk-forward structure:
  Since there is no optimization, "train" serves only as indicator warm-up.
  The system runs continuously across the full data range. Performance is then
  broken down by sequential 3-month evaluation windows.

  BTC data (12 months, combined OOS + IS):
    Mar 2025 – Mar 2026  →  4 windows × 3 months
    W1: Apr–Jun 2025   (OOS first half)
    W2: Jul–Sep 2025   (OOS second half)
    W3: Oct–Dec 2025   (IS first half)
    W4: Jan–Mar 2026   (IS second half)

  ETH data (6 months IS only):
    Sep 2025 – Mar 2026  →  2 windows × 3 months
    W1: Oct–Dec 2025
    W2: Jan–Mar 2026

Evaluation criteria:
  - PF > 1 in majority of windows       → stable edge
  - Consistent WR (±5pp across windows) → not regime-gated
  - No single window dominant           → not period-specific luck
  - DD bounded in worst window           → risk under control

Constraints:
  - No parameter changes at any window boundary
  - Equity is continuous (sizing evolves with account)
"""

import json
import pandas as pd
import numpy as np

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend,
    is_trend_strong,
    is_pullback_quality,
    is_entry_trigger,
    is_candle_quality,
    is_range_sufficient,
)
from core.trade_logic import calculate_sl_tp, check_exit
from core.logger_v2 import setup_logger, log_open, log_close
from backtest.backtest_v2 import load_data, compute_metrics

# ── Config (identical to EXP002) ─────────────────────────────────────────────
INITIAL_CAPITAL = 10_000.0
RISK_PCT        = 0.01
MIN_RISK_PRICE  = 1.0


# ── Window definition ─────────────────────────────────────────────────────────

def assign_window(ts, windows: list[tuple]) -> int | None:
    """Return the index (0-based) of the window [start, end) that ts falls in, or None."""
    if pd.isna(ts):
        return None
    for i, (start, end) in enumerate(windows):
        if start <= ts < end:
            return i
    return None


# ── Per-window metrics ────────────────────────────────────────────────────────

def compute_window_metrics(
    window_trades: list,
    equity_curve: list,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    equity_at_start: float,
) -> dict:
    """Compute PF, WR, return, and max DD for one window."""
    if not window_trades:
        return {
            'trades': 0,
            'win_rate_pct': None,
            'return_pct': None,
            'max_dd_pct': None,
            'profit_factor': None,
            'expectancy_usd': None,
            'gross_profit': 0.0,
            'gross_loss': 0.0,
        }

    df = pd.DataFrame(window_trades)
    wins   = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]

    gross_profit = wins['pnl'].sum() if len(wins) else 0.0
    gross_loss   = abs(losses['pnl'].sum()) if len(losses) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    win_rate      = len(wins) / len(df) * 100
    expectancy    = df['pnl'].mean()
    net_pnl       = df['pnl'].sum()
    return_pct    = net_pnl / equity_at_start * 100

    # Max drawdown within window from equity curve
    eq_df = pd.DataFrame(equity_curve)
    eq_df['ts'] = pd.to_datetime(eq_df['ts'])
    mask = (eq_df['ts'] >= window_start) & (eq_df['ts'] < window_end)
    window_eq = eq_df.loc[mask, 'equity'].values

    max_dd = 0.0
    if len(window_eq) > 0:
        peak = window_eq[0]
        for eq in window_eq:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

    return {
        'trades':        len(df),
        'win_rate_pct':  round(win_rate, 1),
        'return_pct':    round(return_pct, 2),
        'max_dd_pct':    round(max_dd, 2),
        'profit_factor': round(profit_factor, 3),
        'expectancy_usd': round(expectancy, 2),
        'gross_profit':  round(gross_profit, 2),
        'gross_loss':    round(gross_loss, 2),
    }


# ── Core backtest loop (EXP002 logic) ────────────────────────────────────────

def run_walkforward(
    path_1h: str,
    path_15m: str,
    windows: list[tuple],
    asset: str,
    path_1h_extra: str = None,
    path_15m_extra: str = None,
) -> dict:
    """
    Run EXP002 strategy on the full dataset (or combined datasets) and
    split trades into evaluation windows.

    If path_1h_extra / path_15m_extra are provided, those datasets are
    prepended (earlier data) to form a continuous combined range.
    """
    log_file = f'logs/exp006_{asset}.log'
    logger   = setup_logger(f'exp006_{asset}', log_file=log_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"EXP006-v2  |  {asset}  |  WALK-FORWARD")
    logger.info(f"Strategy   : EXP002-v2 (unchanged)")
    logger.info(f"Windows    : {len(windows)} × 3-month evaluation periods")
    logger.info(f"{'='*60}\n")

    # Load and optionally combine data
    df_1h_main, df_15m_main = load_data(path_1h, path_15m)

    if path_1h_extra and path_15m_extra:
        df_1h_extra, df_15m_extra = load_data(path_1h_extra, path_15m_extra)
        df_1h  = pd.concat([df_1h_extra, df_1h_main]).drop_duplicates('open_time').sort_values('open_time').reset_index(drop=True)
        df_15m = pd.concat([df_15m_extra, df_15m_main]).drop_duplicates('open_time').sort_values('open_time').reset_index(drop=True)
    else:
        df_1h  = df_1h_main
        df_15m = df_15m_main

    df_1h_prep  = prepare_1h(df_1h)
    df_15m_prep = prepare_15m(df_15m)
    df          = align_1h_to_15m(df_15m_prep, df_1h_prep)

    # Assign each 15m bar to a window index (for equity tracking)
    win_starts = [w[0] for w in windows]
    win_ends   = [w[1] for w in windows]
    overall_start = windows[0][0]
    overall_end   = windows[-1][1]

    equity       = INITIAL_CAPITAL
    position     = None
    trades       = []
    equity_curve = []

    rejected = {'no_signal': 0, 'trend': 0, 'pullback': 0, 'candle': 0, 'range': 0}

    for _, row in df.iterrows():
        ts = row['open_time']

        if position is not None:
            result = check_exit(position['direction'], position['sl'], position['tp'], row)
            if result is not None:
                reason, exit_price = result

                if position['direction'] == 'long':
                    pnl = (exit_price - position['entry']) * position['qty']
                else:
                    pnl = (position['entry'] - exit_price) * position['qty']

                equity += pnl
                log_close(logger, position['direction'], position['entry'], exit_price, reason, pnl, equity)

                trades.append({
                    'open_ts':   position['open_ts'],
                    'close_ts':  str(ts),
                    'direction': position['direction'],
                    'entry':     position['entry'],
                    'exit':      exit_price,
                    'sl':        position['sl'],
                    'tp':        position['tp'],
                    'reason':    reason,
                    'pnl':       round(pnl, 4),
                    'equity':    round(equity, 4),
                })
                position = None

            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # Entry checks — EXP002 filters
        trend = get_trend(row)
        if trend is None:
            rejected['no_signal'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_trend_strong(row):
            rejected['trend'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_pullback_quality(row, trend):
            rejected['pullback'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_entry_trigger(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_candle_quality(row, trend):
            rejected['candle'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_range_sufficient(row):
            rejected['range'] += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        entry     = row['close']
        direction = 'long' if trend == 'up' else 'short'

        sl, tp = calculate_sl_tp(entry, direction, row['low'], row['high'])
        if sl is None:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_price = abs(entry - sl)
        if risk_price < MIN_RISK_PRICE:
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        risk_usd = equity * RISK_PCT
        qty      = risk_usd / risk_price

        position = {
            'direction': direction,
            'entry':     entry,
            'sl':        sl,
            'tp':        tp,
            'qty':       qty,
            'open_ts':   str(ts),
        }

        log_open(logger, direction, ts, entry, sl, tp)
        equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})

    if position is not None:
        last_row   = df.iloc[-1]
        exit_price = last_row['close']
        if position['direction'] == 'long':
            pnl = (exit_price - position['entry']) * position['qty']
        else:
            pnl = (position['entry'] - exit_price) * position['qty']
        equity += pnl
        log_close(logger, position['direction'], position['entry'], exit_price, 'END', pnl, equity)
        trades.append({
            'open_ts':   position['open_ts'],
            'close_ts':  str(last_row['open_time']),
            'direction': position['direction'],
            'entry':     position['entry'],
            'exit':      exit_price,
            'sl':        position['sl'],
            'tp':        position['tp'],
            'reason':    'END',
            'pnl':       round(pnl, 4),
            'equity':    round(equity, 4),
        })

    # ── Split trades into windows ────────────────────────────────────────────
    trades_df = pd.DataFrame(trades)
    if len(trades_df):
        trades_df['close_ts'] = pd.to_datetime(trades_df['close_ts'])
        trades_df['window']   = trades_df['close_ts'].apply(
            lambda ts: assign_window(ts, windows)
        )

    # Build equity lookup for window-start equity
    eq_df = pd.DataFrame(equity_curve)
    eq_df['ts'] = pd.to_datetime(eq_df['ts'])

    window_results = []
    for i, (wstart, wend) in enumerate(windows):
        label = f"W{i+1}: {wstart.strftime('%b %Y')} – {wend.strftime('%b %Y')}"

        # Equity at window start = last equity value before window begins
        pre_mask = eq_df['ts'] < wstart
        if pre_mask.any():
            eq_at_start = eq_df.loc[pre_mask, 'equity'].iloc[-1]
        else:
            eq_at_start = INITIAL_CAPITAL

        if len(trades_df):
            w_trades = trades_df[trades_df['window'] == i].to_dict(orient='records')
        else:
            w_trades = []

        m = compute_window_metrics(w_trades, equity_curve, wstart, wend, eq_at_start)
        m['window'] = label
        m['equity_start'] = round(eq_at_start, 2)
        window_results.append(m)

        pf_str = f"{m['profit_factor']:.3f}" if m['profit_factor'] is not None else "—"
        ret_str = f"{m['return_pct']:+.1f}%" if m['return_pct'] is not None else "—"
        dd_str = f"{m['max_dd_pct']:.1f}%" if m['max_dd_pct'] is not None else "—"
        logger.info(
            f"{label:30s}  trades={m['trades']:3d}  WR={m['win_rate_pct'] or 0:.0f}%  "
            f"ret={ret_str:>7s}  DD={dd_str:>6s}  PF={pf_str}"
        )

    return {
        'asset':          asset,
        'windows':        window_results,
        'all_trades':     trades,
        'equity_curve':   equity_curve,
        'final_equity':   round(equity, 4),
        'rejected':       rejected,
    }


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_walkforward_summary(asset: str, result: dict) -> None:
    windows = result['windows']
    print(f"\n{'='*75}")
    print(f"EXP006-v2  |  {asset}  |  WALK-FORWARD SUMMARY")
    print(f"{'='*75}")
    print(f"{'Window':<32} {'Trades':>6} {'WR':>6} {'Return':>8} {'MaxDD':>7} {'PF':>7}")
    print(f"{'-'*75}")

    pf_vals = []
    for w in windows:
        if w['trades'] == 0:
            print(f"{w['window']:<32} {'0':>6} {'—':>6} {'—':>8} {'—':>7} {'—':>7}")
            continue
        pf   = w['profit_factor']
        ret  = w['return_pct']
        dd   = w['max_dd_pct']
        wr   = w['win_rate_pct']
        pf_vals.append(pf)
        flag = '  *' if pf < 1.0 else ''
        print(
            f"{w['window']:<32} {w['trades']:>6} {wr:>5.1f}% {ret:>+7.1f}% {dd:>6.1f}% {pf:>7.3f}{flag}"
        )

    print(f"{'-'*75}")
    if pf_vals:
        profitable = sum(1 for p in pf_vals if p > 1.0)
        print(f"PF > 1.0   : {profitable}/{len(pf_vals)} windows")
        print(f"PF range   : {min(pf_vals):.3f} – {max(pf_vals):.3f}")
        print(f"PF median  : {sorted(pf_vals)[len(pf_vals)//2]:.3f}")
        pf_std = float(np.std(pf_vals)) if len(pf_vals) > 1 else 0.0
        print(f"PF std dev : {pf_std:.3f}  (lower = more consistent)")

        worst = min(windows, key=lambda w: w['profit_factor'] if w['profit_factor'] is not None else float('inf'))
        best  = max(windows, key=lambda w: w['profit_factor'] if w['profit_factor'] is not None else 0.0)
        print(f"Best window : {best['window']}  PF={best['profit_factor']:.3f}  ret={best['return_pct']:+.1f}%")
        print(f"Worst window: {worst['window']}  PF={worst['profit_factor']:.3f}  ret={worst['return_pct']:+.1f}%")

        wr_vals = [w['win_rate_pct'] for w in windows if w['win_rate_pct'] is not None]
        if wr_vals:
            print(f"WR range   : {min(wr_vals):.1f}% – {max(wr_vals):.1f}%  (spread={max(wr_vals)-min(wr_vals):.1f}pp)")
    print(f"{'='*75}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':

    # ── BTC: 4 windows across 12 months ──────────────────────────────────────
    # Data: OOS (Mar–Sep 2025) + IS (Sep–Mar 2026) combined
    # Windows defined by trade close_ts (tz-aware, UTC)
    BTC_WINDOWS = [
        (pd.Timestamp('2025-04-01', tz='UTC'), pd.Timestamp('2025-07-01', tz='UTC')),  # W1: Apr–Jun 2025
        (pd.Timestamp('2025-07-01', tz='UTC'), pd.Timestamp('2025-10-01', tz='UTC')),  # W2: Jul–Sep 2025
        (pd.Timestamp('2025-10-01', tz='UTC'), pd.Timestamp('2026-01-01', tz='UTC')),  # W3: Oct–Dec 2025
        (pd.Timestamp('2026-01-01', tz='UTC'), pd.Timestamp('2026-04-01', tz='UTC')),  # W4: Jan–Mar 2026
    ]

    btc_result = run_walkforward(
        path_1h       = 'data/BTCUSDT_1h_last_200d.csv',
        path_15m      = 'data/BTCUSDT_15m_last_180d.csv',
        path_1h_extra = 'data/BTCUSDT_1h_oos_200d.csv',
        path_15m_extra= 'data/BTCUSDT_15m_oos_180d.csv',
        windows       = BTC_WINDOWS,
        asset         = 'BTC',
    )
    print_walkforward_summary('BTC', btc_result)

    # ── ETH: 2 windows across 6 months ───────────────────────────────────────
    # Data: IS only (Sep 2025 – Mar 2026)
    ETH_WINDOWS = [
        (pd.Timestamp('2025-10-01', tz='UTC'), pd.Timestamp('2026-01-01', tz='UTC')),  # W1: Oct–Dec 2025
        (pd.Timestamp('2026-01-01', tz='UTC'), pd.Timestamp('2026-04-01', tz='UTC')),  # W2: Jan–Mar 2026
    ]

    eth_result = run_walkforward(
        path_1h  = 'data/ETHUSDT_1h_last_200d.csv',
        path_15m = 'data/ETHUSDT_15m_last_180d.csv',
        windows  = ETH_WINDOWS,
        asset    = 'ETH',
    )
    print_walkforward_summary('ETH', eth_result)

    # ── Combined cross-asset view ─────────────────────────────────────────────
    print(f"\n{'='*75}")
    print(f"EXP006-v2  |  COMBINED WINDOW VIEW (same calendar periods)")
    print(f"{'='*75}")
    print(f"{'Period':<20} {'BTC PF':>8} {'BTC ret':>9} {'ETH PF':>8} {'ETH ret':>9}")
    print(f"{'-'*75}")

    # Map windows to calendar labels for aligned view
    btc_by_label = {w['window']: w for w in btc_result['windows']}
    eth_by_label = {w['window']: w for w in eth_result['windows']}

    shared_periods = [
        ('Oct–Dec 2025', 'W3: Oct 2025 – Jan 2026', 'W1: Oct 2025 – Jan 2026'),
        ('Jan–Mar 2026', 'W4: Jan 2026 – Apr 2026', 'W2: Jan 2026 – Apr 2026'),
    ]
    for period, btc_key, eth_key in shared_periods:
        bw = btc_by_label.get(btc_key)
        ew = eth_by_label.get(eth_key)
        b_pf  = f"{bw['profit_factor']:.3f}" if bw and bw['trades'] else '—'
        b_ret = f"{bw['return_pct']:+.1f}%" if bw and bw['trades'] else '—'
        e_pf  = f"{ew['profit_factor']:.3f}" if ew and ew['trades'] else '—'
        e_ret = f"{ew['return_pct']:+.1f}%" if ew and ew['trades'] else '—'
        print(f"{period:<20} {b_pf:>8} {b_ret:>9} {e_pf:>8} {e_ret:>9}")
    print(f"{'='*75}\n")

    # Save results
    output = {
        'BTC': {'windows': btc_result['windows'], 'final_equity': btc_result['final_equity']},
        'ETH': {'windows': eth_result['windows'], 'final_equity': eth_result['final_equity']},
    }
    with open('data/exp006v2_walkforward.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print("Saved: data/exp006v2_walkforward.json")
