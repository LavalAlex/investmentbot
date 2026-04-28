import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def slope(series: pd.Series, lookback: int = 5) -> pd.Series:
    """Raw change of series over `lookback` periods. Positive = rising, negative = falling."""
    return series.diff(lookback)


def efficiency_ratio(series: pd.Series, window: int = 24) -> pd.Series:
    """
    Kaufman Efficiency Ratio over a rolling `window`.
    ER = |net displacement over window bars| / sum(|bar-by-bar moves| over window bars)

    Range: 0.0 (perfectly choppy — all movement cancels out) to
           1.0 (perfectly trending — price moves in one direction only).

    Undefined (NaN) for the first `window` bars or if total path is zero.
    """
    net_move   = series.diff(window).abs()
    total_path = series.diff(1).abs().rolling(window).sum()
    return net_move.div(total_path.replace(0, float('nan')))


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's Average Directional Index (ADX).

    Measures trend STRENGTH (not direction). Range 0–100:
      > 25 : trending  (use pullback strategy)
      < 20 : ranging   (use mean reversion strategy)
      20–25: transition (no trades)

    Needs columns: high, low, close.
    Uses Wilder smoothing (equivalent to EWM with alpha = 1/period).
    Requires ~3*period bars before values stabilize.
    """
    high  = df['high']
    low   = df['low']
    close = df['close']

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    up_move   = high.diff()
    down_move = -low.diff()

    plus_dm  = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    # Wilder smoothing: com = period-1 → alpha = 1/period
    atr_w    = tr.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(com=period - 1, min_periods=period, adjust=False).mean() / atr_w
    minus_di = 100 * minus_dm.ewm(com=period - 1, min_periods=period, adjust=False).mean() / atr_w

    denom = (plus_di + minus_di).replace(0, float('nan'))
    dx    = 100 * (plus_di - minus_di).abs() / denom
    return dx.ewm(com=period - 1, min_periods=period, adjust=False).mean()
