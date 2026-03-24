"""
Binance Signal Analysis System — Phase 1
Modes:
  python main.py           → single-run (default)
  python main.py --monitor → continuous monitoring loop
"""

import argparse
import time
from datetime import datetime, timezone

import config
from claude_filter import review_signal
from exchange import create_exchange, fetch_ohlcv
from indicators import add_indicators, latest_row
from signal_engine import generate_signal
from snapshot import persist_snapshot

HTF_TIMEFRAME = "1h"
HTF_CANDLE_LIMIT = 250  # enough for EMA200 warmup + indicator warmup


def run_once(exchange, last_close: datetime | None) -> datetime | None:
    """
    Fetch data, compute indicators, generate signal, persist snapshot.
    Returns the candle close time used (for dedup tracking), or None on failure.
    """
    df = fetch_ohlcv(exchange, config.SYMBOL, config.TIMEFRAME, config.CANDLE_LIMIT)
    if df.empty:
        print(f"[{config.SYMBOL}] No data returned. Skipping.")
        return last_close

    df = add_indicators(df)
    if df.empty:
        print(f"[{config.SYMBOL}] Indicator calculation failed (insufficient data). Skipping.")
        return last_close

    # Fetch higher timeframe data for multi-timeframe confirmation.
    # Drop the last row (in-progress candle) so only closed candles are passed.
    df_htf_raw = fetch_ohlcv(exchange, config.SYMBOL, HTF_TIMEFRAME, HTF_CANDLE_LIMIT)
    df_htf = df_htf_raw.iloc[:-1] if not df_htf_raw.empty else df_htf_raw

    payload = generate_signal(df, config.SYMBOL, config.TIMEFRAME, df_htf=df_htf)

    if payload["signal"] == "BUY" and config.ENABLE_CLAUDE_FILTER:
        row = latest_row(df)
        claude = review_signal(payload, row)
        payload["claude_filter"] = claude
    else:
        payload["claude_filter"] = None

    filepath, new_close = persist_snapshot(
        payload,
        df,
        config.SNAPSHOT_DIR,
        last_close,
    )

    if filepath is None:
        print(f"[{config.SYMBOL}] No new candle since last snapshot. Skipping.")
    else:
        sig = payload["signal"]
        conf = payload["confidence"]
        trend = payload["trend"]
        candle_ts = new_close.isoformat() if new_close else "unknown"
        claude = payload.get("claude_filter")
        claude_str = f" | claude={claude['decision']}" if claude else ""
        print(f"[{config.SYMBOL}] {sig} | {conf} | trend={trend}{claude_str} | candle_close={candle_ts} → {filepath}")

    return new_close


def main():
    parser = argparse.ArgumentParser(description="Binance Signal Analysis System")
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Run in continuous monitoring mode (loops every MONITOR_INTERVAL_SECONDS)",
    )
    args = parser.parse_args()

    exchange = create_exchange()
    last_close: datetime | None = None
    filter_status = "Claude filter: ENABLED" if config.ENABLE_CLAUDE_FILTER else "Claude filter: DISABLED"

    if not args.monitor:
        print(f"[single-run] Symbol: {config.SYMBOL} | Timeframe: {config.TIMEFRAME} | {filter_status}")
        run_once(exchange, last_close)
        return

    print(f"[monitor] Starting. Symbol: {config.SYMBOL} | Timeframe: {config.TIMEFRAME} | Interval: {config.MONITOR_INTERVAL_SECONDS}s | {filter_status}")
    while True:
        cycle_start = datetime.now(timezone.utc).isoformat()
        print(f"\n[monitor] Cycle at {cycle_start}")
        try:
            last_close = run_once(exchange, last_close)
        except Exception as e:
            print(f"[monitor] ERROR: {e} — continuing")
        time.sleep(config.MONITOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
