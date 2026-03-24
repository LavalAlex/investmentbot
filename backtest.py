"""
Backtest — Stage A
Run the signal engine candle-by-candle over saved historical data.
No real trading. No orders. Analysis only.

Usage:
    python3 backtest.py
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from claude_filter import review_signal
from config import ENABLE_CLAUDE_FILTER, SYMBOL
from indicators import add_indicators
from signal_engine import generate_signal

TIMEFRAME = "15m"
RESULTS_DIR = "data"
PATH_15M          = f"{RESULTS_DIR}/BTCUSDT_15m_last_180d.csv"
PATH_1H           = f"{RESULTS_DIR}/BTCUSDT_1h_last_200d.csv"
OUTPUT_PATH       = f"{RESULTS_DIR}/backtest_BTCUSDT_180d.json"
EQUITY_CURVE_PATH = f"{RESULTS_DIR}/equity_curve_BTCUSDT_180d.csv"

# Minimum rows needed before indicators are valid
MIN_WARMUP = 50

# Exit thresholds (percentage, applied to entry price)
STOP_LOSS_PCT         = 0.6   # exit if price drops 0.6% below entry
TAKE_PROFIT_PCT       = 1.2   # LONG take profit (price rises 1.2% beyond entry)
SHORT_TAKE_PROFIT_PCT = 2.2   # SHORT take profit (price falls 2.2% beyond entry)

# Break-even: move SL to entry once unrealized gain reaches this threshold
BREAK_EVEN_TRIGGER_PCT = 0.8

# Circuit breaker: after N consecutive losing trades, pause entries for T hours
CB_LOSS_THRESHOLD  = 2   # consecutive losses that trigger the circuit breaker
CB_PAUSE_HOURS     = 48  # hours to block new entries after trigger

# Trading fees: 0.1% per side (entry + exit = 0.2% round-trip)
FEE_PER_SIDE_PCT   = 0.1
ROUND_TRIP_FEE_PCT = FEE_PER_SIDE_PCT * 2

# ---------------------------------------------------------------------------
# Regime filter — LONG entries only
# ---------------------------------------------------------------------------
# Blocks BUY when the last confirmed 1h candle closed BELOW the 1h EMA200.
# Rationale: LONG entries in bearish macro regimes have ~23% win rate,
# well below the ~40% breakeven threshold at current SL/TP settings.
# SHORT logic is not affected.
REGIME_FILTER_LONG = True

# Optional additional gate (disabled by default):
# Also block LONG when 1h ATR14 is below its rolling-expanding median —
# i.e., low-volatility environments where LONG setups historically hit SL.
# Set to True only after further testing.
BLOCK_LONG_LOW_VOL = False


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_dataset(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Dataset not found: {path}\n"
            "Run fetch_history.py first to download historical data."
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
# Core backtest logic
# ---------------------------------------------------------------------------

def run_backtest(
    df_raw: pd.DataFrame,
    df_1h: pd.DataFrame,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Iterate candle-by-candle, generate signals, simulate position management.

    Signal at candle i → execute at open of candle i+1 (no lookahead bias).
    One open position at a time. Enter on BUY. Exit on SELL, SL, or TP.

    HTF slice for candle i: all 1h candles with open_time < floor(candle_i_open_time, 1h).
    This guarantees no lookahead in the 1h data — only fully closed 1h candles are used.

    Circuit breaker: after CB_LOSS_THRESHOLD consecutive losing trades, all BUY
    entries are blocked for CB_PAUSE_HOURS. A winning trade resets the loss counter.

    Returns:
        trades:     list of completed trade dicts
        signal_log: list of every signal evaluated (for audit)
        cb_events:  list of circuit-breaker activation records
    """
    df_ind = add_indicators(df_raw.copy())
    if df_ind.empty:
        raise ValueError("Indicator computation failed — dataset too short.")

    # Pre-compute 1h indicators once for the regime filter.
    # Uses expanding-median ATR so there is no lookahead bias.
    if REGIME_FILTER_LONG or BLOCK_LONG_LOW_VOL:
        df_1h_ind = add_indicators(df_1h.copy())
        if not df_1h_ind.empty:
            df_1h_ind["atr_pct"] = df_1h_ind["atr14"] / df_1h_ind["close"]
            df_1h_ind["atr_exp_median"] = (
                df_1h_ind["atr_pct"].expanding(min_periods=14).median()
            )
        else:
            df_1h_ind = None
    else:
        df_1h_ind = None

    n = len(df_ind)
    trades        = []
    signal_log    = []
    cb_events     = []        # records of each CB activation
    position      = None      # None or dict with entry details
    cooldown_until = None     # datetime: 45-min post-trade cooldown
    consecutive_losses = 0   # count of back-to-back losing trades
    cb_until       = None     # datetime: circuit-breaker pause end

    # i is the "signal candle" — generate_signal evaluates df[-2] = df[i]
    # window = df[:i+2] satisfies: df[-2]=df[i], df[-1]=df[i+1] ("in-progress")
    # execution happens at open of candle i+1
    for i in range(MIN_WARMUP, n - 1):
        window = df_ind.iloc[: i + 2]

        # 1h slice: only candles whose open_time is before the current 1h period.
        # floor('h') gives the start of the hour containing candle i's open_time;
        # anything strictly less than that is a fully closed 1h candle.
        candle_open_time = df_ind.index[i]
        htf_cutoff = candle_open_time.floor("h")
        df_htf_slice = df_1h[df_1h.index < htf_cutoff]

        payload = generate_signal(window, SYMBOL, TIMEFRAME, df_htf=df_htf_slice)
        signal  = payload["signal"]

        exec_candle = df_ind.iloc[i + 1]
        exec_price  = exec_candle["open"]
        exec_time   = exec_candle.name  # DatetimeIndex entry

        # Is the circuit breaker currently active?
        cb_active = cb_until is not None and exec_time < cb_until

        log_entry = {
            "candle_time":           df_ind.index[i].isoformat(),
            "signal":                signal,
            "confidence":            payload["confidence"],
            "close":                 float(df_ind.iloc[i]["close"]),
            "claude_decision":       None,
            "claude_reason":         None,
            "circuit_breaker":       cb_active,
        }

        if position is None:
            if signal == "BUY":
                # 45-min post-trade cooldown
                if cooldown_until is not None and exec_time < cooldown_until:
                    log_entry["signal"] = "BUY_COOLDOWN"
                    signal_log.append(log_entry)
                    continue

                # Circuit-breaker pause
                if cb_active:
                    cb_events[-1]["blocked_entries_count"] += 1
                    log_entry["signal"] = "BUY_CIRCUIT_BREAKER"
                    signal_log.append(log_entry)
                    continue

                # Regime filter: block LONG when last confirmed 1h candle
                # closed below 1h EMA200 (bearish macro regime).
                if df_1h_ind is not None:
                    htf_mask = df_1h_ind.index < htf_cutoff
                    if htf_mask.any():
                        last_1h = df_1h_ind[htf_mask].iloc[-1]
                        _1h_close  = float(last_1h["close"])
                        _1h_ema200 = float(last_1h["ema200"])
                        _blocked = pd.notna(_1h_ema200) and _1h_close < _1h_ema200
                        # Optional low-volatility gate (BLOCK_LONG_LOW_VOL)
                        if not _blocked and BLOCK_LONG_LOW_VOL:
                            _atr_pct    = last_1h.get("atr_pct", float("nan"))
                            _atr_median = last_1h.get("atr_exp_median", float("nan"))
                            if pd.notna(_atr_pct) and pd.notna(_atr_median):
                                _blocked = float(_atr_pct) < float(_atr_median)
                        if _blocked:
                            log_entry["signal"] = "BUY_REGIME_BLOCKED"
                            signal_log.append(log_entry)
                            continue

                if ENABLE_CLAUDE_FILTER:
                    claude = review_signal(payload, df_ind.iloc[i])
                    log_entry["claude_decision"] = claude["decision"]
                    log_entry["claude_reason"]   = claude["reason"]
                    print(f"  [claude] {claude['decision']} — {claude['reason']}")
                    approved = claude["decision"] == "APPROVE"
                else:
                    approved = True

                if approved:
                    position = {
                        "entry_price":          exec_price,
                        "entry_time":           exec_time.isoformat(),
                        "break_even_triggered": False,
                        "direction":            "LONG",
                    }

            elif signal == "SELL":
                # 45-min post-trade cooldown
                if cooldown_until is not None and exec_time < cooldown_until:
                    log_entry["signal"] = "SELL_COOLDOWN"
                    signal_log.append(log_entry)
                    continue

                # Circuit-breaker pause
                if cb_active:
                    cb_events[-1]["blocked_entries_count"] += 1
                    log_entry["signal"] = "SELL_CIRCUIT_BREAKER"
                    signal_log.append(log_entry)
                    continue

                position = {
                    "entry_price":          exec_price,
                    "entry_time":           exec_time.isoformat(),
                    "break_even_triggered": False,
                    "direction":            "SHORT",
                }

        else:
            entry     = position["entry_price"]
            direction = position["direction"]

            candle_low  = float(exec_candle["low"])
            candle_high = float(exec_candle["high"])
            exit_price  = None
            exit_reason = None
            pct_return  = None

            if direction == "LONG":
                tp_price         = entry * (1 + TAKE_PROFIT_PCT / 100)
                be_trigger_price = entry * (1 + BREAK_EVEN_TRIGGER_PCT / 100)
                sl_price = entry if position["break_even_triggered"] else entry * (1 - STOP_LOSS_PCT / 100)

                # Gap at open takes priority
                if exec_price <= sl_price:
                    exit_price, exit_reason = exec_price, "STOP_LOSS"
                elif exec_price >= tp_price:
                    exit_price, exit_reason = exec_price, "TAKE_PROFIT"
                else:
                    # Activate break-even if candle high reached trigger
                    if not position["break_even_triggered"] and candle_high >= be_trigger_price:
                        position["break_even_triggered"] = True
                        sl_price = entry
                    # Intracandle SL/TP — if both hit, assume SL first (conservative)
                    if candle_low <= sl_price and candle_high >= tp_price:
                        exit_price, exit_reason = sl_price, "STOP_LOSS"
                    elif candle_low <= sl_price:
                        exit_price, exit_reason = sl_price, "STOP_LOSS"
                    elif candle_high >= tp_price:
                        exit_price, exit_reason = tp_price, "TAKE_PROFIT"
                    elif signal == "SELL":
                        exit_price, exit_reason = exec_price, "SELL"

                if exit_price is not None:
                    pct_return = (exit_price - entry) / entry * 100 - ROUND_TRIP_FEE_PCT

            else:  # SHORT
                tp_price         = entry * (1 - SHORT_TAKE_PROFIT_PCT / 100)
                be_trigger_price = entry * (1 - BREAK_EVEN_TRIGGER_PCT / 100)
                sl_price = entry if position["break_even_triggered"] else entry * (1 + STOP_LOSS_PCT / 100)

                # Gap at open takes priority
                if exec_price >= sl_price:
                    exit_price, exit_reason = exec_price, "STOP_LOSS"
                elif exec_price <= tp_price:
                    exit_price, exit_reason = exec_price, "TAKE_PROFIT"
                else:
                    # Activate break-even if candle low reached trigger
                    if not position["break_even_triggered"] and candle_low <= be_trigger_price:
                        position["break_even_triggered"] = True
                        sl_price = entry
                    # Intracandle SL/TP — if both hit, assume SL first (conservative)
                    if candle_high >= sl_price and candle_low <= tp_price:
                        exit_price, exit_reason = sl_price, "STOP_LOSS"
                    elif candle_high >= sl_price:
                        exit_price, exit_reason = sl_price, "STOP_LOSS"
                    elif candle_low <= tp_price:
                        exit_price, exit_reason = tp_price, "TAKE_PROFIT"
                    elif signal == "BUY":
                        exit_price, exit_reason = exec_price, "BUY"

                if exit_price is not None:
                    pct_return = (entry - exit_price) / entry * 100 - ROUND_TRIP_FEE_PCT

            if exit_price is not None:
                trades.append({
                    "entry_time":           position["entry_time"],
                    "exit_time":            exec_time.isoformat(),
                    "entry_price":          round(entry, 4),
                    "exit_price":           round(exit_price, 4),
                    "pct_return":           round(pct_return, 4),
                    "exit_reason":          exit_reason,
                    "break_even_triggered": position["break_even_triggered"],
                    "direction":            direction,
                })
                position       = None
                cooldown_until = exec_time + timedelta(minutes=45)

                # Circuit-breaker loss tracking
                if pct_return <= 0:
                    consecutive_losses += 1
                    if consecutive_losses >= CB_LOSS_THRESHOLD:
                        cb_start = exec_time
                        cb_end   = exec_time + timedelta(hours=CB_PAUSE_HOURS)
                        cb_until = cb_end
                        cb_events.append({
                            "circuit_breaker_triggered": True,
                            "circuit_breaker_start":     cb_start.isoformat(),
                            "circuit_breaker_end":       cb_end.isoformat(),
                            "blocked_entries_count":     0,
                        })
                        consecutive_losses = 0  # reset after trigger
                else:
                    consecutive_losses = 0  # winning trade resets the streak

        signal_log.append(log_entry)

    # Force-close any open position at the last candle's close
    if position is not None:
        last      = df_ind.iloc[-1]
        direction = position["direction"]
        last_close = float(last["close"])
        entry      = position["entry_price"]
        if direction == "LONG":
            pct_return = (last_close - entry) / entry * 100 - ROUND_TRIP_FEE_PCT
        else:
            pct_return = (entry - last_close) / entry * 100 - ROUND_TRIP_FEE_PCT
        trades.append({
            "entry_time":           position["entry_time"],
            "exit_time":            last.name.isoformat(),
            "entry_price":          round(entry, 4),
            "exit_price":           round(last_close, 4),
            "pct_return":           round(pct_return, 4),
            "exit_reason":          "END_OF_DATA",
            "break_even_triggered": position["break_even_triggered"],
            "direction":            direction,
        })

    return trades, signal_log, cb_events


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------

def compute_summary(
    trades: list[dict],
    df: pd.DataFrame,
    signal_log: list[dict],
    cb_events: list[dict],
) -> dict:
    n = len(trades)

    buy_signals      = sum(1 for s in signal_log if s["signal"] == "BUY")
    sell_signals     = sum(1 for s in signal_log if s["signal"] == "SELL")
    cb_blocked       = sum(1 for s in signal_log if s["signal"] in ("BUY_CIRCUIT_BREAKER", "SELL_CIRCUIT_BREAKER"))
    regime_blocked   = sum(1 for s in signal_log if s["signal"] == "BUY_REGIME_BLOCKED")
    claude_approved  = sum(1 for s in signal_log if s.get("claude_decision") == "APPROVE")
    claude_rejected  = sum(1 for s in signal_log if s.get("claude_decision") == "REJECT")

    base = {
        "candles_evaluated":       len(df),
        "buy_signals_total":       buy_signals,
        "sell_signals_total":      sell_signals,
        "circuit_breaker_events":  len(cb_events),
        "circuit_breaker_blocked": cb_blocked,
        "regime_blocked_longs":    regime_blocked,
        "claude_approved":         claude_approved,
        "claude_rejected":         claude_rejected,
    }

    _empty_side = {"trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0,
                   "cumulative_return_pct": 0.0, "profit_factor": None}

    if n == 0:
        return {
            **base,
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
            "long":                   _empty_side,
            "short":                  _empty_side,
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
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss   = abs(sum(r for r in returns if r < 0))
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

    # Long / short breakdown
    def _side_stats(side_trades: list[dict]) -> dict:
        if not side_trades:
            return _empty_side
        rets  = [t["pct_return"] for t in side_trades]
        w     = sum(1 for r in rets if r > 0)
        eq    = 1.0
        for r in rets:
            eq *= 1 + r / 100
        gp = sum(r for r in rets if r > 0)
        gl = abs(sum(r for r in rets if r < 0))
        return {
            "trades":                len(rets),
            "wins":                  w,
            "losses":                len(rets) - w,
            "win_rate_pct":          round(w / len(rets) * 100, 2),
            "cumulative_return_pct": round((eq - 1) * 100, 4),
            "profit_factor":         round(gp / gl, 4) if gl > 0 else None,
        }

    long_trades  = [t for t in trades if t.get("direction") == "LONG"]
    short_trades = [t for t in trades if t.get("direction") == "SHORT"]

    return {
        **base,
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
        "long":                   _side_stats(long_trades),
        "short":                  _side_stats(short_trades),
    }


def compute_monthly_returns(trades: list[dict]) -> list[dict]:
    """Group trades by exit month and compute compounded return per month."""
    monthly: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        month = t["exit_time"][:7]  # YYYY-MM
        monthly[month].append(t["pct_return"])

    rows = []
    for month in sorted(monthly.keys()):
        month_returns = monthly[month]
        equity = 1.0
        for r in month_returns:
            equity *= 1 + r / 100
        month_wins = sum(1 for r in month_returns if r > 0)
        rows.append({
            "month":      month,
            "trades":     len(month_returns),
            "wins":       month_wins,
            "losses":     len(month_returns) - month_wins,
            "return_pct": round((equity - 1) * 100, 4),
        })
    return rows


# ---------------------------------------------------------------------------
# Output: print, save JSON, save equity curve CSV
# ---------------------------------------------------------------------------

def print_summary(summary: dict, trades: list[dict], cb_events: list[dict]) -> None:
    print()
    print("=" * 60)
    print(f"  BACKTEST RESULTS — Stage A   [{SYMBOL}]")
    print(f"  Dataset   : {PATH_15M}")
    print(f"  Timeframe : {TIMEFRAME}  |  SL={STOP_LOSS_PCT}%  TP={TAKE_PROFIT_PCT}%  Fee={ROUND_TRIP_FEE_PCT}%")
    regime_status = f"ENABLED (low-vol gate: {'ON' if BLOCK_LONG_LOW_VOL else 'OFF'})" if REGIME_FILTER_LONG else "DISABLED"
    print(f"  Break-even trigger : +{BREAK_EVEN_TRIGGER_PCT}%  |  Regime filter (LONG): {regime_status}")
    print(f"  Circuit breaker    : {CB_LOSS_THRESHOLD} consecutive losses → {CB_PAUSE_HOURS}h pause")
    print("=" * 60)
    print(f"  Candles evaluated      : {summary['candles_evaluated']}")
    print(f"  BUY signals            : {summary['buy_signals_total']}")
    print(f"  SELL signals           : {summary['sell_signals_total']}")
    print(f"  Circuit breaker events : {summary['circuit_breaker_events']}")
    print(f"  CB blocked entries     : {summary['circuit_breaker_blocked']}")
    print(f"  Regime blocked (LONG)  : {summary['regime_blocked_longs']}")
    print(f"  Claude approved        : {summary['claude_approved']}")
    print(f"  Claude rejected        : {summary['claude_rejected']}")
    print(f"  Total trades      : {summary['total_trades']}")
    print(f"  Wins / Losses     : {summary['wins']} / {summary['losses']}")
    print(f"  Win rate          : {summary['win_rate_pct']:.2f}%")
    print(f"  Cumulative return : {summary['cumulative_return_pct']:.4f}%")
    print(f"  Avg return/trade  : {summary['avg_return_pct']:.4f}%")
    print(f"  Best trade        : {summary['best_trade_pct']:.4f}%")
    print(f"  Worst trade       : {summary['worst_trade_pct']:.4f}%")
    print(f"  Max drawdown      : {summary['max_drawdown_pct']:.4f}%")
    pf = summary['profit_factor']
    print(f"  Profit factor     : {pf:.4f}" if pf is not None else "  Profit factor     : N/A (no losses)")
    print(f"  Expectancy        : {summary['expectancy_pct']:.4f}%")
    print(f"  Avg trade duration: {summary['avg_trade_duration_min']:.1f} min")
    print(f"  Longest win streak : {summary['longest_win_streak']}")
    print(f"  Longest loss streak: {summary['longest_loss_streak']}")
    print("=" * 60)

    # Long / short breakdown
    for side_key, label in (("long", "LONG"), ("short", "SHORT")):
        s = summary[side_key]
        pf = s["profit_factor"]
        pf_str = f"{pf:.4f}" if pf is not None else "N/A"
        print(
            f"  {label:<5}  trades={s['trades']:>3}  wins={s['wins']:>3}  "
            f"losses={s['losses']:>3}  wr={s['win_rate_pct']:>6.2f}%  "
            f"cum={s['cumulative_return_pct']:>+8.4f}%  pf={pf_str}"
        )
    print("=" * 60)

    if cb_events:
        print()
        print("  Circuit-breaker activations:")
        for idx, ev in enumerate(cb_events, 1):
            print(
                f"    {idx}. {ev['circuit_breaker_start']}  →  {ev['circuit_breaker_end']}"
                f"  (blocked {ev['blocked_entries_count']} entries)"
            )

    if trades:
        print()
        print("  Trade log:")
        header = f"  {'#':>3}  {'Dir':<5}  {'Entry time':<26} {'Exit time':<26} {'Entry':>10} {'Exit':>10} {'Return':>8}  {'BE':>5}  Reason"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for idx, t in enumerate(trades, 1):
            be  = "Y" if t["break_even_triggered"] else "N"
            dir_label = t.get("direction", "LONG")
            print(
                f"  {idx:>3}  {dir_label:<5}  {t['entry_time']:<26} {t['exit_time']:<26} "
                f"{t['entry_price']:>10.2f} {t['exit_price']:>10.2f} "
                f"{t['pct_return']:>7.4f}%  {be:>5}  {t['exit_reason']}"
            )
    print()


def print_monthly_returns(monthly: list[dict]) -> None:
    print("  Monthly returns:")
    header = f"  {'Month':<10}  {'Trades':>6}  {'Wins':>5}  {'Losses':>6}  {'Return':>9}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in monthly:
        print(
            f"  {row['month']:<10}  {row['trades']:>6}  {row['wins']:>5}  "
            f"{row['losses']:>6}  {row['return_pct']:>+8.4f}%"
        )
    print()


def save_results(
    summary: dict,
    trades: list[dict],
    signal_log: list[dict],
    monthly: list[dict],
    cb_events: list[dict],
) -> None:
    Path(os.path.dirname(OUTPUT_PATH)).mkdir(parents=True, exist_ok=True)
    results = {
        "generated_at":              datetime.now(timezone.utc).isoformat(),
        "symbol":                    SYMBOL,
        "timeframe":                 TIMEFRAME,
        "stop_loss_pct":             STOP_LOSS_PCT,
        "take_profit_pct":           TAKE_PROFIT_PCT,
        "break_even_trigger_pct":    BREAK_EVEN_TRIGGER_PCT,
        "fee_pct":                   ROUND_TRIP_FEE_PCT,
        "cb_loss_threshold":         CB_LOSS_THRESHOLD,
        "cb_pause_hours":            CB_PAUSE_HOURS,
        "regime_filter_long":        REGIME_FILTER_LONG,
        "block_long_low_vol":        BLOCK_LONG_LOW_VOL,
        "summary":                   summary,
        "circuit_breaker_events":    cb_events,
        "monthly_returns":           monthly,
        "trades":                    trades,
        "signal_log":                signal_log,
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[backtest] Results saved → {OUTPUT_PATH}")


def save_equity_curve(trades: list[dict]) -> None:
    equity = 1.0
    rows = []
    for i, t in enumerate(trades, 1):
        equity *= 1 + t["pct_return"] / 100
        rows.append({
            "trade_number":          i,
            "exit_time":             t["exit_time"],
            "trade_return_pct":      t["pct_return"],
            "cumulative_return_pct": round((equity - 1) * 100, 4),
            "equity_multiple":       round(equity, 6),
        })
    Path(os.path.dirname(EQUITY_CURVE_PATH)).mkdir(parents=True, exist_ok=True)
    with open(EQUITY_CURVE_PATH, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["trade_number", "exit_time", "trade_return_pct",
                        "cumulative_return_pct", "equity_multiple"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"[backtest] Equity curve saved → {EQUITY_CURVE_PATH}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"[backtest] Loading 15m dataset : {PATH_15M}")
    df = load_dataset(PATH_15M)
    print(f"[backtest] {len(df)} candles  ({df.index[0].isoformat()} → {df.index[-1].isoformat()})")

    print(f"[backtest] Loading 1h dataset  : {PATH_1H}")
    df_1h = load_dataset(PATH_1H)
    print(f"[backtest] {len(df_1h)} 1h candles ({df_1h.index[0].isoformat()} → {df_1h.index[-1].isoformat()})")

    filter_status = "Claude filter: ENABLED" if ENABLE_CLAUDE_FILTER else "Claude filter: DISABLED"
    print(
        f"[backtest] Running {SYMBOL} (warmup={MIN_WARMUP}, MTF enabled, "
        f"BE=+{BREAK_EVEN_TRIGGER_PCT}%, CB={CB_LOSS_THRESHOLD}L→{CB_PAUSE_HOURS}h, {filter_status}) ..."
    )

    trades, signal_log, cb_events = run_backtest(df, df_1h)

    summary = compute_summary(trades, df, signal_log, cb_events)
    monthly = compute_monthly_returns(trades)

    print_summary(summary, trades, cb_events)
    print_monthly_returns(monthly)

    save_results(summary, trades, signal_log, monthly, cb_events)
    save_equity_curve(trades)


if __name__ == "__main__":
    main()
