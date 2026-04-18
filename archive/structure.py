import pandas as pd


def detect_structure(df: pd.DataFrame, lookback: int = 20) -> str:
    """
    Detect market structure from recent swing highs and lows.
    Uses a simple pivot detection over the last `lookback` candles.
    Returns: 'BULLISH', 'BEARISH', or 'SIDEWAYS'
    """
    if df.empty or len(df) < lookback + 2:
        return "SIDEWAYS"

    window = df.iloc[-(lookback + 2):-1]  # exclude the in-progress candle

    highs = _pivot_highs(window)
    lows = _pivot_lows(window)

    bullish = len(highs) >= 2 and len(lows) >= 2 and _is_ascending(highs) and _is_ascending(lows)
    bearish = len(highs) >= 2 and len(lows) >= 2 and _is_descending(highs) and _is_descending(lows)

    if bullish:
        return "BULLISH"
    if bearish:
        return "BEARISH"
    return "SIDEWAYS"


def _pivot_highs(df: pd.DataFrame) -> list[float]:
    highs = []
    closes = df["high"].values
    for i in range(1, len(closes) - 1):
        if closes[i] > closes[i - 1] and closes[i] > closes[i + 1]:
            highs.append(closes[i])
    return highs


def _pivot_lows(df: pd.DataFrame) -> list[float]:
    lows = []
    closes = df["low"].values
    for i in range(1, len(closes) - 1):
        if closes[i] < closes[i - 1] and closes[i] < closes[i + 1]:
            lows.append(closes[i])
    return lows


def _is_ascending(values: list[float]) -> bool:
    return all(values[i] < values[i + 1] for i in range(len(values) - 1))


def _is_descending(values: list[float]) -> bool:
    return all(values[i] > values[i + 1] for i in range(len(values) - 1))
