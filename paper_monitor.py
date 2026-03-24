"""
Paper trading monitor for BTC/USDT — paper mode only.

Runs the current approved BTC strategy continuously on live market data.
No real orders. No real execution. Simulates positions and records everything.

Usage:
    python3 paper_monitor.py            # start (or resume from saved state)

Stop:
    Ctrl+C  — state is saved on every candle and on shutdown

Log files (all in logs/):
    paper_trading_events.txt  — human-readable append log (every event)
    paper_trades.csv          — one row per completed trade
    paper_daily_summary.txt   — one block per UTC day
    paper_state.json          — persistent state for crash-safe restart
"""

import csv
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config import SYMBOL
from exchange import create_exchange, fetch_ohlcv
from indicators import add_indicators
from signal_engine import generate_signal

# ---------------------------------------------------------------------------
# Strategy parameters — must match backtest.py exactly
# ---------------------------------------------------------------------------

TIMEFRAME               = "15m"
HTF_TIMEFRAME           = "1h"
CANDLE_LIMIT            = 250       # enough for EMA200 warmup + indicators
HTF_CANDLE_LIMIT        = 250

STOP_LOSS_PCT           = 0.6
TAKE_PROFIT_PCT         = 1.2       # LONG
SHORT_TAKE_PROFIT_PCT   = 2.2       # SHORT
BREAK_EVEN_TRIGGER_PCT  = 0.8
FEE_PER_SIDE_PCT        = 0.1
ROUND_TRIP_FEE_PCT      = FEE_PER_SIDE_PCT * 2

CB_LOSS_THRESHOLD       = 2
CB_PAUSE_HOURS          = 48
COOLDOWN_MINUTES        = 45

# Block LONG entries when last confirmed 1h candle closed below 1h EMA200
REGIME_FILTER_LONG      = True

# ---------------------------------------------------------------------------
# Paper trading settings
# ---------------------------------------------------------------------------

INITIAL_EQUITY  = 100.0     # USD
POLL_SECONDS    = 60        # how often to poll for new candles

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

LOGS_DIR            = "logs"
STATE_PATH          = f"{LOGS_DIR}/paper_state.json"
EVENTS_PATH         = f"{LOGS_DIR}/paper_trading_events.txt"
TRADES_CSV_PATH     = f"{LOGS_DIR}/paper_trades.csv"
DAILY_SUMMARY_PATH  = f"{LOGS_DIR}/paper_daily_summary.txt"

TRADES_CSV_FIELDS = [
    "trade_id", "opened_at", "closed_at", "side",
    "entry_price", "exit_price", "stop_loss_price", "take_profit_price",
    "break_even_triggered", "exit_reason",
    "gross_pnl_pct", "net_pnl_pct",
    "gross_pnl_usd", "net_pnl_usd",
    "entry_fee_usd", "exit_fee_usd",
    "equity_before", "equity_after",
    # intra-trade analytics (added in v2)
    "mfe_pct", "mae_pct", "tp_progress_max", "sl_progress_max",
]


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _default_state() -> dict:
    return {
        "equity":               INITIAL_EQUITY,
        "position":             None,   # open position dict or None
        "pending_signal":       None,   # {"direction": "LONG"|"SHORT", "signal_time": "..."}
        "last_candle_time":     None,   # ISO str of last processed 15m candle
        "consecutive_losses":   0,
        "cb_until":             None,   # ISO str — circuit breaker end
        "cooldown_until":       None,   # ISO str — post-trade cooldown end
        "last_summary_date":    None,   # "YYYY-MM-DD" — last UTC day that was summarised
        "trade_id_counter":     0,
        "daily_trades":         [],     # trade records for the current UTC day
    }


def load_state() -> dict:
    """Load persisted state. Falls back to defaults for any missing keys."""
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            data = json.load(f)
        defaults = _default_state()
        for key, val in defaults.items():
            data.setdefault(key, val)
        return data
    return _default_state()


def save_state(state: dict) -> None:
    """Atomically write state to disk (tmp → rename, crash-safe)."""
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, STATE_PATH)


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def log_event(msg: str) -> None:
    """Append a timestamped line to the events file and print to console."""
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
    line = f"[{_ts()}] {msg}"
    with open(EVENTS_PATH, "a") as f:
        f.write(line + "\n")
    print(line)


def write_trade_to_csv(trade: dict) -> None:
    """Append one completed trade row to the CSV file."""
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
    new_file = not os.path.exists(TRADES_CSV_PATH)
    with open(TRADES_CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADES_CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({k: trade.get(k, "") for k in TRADES_CSV_FIELDS})


def write_daily_summary(date_str: str, trades: list, equity: float) -> None:
    """Append a formatted daily summary block to the summary file."""
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
    n       = len(trades)
    wins    = sum(1 for t in trades if float(t.get("net_pnl_usd", 0)) > 0)
    losses  = n - wins
    pnl_usd = sum(float(t.get("net_pnl_usd", 0)) for t in trades)
    pnl_pct = sum(float(t.get("net_pnl_pct", 0)) for t in trades)
    wr_str  = f"{wins / n * 100:.1f}%" if n > 0 else "N/A"

    lines = [
        "",
        "=" * 58,
        f"  DAILY SUMMARY  —  {date_str} UTC",
        f"  Trades    : {n}",
        f"  Wins      : {wins}",
        f"  Losses    : {losses}",
        f"  Win rate  : {wr_str}",
        f"  PnL USD   : {pnl_usd:+.4f}",
        f"  PnL %     : {pnl_pct:+.4f}%",
        f"  End equity: {equity:.4f} USD",
        "=" * 58,
        "",
    ]
    with open(DAILY_SUMMARY_PATH, "a") as f:
        for line in lines:
            f.write(line + "\n")
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Regime filter (replicates backtest.py REGIME_FILTER_LONG logic)
# ---------------------------------------------------------------------------

def is_bearish_regime(df_htf_raw: pd.DataFrame) -> bool:
    """
    Returns True when the last confirmed 1h candle closed below the 1h EMA200.
    Drops the last row (in-progress 1h candle) before computing indicators,
    matching the no-lookahead rule used in the backtest.
    Falls back to False (allow LONG) if data is insufficient.
    """
    if df_htf_raw is None or df_htf_raw.empty or len(df_htf_raw) < 2:
        return False

    # Drop the in-progress (last) 1h candle — only use confirmed closes
    df = add_indicators(df_htf_raw.iloc[:-1].copy())
    if df.empty or "ema200" not in df.columns:
        return False

    last = df.iloc[-1]
    ema200 = last.get("ema200", float("nan"))
    if pd.isna(ema200):
        return False

    return float(last["close"]) < float(ema200)


# ---------------------------------------------------------------------------
# Position management
# ---------------------------------------------------------------------------

def _next_trade_id(state: dict) -> str:
    state["trade_id_counter"] += 1
    return f"PT-{state['trade_id_counter']:04d}"


def _compute_sl_tp(direction: str, entry: float) -> tuple[float, float]:
    if direction == "LONG":
        sl = entry * (1 - STOP_LOSS_PCT / 100)
        tp = entry * (1 + TAKE_PROFIT_PCT / 100)
    else:
        sl = entry * (1 + STOP_LOSS_PCT / 100)
        tp = entry * (1 - SHORT_TAKE_PROFIT_PCT / 100)
    return round(sl, 2), round(tp, 2)


def open_position(state: dict, direction: str, entry_price: float, candle_time: str) -> None:
    """
    Open a paper position. Updates state['position'].
    Entry fee is deducted from equity tracking but does not change state equity
    (fees are settled at close via net_pnl).
    """
    equity = state["equity"]
    sl, tp = _compute_sl_tp(direction, entry_price)
    entry_fee_usd = round(equity * FEE_PER_SIDE_PCT / 100, 6)
    trade_id = _next_trade_id(state)

    state["position"] = {
        "trade_id":             trade_id,
        "direction":            direction,
        "entry_price":          entry_price,
        "entry_time":           candle_time,
        "sl_price":             sl,
        "tp_price":             tp,
        "break_even_triggered": False,
        "equity_before":        equity,
        "entry_fee_usd":        entry_fee_usd,
        # intra-trade analytics
        "mfe_pct":              0.0,
        "mae_pct":              0.0,
        "tp_progress_max":      0.0,
        "sl_progress_max":      0.0,
    }

    log_event(
        f"[OPEN]  {direction:<5} | entry={entry_price:>10.2f}"
        f" | sl={sl:>10.2f} | tp={tp:>10.2f}"
        f" | equity={equity:.4f} USD | id={trade_id}"
    )


def close_position(
    state: dict,
    exit_price: float,
    exit_reason: str,
    candle_time: str,
) -> dict:
    """
    Close the open paper position. Computes P&L, updates equity, logs to
    events file and trades CSV. Returns the completed trade record dict.
    """
    pos       = state["position"]
    direction = pos["direction"]
    entry     = pos["entry_price"]
    eq_before = pos["equity_before"]

    # Gross P&L (pre-fee)
    if direction == "LONG":
        gross_pct = (exit_price - entry) / entry * 100
    else:
        gross_pct = (entry - exit_price) / entry * 100

    exit_fee_usd  = round(eq_before * FEE_PER_SIDE_PCT / 100, 6)
    net_pct       = gross_pct - ROUND_TRIP_FEE_PCT
    gross_pnl_usd = round(eq_before * gross_pct / 100, 6)
    net_pnl_usd   = round(eq_before * net_pct   / 100, 6)
    eq_after      = round(eq_before + net_pnl_usd, 6)

    trade = {
        "trade_id":             pos["trade_id"],
        "opened_at":            pos["entry_time"],
        "closed_at":            candle_time,
        "side":                 direction,
        "entry_price":          round(entry, 2),
        "exit_price":           round(exit_price, 2),
        "stop_loss_price":      round(pos["sl_price"], 2),
        "take_profit_price":    round(pos["tp_price"], 2),
        "break_even_triggered": pos["break_even_triggered"],
        "exit_reason":          exit_reason,
        "gross_pnl_pct":        round(gross_pct, 4),
        "net_pnl_pct":          round(net_pct, 4),
        "gross_pnl_usd":        gross_pnl_usd,
        "net_pnl_usd":          net_pnl_usd,
        "entry_fee_usd":        pos["entry_fee_usd"],
        "exit_fee_usd":         exit_fee_usd,
        "equity_before":        round(eq_before, 6),
        "equity_after":         round(eq_after, 6),
        # intra-trade analytics
        "mfe_pct":              round(pos.get("mfe_pct", 0.0), 4),
        "mae_pct":              round(pos.get("mae_pct", 0.0), 4),
        "tp_progress_max":      round(pos.get("tp_progress_max", 0.0), 1),
        "sl_progress_max":      round(pos.get("sl_progress_max", 0.0), 1),
    }

    # Update state
    state["equity"]   = eq_after
    state["position"] = None
    cooldown_end = datetime.fromisoformat(candle_time) + timedelta(minutes=COOLDOWN_MINUTES)
    state["cooldown_until"] = cooldown_end.isoformat()

    # Circuit-breaker tracking
    if net_pnl_usd <= 0:
        state["consecutive_losses"] += 1
        if state["consecutive_losses"] >= CB_LOSS_THRESHOLD:
            cb_end = datetime.fromisoformat(candle_time) + timedelta(hours=CB_PAUSE_HOURS)
            state["cb_until"] = cb_end.isoformat()
            state["consecutive_losses"] = 0
            log_event(
                f"[CB]    Circuit breaker triggered"
                f" — entries blocked until {cb_end.strftime('%Y-%m-%d %H:%M UTC')}"
            )
    else:
        state["consecutive_losses"] = 0

    result = "WIN " if net_pnl_usd > 0 else "LOSS"
    log_event(
        f"[CLOSE] {direction:<5} | entry={entry:>10.2f} | exit={exit_price:>10.2f}"
        f" | reason={exit_reason:<15} | {result}"
        f" | net={net_pnl_usd:>+8.4f} USD ({net_pct:>+.4f}%)"
        f" | equity={eq_after:.4f} USD"
        f" | MFE={trade['mfe_pct']:.2f}% | MAE={trade['mae_pct']:.2f}%"
    )
    write_trade_to_csv(trade)

    # Accumulate for daily summary
    state.setdefault("daily_trades", []).append(trade)

    return trade


# ---------------------------------------------------------------------------
# Intra-trade analytics helpers
# ---------------------------------------------------------------------------

def _update_excursions(pos: dict, c_high: float, c_low: float) -> None:
    """
    Update MFE, MAE, and progress metrics for the open position using the
    current candle's high/low.  Called once per candle before simulate_exit.

    MFE (Max Favorable Excursion): best price reached in our favour.
    MAE (Max Adverse Excursion): worst price reached against us.
    tp_progress_max / sl_progress_max: cumulative maximum fraction of the
      original TP / SL range already covered, expressed as 0–100 %.
    """
    entry     = pos["entry_price"]
    direction = pos["direction"]

    if direction == "LONG":
        tp_range = entry * TAKE_PROFIT_PCT / 100          # distance to original TP
        sl_range = entry * STOP_LOSS_PCT  / 100           # distance to original SL
        fav_move = c_high - entry                         # positive = favourable
        adv_move = entry  - c_low                         # positive = adverse
    else:
        tp_range = entry * SHORT_TAKE_PROFIT_PCT / 100
        sl_range = entry * STOP_LOSS_PCT         / 100
        fav_move = entry  - c_low
        adv_move = c_high - entry

    # Convert to % of entry price
    fav_pct = max(fav_move / entry * 100, 0.0)
    adv_pct = max(adv_move / entry * 100, 0.0)

    pos["mfe_pct"] = max(pos["mfe_pct"], fav_pct)
    pos["mae_pct"] = max(pos["mae_pct"], adv_pct)

    # Progress toward original TP / SL (cap at 100 %)
    if tp_range > 0:
        pos["tp_progress_max"] = min(max(pos["tp_progress_max"],
                                         fav_pct / (tp_range / entry * 100) * 100), 100.0)
    if sl_range > 0:
        pos["sl_progress_max"] = min(max(pos["sl_progress_max"],
                                         adv_pct / (sl_range / entry * 100) * 100), 100.0)


def log_trade_update(pos: dict, candle_close: float, candle_time: str) -> None:
    """
    Emit a [UPDATE] line to the events log for an open position.
    Shows current PnL, MFE, MAE, and progress toward TP/SL.
    Not written to the trades CSV — informational only.
    """
    direction = pos["direction"]
    entry     = pos["entry_price"]

    if direction == "LONG":
        cur_pnl_pct = (candle_close - entry) / entry * 100
    else:
        cur_pnl_pct = (entry - candle_close) / entry * 100

    sign = "+" if cur_pnl_pct >= 0 else ""
    log_event(
        f"[UPDATE] {direction:<5} | entry={entry:>10.2f} | price={candle_close:>10.2f}"
        f" | pnl={sign}{cur_pnl_pct:.2f}%"
        f" | MFE={pos['mfe_pct']:.2f}% | MAE={pos['mae_pct']:.2f}%"
        f" | TP_progress={pos['tp_progress_max']:.0f}%"
        f" | SL_progress={pos['sl_progress_max']:.0f}%"
    )


# ---------------------------------------------------------------------------
# Exit simulation (identical rules to backtest.py)
# ---------------------------------------------------------------------------

def simulate_exit(
    state: dict,
    candle: pd.Series,
    sig: str,
    candle_time: str,
) -> bool:
    """
    Simulate position exit against a confirmed closed candle.

    Checks (in order, matching backtest.py):
      1. Gap at candle open (open gaps through SL or TP)
      2. Break-even activation (candle high/low reaches BE trigger)
      3. Intracandle SL/TP (if both hit, SL wins — conservative)
      4. Signal-flip exit (opposing signal on same candle)

    Modifies state in-place. Returns True if the position was closed.
    """
    pos       = state["position"]
    direction = pos["direction"]
    entry     = pos["entry_price"]

    c_open  = float(candle["open"])
    c_high  = float(candle["high"])
    c_low   = float(candle["low"])
    c_close = float(candle["close"])

    exit_price  = None
    exit_reason = None

    if direction == "LONG":
        tp_price        = entry * (1 + TAKE_PROFIT_PCT / 100)
        be_trigger      = entry * (1 + BREAK_EVEN_TRIGGER_PCT / 100)
        sl_price        = entry if pos["break_even_triggered"] else entry * (1 - STOP_LOSS_PCT / 100)

        # 1. Gap at open
        if c_open <= sl_price:
            exit_price, exit_reason = c_open, "STOP_LOSS"
        elif c_open >= tp_price:
            exit_price, exit_reason = c_open, "TAKE_PROFIT"
        else:
            # 2. Break-even activation
            if not pos["break_even_triggered"] and c_high >= be_trigger:
                pos["break_even_triggered"] = True
                sl_price = entry
                log_event(f"[BE]    LONG  | break-even activated at {entry:.2f}")
            # 3. Intracandle SL/TP (SL takes priority if both hit)
            if c_low <= sl_price and c_high >= tp_price:
                exit_price, exit_reason = sl_price, "STOP_LOSS"
            elif c_low <= sl_price:
                exit_price, exit_reason = sl_price, "STOP_LOSS"
            elif c_high >= tp_price:
                exit_price, exit_reason = tp_price, "TAKE_PROFIT"
            # 4. Signal-flip exit
            elif sig == "SELL":
                exit_price, exit_reason = c_close, "SIGNAL_EXIT"

    else:  # SHORT
        tp_price   = entry * (1 - SHORT_TAKE_PROFIT_PCT / 100)
        be_trigger = entry * (1 - BREAK_EVEN_TRIGGER_PCT / 100)
        sl_price   = entry if pos["break_even_triggered"] else entry * (1 + STOP_LOSS_PCT / 100)

        # 1. Gap at open
        if c_open >= sl_price:
            exit_price, exit_reason = c_open, "STOP_LOSS"
        elif c_open <= tp_price:
            exit_price, exit_reason = c_open, "TAKE_PROFIT"
        else:
            # 2. Break-even activation
            if not pos["break_even_triggered"] and c_low <= be_trigger:
                pos["break_even_triggered"] = True
                sl_price = entry
                log_event(f"[BE]    SHORT | break-even activated at {entry:.2f}")
            # 3. Intracandle SL/TP (SL takes priority if both hit)
            if c_high >= sl_price and c_low <= tp_price:
                exit_price, exit_reason = sl_price, "STOP_LOSS"
            elif c_high >= sl_price:
                exit_price, exit_reason = sl_price, "STOP_LOSS"
            elif c_low <= tp_price:
                exit_price, exit_reason = tp_price, "TAKE_PROFIT"
            # 4. Signal-flip exit
            elif sig == "BUY":
                exit_price, exit_reason = c_close, "SIGNAL_EXIT"

    if exit_price is not None:
        close_position(state, exit_price, exit_reason, candle_time)
        return True

    return False


# ---------------------------------------------------------------------------
# One poll cycle
# ---------------------------------------------------------------------------

def run_cycle(exchange, state: dict) -> None:
    """
    Fetch data, check for a new confirmed candle, manage position, log signals.
    This is the core loop body — called once per POLL_SECONDS.
    """
    now_utc   = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Daily summary boundary check
    # ------------------------------------------------------------------
    last_summary = state.get("last_summary_date")
    if last_summary is not None and last_summary != today_str:
        write_daily_summary(last_summary, state.get("daily_trades", []), state["equity"])
        state["daily_trades"] = []
    state["last_summary_date"] = today_str

    # ------------------------------------------------------------------
    # Fetch market data
    # ------------------------------------------------------------------
    df_raw = fetch_ohlcv(exchange, SYMBOL, TIMEFRAME, CANDLE_LIMIT)
    if df_raw.empty:
        log_event("[WARN]  Empty 15m response — skipping cycle")
        return

    df_htf_raw = fetch_ohlcv(exchange, SYMBOL, HTF_TIMEFRAME, HTF_CANDLE_LIMIT)

    df = add_indicators(df_raw.copy())
    if df.empty:
        log_event("[WARN]  Indicator computation failed — skipping cycle")
        return

    # ------------------------------------------------------------------
    # Identify the last CONFIRMED (fully closed) 15m candle = df.iloc[-2]
    # df.iloc[-1] is the candle currently forming — never use it.
    # ------------------------------------------------------------------
    if len(df) < 2:
        return

    confirmed      = df.iloc[-2]
    confirmed_time = df.index[-2].isoformat()

    # Deduplication: skip if this candle was already processed
    if state["last_candle_time"] == confirmed_time:
        return

    # ------------------------------------------------------------------
    # HTF slice for the signal engine (only fully closed 1h candles)
    # Matches backtest.py: df_1h[df_1h.index < floor(candle_open, 1h)]
    # ------------------------------------------------------------------
    candle_open_dt = df.index[-2]
    htf_cutoff     = candle_open_dt.floor("h")

    if df_htf_raw.empty:
        df_htf_for_signal = pd.DataFrame()
    else:
        df_htf_for_signal = df_htf_raw[df_htf_raw.index < htf_cutoff]

    # ------------------------------------------------------------------
    # Generate signal for the confirmed candle
    # (signal engine uses df.iloc[-2] as latest_row)
    # ------------------------------------------------------------------
    payload = generate_signal(df, SYMBOL, TIMEFRAME, df_htf=df_htf_for_signal)
    sig     = payload["signal"]

    # ------------------------------------------------------------------
    # Step 1 — Execute a pending entry on this candle's open
    # (signal was detected on the PREVIOUS candle; we enter at next open)
    # ------------------------------------------------------------------
    pending = state.get("pending_signal")
    if pending is not None:
        direction   = pending["direction"]
        entry_price = float(confirmed["open"])
        open_position(state, direction, entry_price, confirmed_time)
        state["pending_signal"] = None

    # ------------------------------------------------------------------
    # Step 2 — Simulate exit for any open position
    # (runs even if we just opened above — catches immediate gap SL/TP)
    # ------------------------------------------------------------------
    if state["position"] is not None:
        _update_excursions(
            state["position"],
            float(confirmed["high"]),
            float(confirmed["low"]),
        )
        closed = simulate_exit(state, confirmed, sig, confirmed_time)
        # If position survived this candle, emit a live progress update
        if not closed and state["position"] is not None:
            log_trade_update(state["position"], float(confirmed["close"]), confirmed_time)

    # ------------------------------------------------------------------
    # Step 3 — Check for a new entry signal (only if flat and not pending)
    # ------------------------------------------------------------------
    if state["position"] is None and state["pending_signal"] is None:

        # Cooldown gate
        in_cooldown = False
        if state["cooldown_until"] is not None:
            cooldown_dt = datetime.fromisoformat(state["cooldown_until"])
            candle_dt   = datetime.fromisoformat(confirmed_time)
            if candle_dt < cooldown_dt:
                in_cooldown = True

        # Circuit-breaker gate
        cb_active = False
        if state["cb_until"] is not None:
            cb_dt     = datetime.fromisoformat(state["cb_until"])
            candle_dt = datetime.fromisoformat(confirmed_time)
            if candle_dt < cb_dt:
                cb_active = True

        if not in_cooldown and not cb_active:

            if sig == "BUY":
                if REGIME_FILTER_LONG and is_bearish_regime(df_htf_raw):
                    log_event(
                        f"[BLOCK] BUY blocked — bearish regime"
                        f" (1h close < 1h EMA200) | {confirmed_time}"
                    )
                else:
                    state["pending_signal"] = {
                        "direction":   "LONG",
                        "signal_time": confirmed_time,
                    }
                    log_event(
                        f"[SIGNAL] BUY → pending LONG entry on next candle"
                        f" | conf={payload['confidence']}"
                        f" | {payload['summary'][:90]}"
                    )

            elif sig == "SELL":
                state["pending_signal"] = {
                    "direction":   "SHORT",
                    "signal_time": confirmed_time,
                }
                log_event(
                    f"[SIGNAL] SELL → pending SHORT entry on next candle"
                    f" | conf={payload['confidence']}"
                    f" | {payload['summary'][:90]}"
                )

    # ------------------------------------------------------------------
    # Mark candle as processed and save state
    # ------------------------------------------------------------------
    state["last_candle_time"] = confirmed_time

    # Quiet heartbeat to console (not written to events file)
    pos_info = (
        f"  pos={state['position']['direction']}@{state['position']['entry_price']:.0f}"
        if state["position"]
        else "  flat"
    )
    pending_info = f"  pending={state['pending_signal']['direction']}" if state["pending_signal"] else ""
    print(
        f"  [{_ts()}] candle={confirmed_time[:16]}  sig={sig:<8}"
        f"  eq={state['equity']:.4f} USD{pos_info}{pending_info}"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)

    state = load_state()

    is_fresh = state["equity"] == INITIAL_EQUITY and state["trade_id_counter"] == 0
    if is_fresh:
        log_event(
            f"[START] Paper trading started."
            f" initial_equity={INITIAL_EQUITY:.2f} USD"
            f" | symbol={SYMBOL} | TF={TIMEFRAME}"
            f" | regime_filter={'ON' if REGIME_FILTER_LONG else 'OFF'}"
        )
    else:
        log_event(
            f"[RESUME] Paper trading resumed."
            f" equity={state['equity']:.4f} USD"
            f" | trades_completed={state['trade_id_counter']}"
            f" | position={'OPEN: ' + state['position']['direction'] if state['position'] else 'flat'}"
        )

    print()
    print("=" * 60)
    print("  BTC/USDT Paper Trading Monitor")
    print(f"  Symbol    : {SYMBOL}")
    print(f"  Timeframe : {TIMEFRAME}  (HTF: {HTF_TIMEFRAME})")
    print(f"  Equity    : {state['equity']:.4f} USD")
    print(f"  SL / TP   : {STOP_LOSS_PCT}% / {TAKE_PROFIT_PCT}% (LONG)  {SHORT_TAKE_PROFIT_PCT}% (SHORT)")
    print(f"  BE trigger: +{BREAK_EVEN_TRIGGER_PCT}%")
    print(f"  CB        : {CB_LOSS_THRESHOLD} losses → {CB_PAUSE_HOURS}h pause")
    print(f"  Regime filter (LONG): {'ENABLED' if REGIME_FILTER_LONG else 'DISABLED'}")
    print(f"  Poll      : every {POLL_SECONDS}s")
    print(f"  Logs      : {LOGS_DIR}/")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    exchange = create_exchange()

    # Graceful shutdown on SIGINT / SIGTERM
    def _shutdown(signum, frame):
        print()
        log_event("[STOP]  Paper monitor stopped by user.")
        save_state(state)
        print(f"[paper_monitor] State saved → {STATE_PATH}")
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        try:
            run_cycle(exchange, state)
            save_state(state)
        except Exception as exc:
            log_event(f"[ERROR] Cycle failed: {exc}")
            traceback.print_exc()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
