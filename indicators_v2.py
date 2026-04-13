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
