"""
EXP007-v2 — Minimum SL Distance Filter

Hypothesis : Many BTC losses occur when the trigger candle is compressed,
             placing the SL within normal 15m market noise. The existing
             `is_range_sufficient` filter uses a 5-bar rolling average and
             does NOT protect against a compressed trigger candle. When
             sl_dist < 0.15% of entry price, ~94.5% of subsequent candles
             statistically reach the SL level (ratio SL/next-candle-range ≈ 0.25).

Intervention: Add a `MIN_SL_DIST_PCT` filter immediately after `calculate_sl_tp`.
              If abs(entry - sl) / entry < MIN_SL_DIST_PCT → reject the entry.

Tested thresholds: 0.15%, 0.20%, 0.25%

Validation: Same walk-forward structure as EXP006 (zero other changes).
  BTC: 4 windows × 3 months  (OOS + IS combined, Apr 2025 – Mar 2026)
  ETH: 2 windows × 3 months  (IS only, Oct 2025 – Mar 2026)

Decision criteria:
  KEEP if:
    - BTC PF improves or stays stable AND BTC WR increases
    - Trade count does not drop below ~50% of EXP006 baseline
    - ETH not harmed (PF within 0.1 of EXP006)
  REVERT if threshold kills edge (PF collapses or trade count < 30% of baseline)
  CONDITIONAL if improvement is BTC-only and ETH is harmed
"""

import json
import pandas as pd
import numpy as np

from strategy_pullback import (
    prepare_1h, prepare_15m, align_1h_to_15m,
    get_trend,
    is_trend_strong,
    is_pullback_quality,
    is_entry_trigger,
    is_candle_quality,
    is_range_sufficient,
)
from trade_logic import calculate_sl_tp, check_exit
from logger_v2 import setup_logger, log_open, log_close
from backtest_v2 import load_data, compute_metrics

# ── Config (identical to EXP006) ─────────────────────────────────────────────
INITIAL_CAPITAL = 10_000.0
RISK_PCT        = 0.01
MIN_RISK_PRICE  = 1.0

# Candidate thresholds under test
SL_DIST_THRESHOLDS = [0.0015, 0.0020, 0.0025]  # 0.15%, 0.20%, 0.25%


# ── Window definition (reused from EXP006) ───────────────────────────────────

def assign_window(ts, windows: list[tuple]) -> int | None:
    if pd.isna(ts):
        return None
    for i, (start, end) in enumerate(windows):
        if start <= ts < end:
            return i
    return None


# ── Per-window metrics (reused from EXP006) ──────────────────────────────────

def compute_window_metrics(
    window_trades: list,
    equity_curve: list,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    equity_at_start: float,
) -> dict:
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

    gross_profit  = wins['pnl'].sum() if len(wins) else 0.0
    gross_loss    = abs(losses['pnl'].sum()) if len(losses) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    win_rate      = len(wins) / len(df) * 100
    expectancy    = df['pnl'].mean()
    net_pnl       = df['pnl'].sum()
    return_pct    = net_pnl / equity_at_start * 100

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
        'trades':         len(df),
        'win_rate_pct':   round(win_rate, 1),
        'return_pct':     round(return_pct, 2),
        'max_dd_pct':     round(max_dd, 2),
        'profit_factor':  round(profit_factor, 3),
        'expectancy_usd': round(expectancy, 2),
        'gross_profit':   round(gross_profit, 2),
        'gross_loss':     round(gross_loss, 2),
    }


# ── Core backtest loop ────────────────────────────────────────────────────────

def run_walkforward(
    path_1h: str,
    path_15m: str,
    windows: list[tuple],
    asset: str,
    min_sl_dist_pct: float,
    path_1h_extra: str = None,
    path_15m_extra: str = None,
) -> dict:
    """
    EXP002 strategy with one added filter: sl_dist / entry >= min_sl_dist_pct.
    All other parameters are identical to EXP006.
    """
    label_pct = f"{min_sl_dist_pct*100:.2f}pct"
    log_file  = f'logs/exp007_{asset}_{label_pct}.log'
    logger    = setup_logger(f'exp007_{asset}_{label_pct}', log_file=log_file)

    logger.info(f"\n{'='*60}")
    logger.info(f"EXP007-v2  |  {asset}  |  MIN_SL_DIST_PCT={min_sl_dist_pct*100:.2f}%")
    logger.info(f"Strategy   : EXP002-v2 + SL distance filter")
    logger.info(f"Windows    : {len(windows)} × 3-month evaluation periods")
    logger.info(f"{'='*60}\n")

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

    equity       = INITIAL_CAPITAL
    position     = None
    trades       = []
    equity_curve = []

    rejected_sl_dist = 0  # new filter rejection counter
    rejected_other   = 0

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
                    'sl_dist_pct': position['sl_dist_pct'],
                    'reason':    reason,
                    'pnl':       round(pnl, 4),
                    'equity':    round(equity, 4),
                })
                position = None

            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        # EXP002 entry filters (unchanged)
        trend = get_trend(row)
        if trend is None:
            rejected_other += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_trend_strong(row):
            rejected_other += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_pullback_quality(row, trend):
            rejected_other += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_entry_trigger(row, trend):
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_candle_quality(row, trend):
            rejected_other += 1
            equity_curve.append({'ts': str(ts), 'equity': round(equity, 4)})
            continue

        if not is_range_sufficient(row):
            rejected_other += 1
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

        # ── EXP007 new filter: SL must be outside market noise ──────────────
        sl_dist_pct = risk_price / entry
        if sl_dist_pct < min_sl_dist_pct:
            rejected_sl_dist += 1
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
        if position['direction'] == 'long':
            pnl = (exit_price - position['entry']) * position['qty']
        else:
            pnl = (position['entry'] - exit_price) * position['qty']
        equity += pnl
        log_close(logger, position['direction'], position['entry'], exit_price, 'END', pnl, equity)
        trades.append({
            'open_ts':     position['open_ts'],
            'close_ts':    str(last_row['open_time']),
            'direction':   position['direction'],
            'entry':       position['entry'],
            'exit':        exit_price,
            'sl':          position['sl'],
            'tp':          position['tp'],
            'sl_dist_pct': position['sl_dist_pct'],
            'reason':      'END',
            'pnl':         round(pnl, 4),
            'equity':      round(equity, 4),
        })

    logger.info(f"\nRejected by SL-dist filter : {rejected_sl_dist}")
    logger.info(f"Rejected by other filters  : {rejected_other}")

    # ── Split into windows ───────────────────────────────────────────────────
    trades_df = pd.DataFrame(trades)
    if len(trades_df):
        trades_df['close_ts'] = pd.to_datetime(trades_df['close_ts'])
        trades_df['window']   = trades_df['close_ts'].apply(
            lambda ts: assign_window(ts, windows)
        )

    eq_df = pd.DataFrame(equity_curve)
    eq_df['ts'] = pd.to_datetime(eq_df['ts'])

    window_results = []
    for i, (wstart, wend) in enumerate(windows):
        label = f"W{i+1}: {wstart.strftime('%b %Y')} – {wend.strftime('%b %Y')}"

        pre_mask = eq_df['ts'] < wstart
        eq_at_start = eq_df.loc[pre_mask, 'equity'].iloc[-1] if pre_mask.any() else INITIAL_CAPITAL

        w_trades = trades_df[trades_df['window'] == i].to_dict(orient='records') if len(trades_df) else []

        m = compute_window_metrics(w_trades, equity_curve, wstart, wend, eq_at_start)
        m['window']       = label
        m['equity_start'] = round(eq_at_start, 2)
        window_results.append(m)

        pf_str  = f"{m['profit_factor']:.3f}" if m['profit_factor'] is not None else "—"
        ret_str = f"{m['return_pct']:+.1f}%"  if m['return_pct'] is not None else "—"
        dd_str  = f"{m['max_dd_pct']:.1f}%"   if m['max_dd_pct'] is not None else "—"
        logger.info(
            f"{label:30s}  trades={m['trades']:3d}  WR={m['win_rate_pct'] or 0:.0f}%  "
            f"ret={ret_str:>7s}  DD={dd_str:>6s}  PF={pf_str}"
        )

    return {
        'asset':              asset,
        'min_sl_dist_pct':    min_sl_dist_pct,
        'windows':            window_results,
        'all_trades':         trades,
        'equity_curve':       equity_curve,
        'final_equity':       round(equity, 4),
        'rejected_sl_dist':   rejected_sl_dist,
    }


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_summary(asset: str, result: dict) -> None:
    pct   = result['min_sl_dist_pct'] * 100
    windows = result['windows']
    print(f"\n{'='*75}")
    print(f"EXP007-v2  |  {asset}  |  MIN_SL_DIST={pct:.2f}%")
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
        all_trades = sum(w['trades'] for w in windows)
        print(f"PF > 1.0   : {profitable}/{len(pf_vals)} windows")
        print(f"PF range   : {min(pf_vals):.3f} – {max(pf_vals):.3f}")
        print(f"PF median  : {sorted(pf_vals)[len(pf_vals)//2]:.3f}")
        pf_std = float(np.std(pf_vals)) if len(pf_vals) > 1 else 0.0
        print(f"PF std dev : {pf_std:.3f}")
        print(f"Total trades : {all_trades}")
        print(f"Rejected (SL-dist filter): {result['rejected_sl_dist']}")
    print(f"{'='*75}\n")


def print_comparison_table(asset: str, results_by_threshold: dict, baseline: dict) -> None:
    """Print a side-by-side comparison of EXP006 baseline vs each EXP007 threshold."""
    thresholds = sorted(results_by_threshold.keys())
    print(f"\n{'='*90}")
    print(f"EXP007-v2  |  {asset}  |  THRESHOLD COMPARISON vs EXP006 BASELINE")
    print(f"{'='*90}")
    header = f"{'Threshold':<14}"
    for w in baseline['windows']:
        label = w['window'].split(':')[0]  # "W1", "W2", etc.
        header += f" {label+' PF':>9} {label+' WR':>8} {label+' n':>6}"
    header += f" {'Total n':>8} {'Rej':>6}"
    print(header)
    print('-' * 90)

    def row_str(label, result, rej=None):
        s = f"{label:<14}"
        for w in result['windows']:
            pf = f"{w['profit_factor']:.3f}" if w['profit_factor'] is not None else "—"
            wr = f"{w['win_rate_pct']:.1f}%" if w['win_rate_pct'] is not None else "—"
            s += f" {pf:>9} {wr:>8} {w['trades']:>6}"
        s += f" {sum(w['trades'] for w in result['windows']):>8}"
        if rej is not None:
            s += f" {rej:>6}"
        else:
            s += f" {'—':>6}"
        return s

    print(row_str('EXP006 (base)', baseline))
    for t in thresholds:
        r = results_by_threshold[t]
        print(row_str(f"EXP007 {t*100:.2f}%", r, r['rejected_sl_dist']))
    print(f"{'='*90}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':

    BTC_WINDOWS = [
        (pd.Timestamp('2025-04-01', tz='UTC'), pd.Timestamp('2025-07-01', tz='UTC')),
        (pd.Timestamp('2025-07-01', tz='UTC'), pd.Timestamp('2025-10-01', tz='UTC')),
        (pd.Timestamp('2025-10-01', tz='UTC'), pd.Timestamp('2026-01-01', tz='UTC')),
        (pd.Timestamp('2026-01-01', tz='UTC'), pd.Timestamp('2026-04-01', tz='UTC')),
    ]

    ETH_WINDOWS = [
        (pd.Timestamp('2025-10-01', tz='UTC'), pd.Timestamp('2026-01-01', tz='UTC')),
        (pd.Timestamp('2026-01-01', tz='UTC'), pd.Timestamp('2026-04-01', tz='UTC')),
    ]

    # ── Load EXP006 baseline ─────────────────────────────────────────────────
    print("\nLoading EXP006 baseline for comparison...")
    try:
        with open('data/exp006v2_walkforward.json') as f:
            exp006_data = json.load(f)
        btc_baseline = {'windows': exp006_data['BTC']['windows'], 'rejected_sl_dist': 0}
        eth_baseline = {'windows': exp006_data['ETH']['windows'], 'rejected_sl_dist': 0}
        print("EXP006 baseline loaded.")
    except FileNotFoundError:
        print("WARNING: data/exp006v2_walkforward.json not found. Run backtest_exp006.py first.")
        btc_baseline = None
        eth_baseline = None

    # ── Run EXP007 for each threshold ────────────────────────────────────────
    btc_results = {}
    eth_results = {}

    for threshold in SL_DIST_THRESHOLDS:
        pct_label = f"{threshold*100:.2f}%"
        print(f"\n{'─'*60}")
        print(f"Running BTC | MIN_SL_DIST_PCT = {pct_label}")
        print(f"{'─'*60}")
        btc_r = run_walkforward(
            path_1h        = 'data/BTCUSDT_1h_last_200d.csv',
            path_15m       = 'data/BTCUSDT_15m_last_180d.csv',
            path_1h_extra  = 'data/BTCUSDT_1h_oos_200d.csv',
            path_15m_extra = 'data/BTCUSDT_15m_oos_180d.csv',
            windows        = BTC_WINDOWS,
            asset          = 'BTC',
            min_sl_dist_pct= threshold,
        )
        btc_results[threshold] = btc_r
        print_summary('BTC', btc_r)

        print(f"\n{'─'*60}")
        print(f"Running ETH | MIN_SL_DIST_PCT = {pct_label}")
        print(f"{'─'*60}")
        eth_r = run_walkforward(
            path_1h        = 'data/ETHUSDT_1h_last_200d.csv',
            path_15m       = 'data/ETHUSDT_15m_last_180d.csv',
            windows        = ETH_WINDOWS,
            asset          = 'ETH',
            min_sl_dist_pct= threshold,
        )
        eth_results[threshold] = eth_r
        print_summary('ETH', eth_r)

    # ── Cross-threshold comparison ────────────────────────────────────────────
    if btc_baseline:
        print_comparison_table('BTC', btc_results, btc_baseline)
    if eth_baseline:
        print_comparison_table('ETH', eth_results, eth_baseline)

    # ── Save all results ─────────────────────────────────────────────────────
    output = {}
    for t in SL_DIST_THRESHOLDS:
        key = f"{t*100:.2f}pct"
        output[key] = {
            'BTC': {
                'min_sl_dist_pct': t,
                'windows':         btc_results[t]['windows'],
                'final_equity':    btc_results[t]['final_equity'],
                'rejected_sl_dist':btc_results[t]['rejected_sl_dist'],
            },
            'ETH': {
                'min_sl_dist_pct': t,
                'windows':         eth_results[t]['windows'],
                'final_equity':    eth_results[t]['final_equity'],
                'rejected_sl_dist':eth_results[t]['rejected_sl_dist'],
            },
        }

    out_path = 'data/backtest_exp007_walkforward.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Saved: {out_path}")

    # ── Decision summary ─────────────────────────────────────────────────────
    print(f"\n{'='*75}")
    print(f"EXP007-v2  |  DECISION SUMMARY")
    print(f"{'='*75}")
    print(f"{'Threshold':<14} {'BTC PF med':>11} {'BTC WR':>8} {'BTC n':>7} {'ETH PF med':>11} {'ETH WR':>8} {'ETH n':>7} {'BTC rej':>8}")
    print(f"{'-'*75}")

    for t in SL_DIST_THRESHOLDS:
        br = btc_results[t]
        er = eth_results[t]

        b_pf_vals = [w['profit_factor'] for w in br['windows'] if w['profit_factor'] is not None]
        e_pf_vals = [w['profit_factor'] for w in er['windows'] if w['profit_factor'] is not None]
        b_wr_vals = [w['win_rate_pct']  for w in br['windows'] if w['win_rate_pct']  is not None]
        e_wr_vals = [w['win_rate_pct']  for w in er['windows'] if w['win_rate_pct']  is not None]

        b_pf_med = f"{sorted(b_pf_vals)[len(b_pf_vals)//2]:.3f}" if b_pf_vals else "—"
        e_pf_med = f"{sorted(e_pf_vals)[len(e_pf_vals)//2]:.3f}" if e_pf_vals else "—"
        b_wr_med = f"{np.mean(b_wr_vals):.1f}%"                   if b_wr_vals else "—"
        e_wr_med = f"{np.mean(e_wr_vals):.1f}%"                   if e_wr_vals else "—"
        b_n      = sum(w['trades'] for w in br['windows'])
        e_n      = sum(w['trades'] for w in er['windows'])

        print(
            f"{t*100:.2f}%{'':<9} {b_pf_med:>11} {b_wr_med:>8} {b_n:>7} "
            f"{e_pf_med:>11} {e_wr_med:>8} {e_n:>7} {br['rejected_sl_dist']:>8}"
        )

    if btc_baseline:
        b_pf_vals = [w['profit_factor'] for w in btc_baseline['windows'] if w['profit_factor'] is not None]
        e_pf_vals = [w['profit_factor'] for w in eth_baseline['windows'] if w['profit_factor'] is not None]
        b_pf_med = f"{sorted(b_pf_vals)[len(b_pf_vals)//2]:.3f}" if b_pf_vals else "—"
        e_pf_med = f"{sorted(e_pf_vals)[len(e_pf_vals)//2]:.3f}" if e_pf_vals else "—"
        b_n = sum(w['trades'] for w in btc_baseline['windows'])
        e_n = sum(w['trades'] for w in eth_baseline['windows'])
        print(f"\nBaseline (EXP006)   {b_pf_med:>11} {'—':>8} {b_n:>7} {e_pf_med:>11} {'—':>8} {e_n:>7} {'0':>8}")

    print(f"{'='*75}\n")
