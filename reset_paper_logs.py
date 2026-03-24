"""
Reset the paper trading environment to a clean initial state.

Usage:
    python3 reset_paper_logs.py

Safe to run only when the paper monitor is NOT running.
Deletes all log files and writes a fresh paper_state.json with 100 USD equity.
"""

import json
import os
from pathlib import Path

LOGS_DIR = "logs"

FILES_TO_DELETE = [
    f"{LOGS_DIR}/paper_trading_events.txt",
    f"{LOGS_DIR}/paper_trades.csv",
    f"{LOGS_DIR}/paper_daily_summary.txt",
]

STATE_PATH    = f"{LOGS_DIR}/paper_state.json"
INITIAL_EQUITY = 100.0

FRESH_STATE = {
    "equity":             INITIAL_EQUITY,
    "position":           None,
    "pending_signal":     None,
    "last_candle_time":   None,
    "consecutive_losses": 0,
    "cb_until":           None,
    "cooldown_until":     None,
    "last_summary_date":  None,
    "trade_id_counter":   0,
    "daily_trades":       [],
}


def main() -> None:
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)

    for path in FILES_TO_DELETE:
        if os.path.exists(path):
            os.remove(path)
            print(f"  deleted : {path}")
        else:
            print(f"  skipped : {path}  (not found)")

    with open(STATE_PATH, "w") as f:
        json.dump(FRESH_STATE, f, indent=2)
    print(f"  created : {STATE_PATH}  (equity={INITIAL_EQUITY:.2f} USD, all counters reset)")

    print()
    print(f"[RESET] Paper trading logs cleared. Ready to start fresh with {INITIAL_EQUITY:.0f} USD.")


if __name__ == "__main__":
    main()
