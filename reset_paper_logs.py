"""
Reset the paper trading environment to a clean initial state.

Usage:
    python3 reset_paper_logs.py

Safe to run only when paper_monitor.py is NOT running.
Deletes log files and writes a fresh paper_state.json.
"""

import json
import os
from pathlib import Path

INITIAL_EQUITY = 10_000.0
STATE_FILE     = 'paper_state.json'
LOGS_DIR       = 'logs'


def main() -> None:
    # ── Remove state file ─────────────────────────────────────────────────────
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        print(f"  deleted : {STATE_FILE}")
    else:
        print(f"  skipped : {STATE_FILE}  (not found)")

    # ── Remove paper log files ────────────────────────────────────────────────
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)
    removed = 0
    for fname in os.listdir(LOGS_DIR):
        if fname.startswith('paper_') and fname.endswith('.log'):
            path = os.path.join(LOGS_DIR, fname)
            os.remove(path)
            print(f"  deleted : {path}")
            removed += 1
    if removed == 0:
        print(f"  skipped : no paper_*.log files found in {LOGS_DIR}/")

    # ── Write fresh state ─────────────────────────────────────────────────────
    fresh = {
        'equity':    INITIAL_EQUITY,
        'positions': {},
        'trades':    [],
    }
    with open(STATE_FILE, 'w') as f:
        json.dump(fresh, f, indent=2)
    print(f"  created : {STATE_FILE}  (equity={INITIAL_EQUITY:.0f} USD)")

    print(f"\n[RESET] Ready. Start monitor with: python paper_monitor.py --loop")


if __name__ == '__main__':
    main()
