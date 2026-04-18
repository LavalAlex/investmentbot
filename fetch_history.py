"""
Fetch historical OHLCV data from Binance Spot for backtesting.

Fetches for BTC/USDT:
  - 180 days of 5m  candles → data/BTCUSDT_5m_last_180d.csv
  - 180 days of 15m candles → data/BTCUSDT_15m_last_180d.csv
  - 200 days of 1h  candles → data/BTCUSDT_1h_last_200d.csv
    (200d of 1h = 4800 candles, providing a full EMA200 warmup buffer
    before the first 15m/5m candle regardless of backtest window size.)

Usage:
    python3 fetch_history.py
"""

import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.exchange import create_exchange

SYMBOL = "BTC/USDT"
SYMBOL_RAW = "BTCUSDT"

DAYS_5M  = 180
DAYS_15M = 180
DAYS_1H  = 200

OUTPUT_DIR = "data"

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trade_count",
    "taker_buy_base_volume", "taker_buy_quote_volume",
]


def fetch_candles(exchange, symbol: str, interval: str, days: int) -> list[dict]:
    """
    Fetch `days` worth of `interval` candles for `symbol` from Binance Spot.
    Paginates automatically when the requested range exceeds 1000 candles.
    Returns a deduplicated, timestamp-sorted list of row dicts.

    Raises RuntimeError if no data is returned.
    """
    symbol_raw = symbol.replace("/", "")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    print(f"[fetch] {symbol} {interval} ({days}d) "
          f"from {datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).isoformat()}")

    all_rows = []
    batch_start = since_ms
    page = 0

    while batch_start < now_ms:
        page += 1
        try:
            raw = exchange.publicGetKlines({
                "symbol":    symbol_raw,
                "interval":  interval,
                "startTime": batch_start,
                "limit":     1000,
            })
        except Exception as e:
            raise RuntimeError(
                f"Fetch failed for {symbol} {interval} (page {page}): {e}"
            ) from e

        if not raw:
            break

        for entry in raw:
            # Binance kline fields (indices 0–10, index 11 is ignored):
            # 0: open_time, 1: open, 2: high, 3: low, 4: close, 5: volume,
            # 6: close_time, 7: quote_asset_volume, 8: num_trades,
            # 9: taker_buy_base, 10: taker_buy_quote, 11: ignored
            all_rows.append({
                "open_time":              _ms_to_iso(int(entry[0])),
                "open":                   float(entry[1]),
                "high":                   float(entry[2]),
                "low":                    float(entry[3]),
                "close":                  float(entry[4]),
                "volume":                 float(entry[5]),
                "close_time":             _ms_to_iso(int(entry[6])),
                "quote_volume":           float(entry[7]),
                "trade_count":            int(entry[8]),
                "taker_buy_base_volume":  float(entry[9]),
                "taker_buy_quote_volume": float(entry[10]),
            })

        if len(raw) < 1000:
            break  # fewer than requested — no more pages

        last_open_ms = int(raw[-1][0])
        batch_start = last_open_ms + 1  # advance past the last received candle

    if not all_rows:
        raise RuntimeError(f"No data returned from Binance for {symbol} {interval}.")

    all_rows = _deduplicate_and_sort(all_rows)

    print(f"[fetch] {symbol} {interval}: {len(all_rows)} candles "
          f"({all_rows[0]['open_time']} → {all_rows[-1]['close_time']})")
    return all_rows


def save_csv(rows: list[dict], path: str) -> None:
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[fetch] Saved {len(rows)} rows → {path}")


def _deduplicate_and_sort(rows: list[dict]) -> list[dict]:
    """Remove duplicate open_time entries and sort ascending by open_time."""
    seen: set[str] = set()
    unique = []
    for row in rows:
        if row["open_time"] not in seen:
            seen.add(row["open_time"])
            unique.append(row)
    return sorted(unique, key=lambda r: r["open_time"])


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    exchange = create_exchange()

    rows_5m = fetch_candles(exchange, SYMBOL, "5m", DAYS_5M)
    save_csv(rows_5m, f"{OUTPUT_DIR}/{SYMBOL_RAW}_5m_last_{DAYS_5M}d.csv")

    rows_15m = fetch_candles(exchange, SYMBOL, "15m", DAYS_15M)
    save_csv(rows_15m, f"{OUTPUT_DIR}/{SYMBOL_RAW}_15m_last_{DAYS_15M}d.csv")

    rows_1h = fetch_candles(exchange, SYMBOL, "1h", DAYS_1H)
    save_csv(rows_1h, f"{OUTPUT_DIR}/{SYMBOL_RAW}_1h_last_{DAYS_1H}d.csv")

    print("\n[fetch] BTC/USDT data fetched successfully.")
