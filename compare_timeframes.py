"""
Timeframe Comparison Experiment — BTC/USDT 180d
Tests the same strategy logic across 5m, 15m, and 1h candles.

Rules:
  - Identical SL/TP/BE thresholds across all timeframes
  - No circuit breaker
  - No early exits
  - 45-min post-trade cooldown (time-based, adapts naturally to each TF)
  - HTF confirmation always uses the 1h dataset

HTF slice logic per timeframe:
  - 5m  : floor("h") excludes the in-progress 1h candle → uses prior closed 1h
  - 15m : same
  - 1h  : floor("h") = candle open time → HTF slice is all prior closed 1h candles
           (HTF confirmation uses the previous 1h candle's indicators)

Usage:
    python3 compare_timeframes.py
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config import SYMBOL
from indicators import add_indicators
from signal_engine import generate_signal

# ---------------------------------------------------------------------------
# Constants — identical across all timeframes
# ---------------------------------------------------------------------------

RESULTS_DIR = "data"

PATH_5M  = f"{RESULTS_DIR}/BTCUSDT_5m_last_180d.csv"
PATH_15M = f"{RESULTS_DIR}/BTCUSDT_15m_last_180d.csv"
PATH_1H  = f"{RESULTS_DIR}/BTCUSDT_1h_last_200d.csv"

OUTPUT_PATH = f"{RESULTS_DIR}/timeframe_comparison.json"

STOP_LOSS_PCT          = 0.6
TAKE_PROFIT_PCT        = 1.2
BREAK_EVEN_TRIGGER_PCT = 0.8
FEE_PER_SIDE_PCT       = 0.1
ROUND_TRIP_FEE_PCT     = FEE_PER_SIDE_PCT * 2

MIN_WARMUP = 50  # candles before signals are evaluated


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_dataset(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Dataset not found: {path}\n"
            "Run fetch_history.py first."
        )
    df = pd.read_csv(path, parse_dates=["open_time", "close_time"])
    df.set_index("open_time", inplace=True)
    df.index = pd.to_datetime(df.index, utc=True)
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing required columns: {missing}")
    return df


# ---------------------------------------------------------------------------
# Core backtest — clean baseline, no CB, no early exits
# ---------------------------------------------------------------------------

def run_backtest(df_raw: pd.DataFrame, df_1h: pd.DataFrame, timeframe: str) -> list[dict]:
    """
    Candle-by-candle simulation with SL/TP/BE and 45-min cooldown.
    Signal at candle i → execute at open of candle i+1.
    HTF: 1h candles with open_time < floor(candle_i_open_time, 1h).
    """
    df_ind = add_indicators(df_raw.copy())
    if df_ind.empty:
        raise ValueError(f"Indicator computation failed for {timeframe} — dataset too short.")

    n = len(df_ind)
    trades         = []
    position       = None
    cooldown_until = None

    for i in range(MIN_WARMUP, n - 1):
        window = df_ind.iloc[: i + 2]

        candle_open_time = df_ind.index[i]
        htf_cutoff       = candle_open_time.floor("h")
        df_htf_slice     = df_1h[df_1h.index < htf_cutoff]

        payload    = generate_signal(window, SYMBOL, timeframe, df_htf=df_htf_slice)
        signal     = payload["signal"]

        exec_candle = df_ind.iloc[i + 1]
        exec_price  = exec_candle["open"]
        exec_time   = exec_candle.name

        if position is None:
            if signal == "BUY":
                if cooldown_until is not None and exec_time < cooldown_until:
                    continue
                position = {
                    "entry_price":          exec_price,
                    "entry_time":           exec_time.isoformat(),
                    "break_even_triggered": False,
                }
        else:
            entry            = position["entry_price"]
            tp_price         = entry * (1 + TAKE_PROFIT_PCT / 100)
            be_trigger_price = entry * (1 + BREAK_EVEN_TRIGGER_PCT / 100)

            candle_low  = float(exec_candle["low"])
            candle_high = float(exec_candle["high"])

            sl_price = entry if position["break_even_triggered"] else entry * (1 - STOP_LOSS_PCT / 100)

            # Gap at open check
            if exec_price <= sl_price:
                exit_price, exit_reason = exec_price, "STOP_LOSS"
            elif exec_price >= tp_price:
                exit_price, exit_reason = exec_price, "TAKE_PROFIT"
            else:
                # Intracandle: activate break-even if high reached trigger
                if not position["break_even_triggered"] and candle_high >= be_trigger_price:
                    position["break_even_triggered"] = True
                    sl_price = entry

                if candle_low <= sl_price and candle_high >= tp_price:
                    exit_price, exit_reason = sl_price, "STOP_LOSS"
                elif candle_low <= sl_price:
                    exit_price, exit_reason = sl_price, "STOP_LOSS"
                elif candle_high >= tp_price:
                    exit_price, exit_reason = tp_price, "TAKE_PROFIT"
                elif signal == "SELL":
                    exit_price, exit_reason = exec_price, "SELL"
                else:
                    exit_price = None

            if exit_price is not None:
                pct_return = (exit_price - entry) / entry * 100 - ROUND_TRIP_FEE_PCT
                trades.append({
                    "entry_time":           position["entry_time"],
                    "exit_time":            exec_time.isoformat(),
                    "entry_price":          round(entry, 4),
                    "exit_price":           round(exit_price, 4),
                    "pct_return":           round(pct_return, 4),
                    "exit_reason":          exit_reason,
                    "break_even_triggered": position["break_even_triggered"],
                })
                position       = None
                cooldown_until = exec_time + timedelta(minutes=45)

    # Force-close any open position at last candle's close
    if position is not None:
        last       = df_ind.iloc[-1]
        pct_return = (last["close"] - position["entry_price"]) / position["entry_price"] * 100 - ROUND_TRIP_FEE_PCT
        trades.append({
            "entry_time":           position["entry_time"],
            "exit_time":            last.name.isoformat(),
            "entry_price":          round(position["entry_price"], 4),
            "exit_price":           round(float(last["close"]), 4),
            "pct_return":           round(pct_return, 4),
            "exit_reason":          "END_OF_DATA",
            "break_even_triggered": position["break_even_triggered"],
        })

    return trades


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(trades: list[dict], timeframe: str) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "timeframe":              timeframe,
            "total_trades":           0,
            "wins":                   0,
            "losses":                 0,
            "win_rate_pct":           0.0,
            "cumulative_return_pct":  0.0,
            "avg_return_pct":         0.0,
            "best_trade_pct":         0.0,
            "worst_trade_pct":        0.0,
            "max_drawdown_pct":       0.0,
            "profit_factor":          None,
            "expectancy_pct":         0.0,
            "avg_trade_duration_min": 0.0,
            "longest_win_streak":     0,
            "longest_loss_streak":    0,
        }

    returns = [t["pct_return"] for t in trades]
    wins    = sum(1 for r in returns if r > 0)

    cumulative = 1.0
    for r in returns:
        cumulative *= 1 + r / 100
    cumulative_pct = (cumulative - 1) * 100

    # Max drawdown
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r / 100))
    peak, max_dd = equity[0], 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Profit factor
    gross_profit  = sum(r for r in returns if r > 0)
    gross_loss    = abs(sum(r for r in returns if r < 0))
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None

    # Expectancy
    losses_count = n - wins
    avg_win  = gross_profit / wins         if wins         > 0 else 0.0
    avg_loss = gross_loss   / losses_count if losses_count > 0 else 0.0
    expectancy = round((wins / n) * avg_win - (losses_count / n) * avg_loss, 4)

    # Avg trade duration (minutes)
    durations = []
    for t in trades:
        entry_dt = datetime.fromisoformat(t["entry_time"])
        exit_dt  = datetime.fromisoformat(t["exit_time"])
        durations.append((exit_dt - entry_dt).total_seconds() / 60)
    avg_duration_min = round(sum(durations) / len(durations), 1)

    # Win / loss streaks
    longest_win_streak = longest_loss_streak = 0
    cur_win = cur_loss = 0
    for r in returns:
        if r > 0:
            cur_win  += 1
            cur_loss  = 0
        else:
            cur_loss += 1
            cur_win   = 0
        longest_win_streak  = max(longest_win_streak,  cur_win)
        longest_loss_streak = max(longest_loss_streak, cur_loss)

    # Exit reason breakdown
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1

    return {
        "timeframe":              timeframe,
        "total_trades":           n,
        "wins":                   wins,
        "losses":                 n - wins,
        "win_rate_pct":           round(wins / n * 100, 2),
        "cumulative_return_pct":  round(cumulative_pct, 4),
        "avg_return_pct":         round(sum(returns) / n, 4),
        "best_trade_pct":         round(max(returns), 4),
        "worst_trade_pct":        round(min(returns), 4),
        "max_drawdown_pct":       round(max_dd, 4),
        "profit_factor":          profit_factor,
        "expectancy_pct":         expectancy,
        "avg_trade_duration_min": avg_duration_min,
        "longest_win_streak":     longest_win_streak,
        "longest_loss_streak":    longest_loss_streak,
        "exit_reasons":           reasons,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_comparison(results: list[dict]) -> None:
    labels = [r["timeframe"] for r in results]

    def row(label: str, key: str, fmt: str) -> str:
        vals = []
        for r in results:
            v = r.get(key)
            if v is None:
                vals.append("  N/A    ")
            else:
                vals.append(fmt.format(v))
        return f"  {label:<30} " + "  ".join(f"{v:>12}" for v in vals)

    def best_idx(key: str, higher_is_better: bool = True) -> int:
        vals = [r.get(key) for r in results]
        valid = [(v, i) for i, v in enumerate(vals) if v is not None]
        if not valid:
            return -1
        return max(valid, key=lambda x: x[0] if higher_is_better else -x[0])[1]

    print()
    print("=" * 72)
    print("  TIMEFRAME COMPARISON — BTC/USDT 180d")
    print(f"  SL={STOP_LOSS_PCT}%  TP={TAKE_PROFIT_PCT}%  BE=+{BREAK_EVEN_TRIGGER_PCT}%  Fee={ROUND_TRIP_FEE_PCT}%")
    print(f"  No circuit breaker  |  No early exits  |  45-min post-trade cooldown")
    print("=" * 72)
    print(f"  {'Metric':<30} " + "  ".join(f"  {tf:>10}" for tf in labels))
    print("  " + "-" * 68)
    print(row("Total trades",           "total_trades",           "{:.0f}"))
    print(row("Wins",                   "wins",                   "{:.0f}"))
    print(row("Losses",                 "losses",                 "{:.0f}"))
    print(row("Win rate",               "win_rate_pct",           "{:.2f}%"))
    print(row("Cumulative return",      "cumulative_return_pct",  "{:+.4f}%"))
    print(row("Avg return / trade",     "avg_return_pct",         "{:+.4f}%"))
    print(row("Best trade",             "best_trade_pct",         "{:+.4f}%"))
    print(row("Worst trade",            "worst_trade_pct",        "{:+.4f}%"))
    print(row("Max drawdown",           "max_drawdown_pct",       "{:.4f}%"))
    pf_strs = []
    for r in results:
        pf = r.get("profit_factor")
        pf_strs.append(f"{pf:>11.4f}" if pf is not None else "        N/A")
    print(f"  {'Profit factor':<30} " + "  ".join(pf_strs))
    print(row("Expectancy",             "expectancy_pct",         "{:+.4f}%"))
    print(row("Avg trade duration",     "avg_trade_duration_min", "{:.1f} min"))
    print(row("Longest win streak",     "longest_win_streak",     "{:.0f}"))
    print(row("Longest loss streak",    "longest_loss_streak",    "{:.0f}"))
    print("  " + "-" * 68)

    # Best performer by cumulative return
    bi = best_idx("cumulative_return_pct", higher_is_better=True)
    pf_bi = best_idx("profit_factor", higher_is_better=True)
    wr_bi = best_idx("win_rate_pct", higher_is_better=True)
    dd_bi = best_idx("max_drawdown_pct", higher_is_better=False)

    print()
    print(f"  Best cumulative return : {labels[bi]} ({results[bi]['cumulative_return_pct']:+.4f}%)")
    print(f"  Best profit factor     : {labels[pf_bi]} ({results[pf_bi]['profit_factor']:.4f})")
    print(f"  Best win rate          : {labels[wr_bi]} ({results[wr_bi]['win_rate_pct']:.2f}%)")
    print(f"  Lowest max drawdown    : {labels[dd_bi]} ({results[dd_bi]['max_drawdown_pct']:.4f}%)")
    print("=" * 72)

    # Exit reason breakdown per TF
    print()
    print("  Exit reasons per timeframe:")
    all_reasons = sorted({r for m in results for r in m.get("exit_reasons", {})})
    print(f"  {'Reason':<20} " + "  ".join(f"  {tf:>10}" for tf in labels))
    print("  " + "-" * 54)
    for reason in all_reasons:
        vals = [str(m.get("exit_reasons", {}).get(reason, 0)) for m in results]
        print(f"  {reason:<20} " + "  ".join(f"{v:>12}" for v in vals))
    print()


def describe_equity_curve(trades: list[dict], timeframe: str) -> str:
    """Summarise the shape of the equity curve without plotting."""
    if not trades:
        return f"  {timeframe}: No trades."

    returns = [t["pct_return"] for t in trades]
    equity  = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r / 100))

    final      = equity[-1]
    peak       = max(equity)
    trough     = min(equity)
    peak_idx   = equity.index(peak)
    trough_idx = equity.index(trough)

    # Count winning and losing runs to describe shape
    phases = []
    run_type, run_len = ("win" if returns[0] > 0 else "loss"), 1
    for r in returns[1:]:
        cur = "win" if r > 0 else "loss"
        if cur == run_type:
            run_len += 1
        else:
            phases.append((run_type, run_len))
            run_type, run_len = cur, 1
    phases.append((run_type, run_len))
    max_win_run  = max((l for t, l in phases if t == "win"),  default=0)
    max_loss_run = max((l for t, l in phases if t == "loss"), default=0)

    direction = "upward" if final > 1.0 else "downward"
    peak_pos  = "early" if peak_idx < len(equity) * 0.33 else ("mid" if peak_idx < len(equity) * 0.66 else "late")

    return (
        f"  {timeframe}: {direction} overall (×{final:.4f}). "
        f"Peak ×{peak:.4f} at {peak_pos} period (trade {peak_idx}), "
        f"trough ×{trough:.4f} at trade {trough_idx}. "
        f"Longest win run: {max_win_run}, longest loss run: {max_loss_run}."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"[compare] Loading datasets ...")
    df_5m  = load_dataset(PATH_5M)
    df_15m = load_dataset(PATH_15M)
    df_1h  = load_dataset(PATH_1H)

    print(f"[compare]  5m : {len(df_5m):>6} candles  ({df_5m.index[0].date()} → {df_5m.index[-1].date()})")
    print(f"[compare] 15m : {len(df_15m):>6} candles  ({df_15m.index[0].date()} → {df_15m.index[-1].date()})")
    print(f"[compare]  1h : {len(df_1h):>6} candles  ({df_1h.index[0].date()} → {df_1h.index[-1].date()})")

    configs = [
        ("5m",  df_5m,  df_1h),
        ("15m", df_15m, df_1h),
        ("1h",  df_1h,  df_1h),   # 1h as both primary and HTF — prior closed candles only
    ]

    all_trades   = {}
    all_metrics  = []

    for tf, df_primary, df_htf in configs:
        print(f"\n[compare] Running {tf} backtest ...")
        trades = run_backtest(df_primary, df_htf, tf)
        all_trades[tf]  = trades
        metrics = compute_metrics(trades, tf)
        all_metrics.append(metrics)
        print(
            f"[compare] {tf}: {metrics['total_trades']} trades | "
            f"win={metrics['win_rate_pct']:.1f}% | "
            f"cum={metrics['cumulative_return_pct']:+.4f}% | "
            f"PF={metrics['profit_factor']}"
        )

    print_comparison(all_metrics)

    print("  Equity curve shape:")
    for tf, trades in all_trades.items():
        print(describe_equity_curve(trades, tf))

    # Save JSON
    Path(os.path.dirname(OUTPUT_PATH)).mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "symbol":        SYMBOL,
        "stop_loss_pct": STOP_LOSS_PCT,
        "take_profit_pct": TAKE_PROFIT_PCT,
        "break_even_trigger_pct": BREAK_EVEN_TRIGGER_PCT,
        "fee_pct":       ROUND_TRIP_FEE_PCT,
        "results":       all_metrics,
        "trades":        {tf: t for tf, t in all_trades.items()},
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[compare] Full results saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
