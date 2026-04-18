import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute and attach all required indicators to the DataFrame.
    Returns the enriched DataFrame, or an empty DataFrame if input is invalid.
    """
    if df.empty or len(df) < 50:
        return pd.DataFrame()

    df = df.copy()

    # Trend
    df["ema20"]  = df["close"].ewm(span=20,  adjust=False).mean()
    df["ema50"]  = df["close"].ewm(span=50,  adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

    # Momentum — RSI14
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi14"] = 100 - (100 / (1 + rs))

    # Volatility — ATR14
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr14"] = true_range.ewm(com=13, adjust=False).mean()

    # Volume ratio — current vs 20-candle average
    df["vol_avg20"] = df["volume"].rolling(window=20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg20"]

    return df


def latest_row(df: pd.DataFrame) -> pd.Series | None:
    """
    Return the most recent fully-closed candle (second-to-last row).
    The last row may be the in-progress candle, so we use [-2].
    Returns None if data is insufficient or contains NaN in required fields.
    """
    if df.empty or len(df) < 2:
        return None

    row = df.iloc[-2]
    required = ["close", "ema20", "ema50", "rsi14", "atr14", "vol_ratio"]
    if row[required].isnull().any():
        return None

    return row
