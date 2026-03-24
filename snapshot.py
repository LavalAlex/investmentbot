import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def persist_snapshot(
    payload: dict,
    df: pd.DataFrame,
    snapshot_dir: str,
    last_candle_close: datetime | None,
) -> tuple[str | None, datetime | None]:
    """
    Enrich the signal payload with timestamps and persist to disk as JSON.

    Deduplication: if the most recent closed candle has the same close time as
    `last_candle_close`, no snapshot is written and (None, last_candle_close) is returned.

    Returns:
        (file_path, candle_close_time) on success
        (None, last_candle_close) if skipped (duplicate candle)
    """
    if df.empty or len(df) < 2:
        return None, last_candle_close

    # The closed candle is the second-to-last row (last row may be in-progress)
    candle_close_time: datetime = df.index[-2].to_pydatetime()

    if last_candle_close is not None and candle_close_time == last_candle_close:
        return None, last_candle_close

    snapshot_time = datetime.now(timezone.utc)

    enriched = {
        "snapshot_time": snapshot_time.isoformat(),
        "candle_close_time": candle_close_time.isoformat(),
        **payload,
    }

    Path(snapshot_dir).mkdir(parents=True, exist_ok=True)

    symbol_safe = enriched["symbol"].replace("/", "")
    timeframe = enriched["timeframe"]
    candle_ts = candle_close_time.strftime("%Y%m%d_%H%M%S")
    filename = f"{symbol_safe}_{timeframe}_{candle_ts}.json"
    filepath = os.path.join(snapshot_dir, filename)

    with open(filepath, "w") as f:
        json.dump(enriched, f, indent=2)

    return filepath, candle_close_time
