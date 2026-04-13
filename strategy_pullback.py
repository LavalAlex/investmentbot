import pandas as pd
from indicators_v2 import ema, slope, efficiency_ratio

# ── EXP001 parameters ────────────────────────────────────────────────────────
EMA_PERIOD = 20          # period for trend / pullback EMA on 1h
SLOPE_LOOKBACK = 5       # bars used to measure EMA slope direction
PULLBACK_TOLERANCE = 0.01  # EXP001 only — ±1% proximity to EMA20

# ── EXP002 parameters ────────────────────────────────────────────────────────
EMA50_PERIOD = 50
EMA50_SLOPE_MIN_PCT = 0.05   # EMA50 must have moved ≥ 0.05% over 5 bars (filters flat markets)
EMA50_DIST_MIN_PCT  = 0.005  # price must be ≥ 0.5% away from EMA50 (avoids flat zones)
MIN_BODY_RATIO      = 0.60   # 15m trigger candle body must be ≥ 60% of its range
MIN_RANGE_PCT       = 0.001  # 5-bar avg 15m range must be ≥ 0.1% of price (volatility floor)

# ── EXP003 parameters ────────────────────────────────────────────────────────
ER_WINDOW = 24        # Efficiency Ratio lookback on 1h (24 bars = 24 hours)
MIN_ER    = 0.15      # minimum directional efficiency — below this the market is too choppy


# ── Preparation ─────────────────────────────────────────────────────────────

def prepare_1h(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add EMA20, EMA50, their slopes, and the availability timestamp.
    EXP001 uses only ema20 / ema20_slope.
    EXP002 additionally uses ema50 / ema50_slope_pct plus low_1h / high_1h / close_1h.
    """
    out = df.copy()
    out['ema20'] = ema(out['close'], EMA_PERIOD)
    out['ema20_slope'] = slope(out['ema20'], SLOPE_LOOKBACK)
    out['ema50'] = ema(out['close'], EMA50_PERIOD)
    out['ema50_slope_pct'] = slope(out['ema50'], SLOPE_LOOKBACK) / out['ema50'] * 100
    out['er24'] = efficiency_ratio(out['close'], ER_WINDOW)
    # Mark when this bar's data is available (after it closes)
    out['available_at'] = out['open_time'] + pd.Timedelta(hours=1)
    return out


def prepare_15m(df: pd.DataFrame) -> pd.DataFrame:
    """
    EXP001: returns a clean copy.
    EXP002: also adds avg_range (5-bar rolling mean of high-low).
    """
    out = df.copy()
    out['avg_range'] = (out['high'] - out['low']).rolling(5, min_periods=1).mean()
    return out


# ── Context alignment ────────────────────────────────────────────────────────

def align_1h_to_15m(df_15m: pd.DataFrame, df_1h_prep: pd.DataFrame) -> pd.DataFrame:
    """
    For each 15m bar, attach the most recently *completed* 1h bar's context.
    A 1h bar opened at T is only available after T+1h.
    Includes EXP002 columns (ema50, close_1h, low_1h, high_1h) — ignored by EXP001.
    """
    left = df_15m.sort_values('open_time').reset_index(drop=True)
    right = (
        df_1h_prep[['available_at', 'ema20', 'ema20_slope',
                     'ema50', 'ema50_slope_pct', 'er24',
                     'close', 'low', 'high']]
        .rename(columns={'close': 'close_1h', 'low': 'low_1h', 'high': 'high_1h'})
        .dropna(subset=['ema20', 'ema20_slope'])
        .sort_values('available_at')
        .reset_index(drop=True)
    )
    merged = pd.merge_asof(
        left,
        right,
        left_on='open_time',
        right_on='available_at',
        direction='backward',
    )
    return merged


# ── Signal logic ─────────────────────────────────────────────────────────────

def get_trend(row) -> str | None:
    """
    Returns 'up', 'down', or None based on EMA20 slope on 1h.
    None means flat / no signal.
    """
    if pd.isna(row['ema20_slope']) or pd.isna(row['ema20']):
        return None
    if row['ema20_slope'] > 0:
        return 'up'
    if row['ema20_slope'] < 0:
        return 'down'
    return None


def is_pullback(row) -> bool:
    """
    True when 15m bar's close is within PULLBACK_TOLERANCE of the 1h EMA20.
    This means price has retraced to the EMA20 zone.
    """
    if pd.isna(row['ema20']):
        return False
    dist_pct = abs(row['close'] - row['ema20']) / row['ema20']
    return dist_pct <= PULLBACK_TOLERANCE


def is_entry_trigger(row, trend: str) -> bool:
    """
    15m candle confirms continuation:
      - LONG: bullish candle (close > open)
      - SHORT: bearish candle (close < open)
    """
    if trend == 'up':
        return row['close'] > row['open']
    if trend == 'down':
        return row['close'] < row['open']
    return False


# ── EXP002 filters ───────────────────────────────────────────────────────────

def is_trend_strong(row) -> bool:
    """
    Filter 1 — Trend strength on 1h.
    Two conditions must hold:
      1. EMA50 normalized slope exceeds minimum threshold (trend is moving, not flat).
      2. Price is at least EMA50_DIST_MIN_PCT away from EMA50 (not in a flat zone).
    """
    ema50 = row.get('ema50')
    slope_pct = row.get('ema50_slope_pct')
    if pd.isna(ema50) or pd.isna(slope_pct) or ema50 == 0:
        return False
    if abs(slope_pct) < EMA50_SLOPE_MIN_PCT:
        return False
    dist_from_ema50 = abs(row['close'] - ema50) / ema50
    return dist_from_ema50 >= EMA50_DIST_MIN_PCT


def is_pullback_quality(row, trend: str) -> bool:
    """
    Filter 2 — Pullback quality on 1h (replaces loose ±1% proximity check).
    Requires the 1h bar to have structurally touched EMA20:
      - LONG : bar's low reached EMA20 zone AND close did not break far below it.
      - SHORT: bar's high reached EMA20 zone AND close did not break far above it.
    The 0.2% slack on the touch side allows for near-misses.
    The 0.5% limit on the close side prevents accepting bars that crashed through EMA20.
    """
    low_1h   = row.get('low_1h')
    high_1h  = row.get('high_1h')
    close_1h = row.get('close_1h')
    ema20    = row.get('ema20')
    if any(pd.isna(v) for v in [low_1h, high_1h, close_1h, ema20]):
        return False
    if trend == 'up':
        touched       = low_1h  <= ema20 * 1.002   # low came to within 0.2% of EMA20
        not_collapsed = close_1h >= ema20 * 0.995   # close stayed within 0.5% below EMA20
        return touched and not_collapsed
    else:
        touched       = high_1h  >= ema20 * 0.998
        not_collapsed = close_1h <= ema20 * 1.005
        return touched and not_collapsed


def is_candle_quality(row, trend: str) -> bool:
    """
    Filter 3 — 15m entry candle quality.
    Body must represent at least MIN_BODY_RATIO of the total range.
    Filters out doji and indecision candles.
    """
    candle_range = row['high'] - row['low']
    if candle_range < 1.0:
        return False
    body = abs(row['close'] - row['open'])
    return (body / candle_range) >= MIN_BODY_RATIO


def is_range_sufficient(row) -> bool:
    """
    Filter 4 (optional) — Recent volatility floor.
    5-bar rolling average range must be at least MIN_RANGE_PCT of price.
    Prevents entering during compression / near-zero-volatility periods.
    """
    avg_range = row.get('avg_range')
    if pd.isna(avg_range) or row['close'] == 0:
        return False
    return (avg_range / row['close']) >= MIN_RANGE_PCT


# ── EXP003 filter ─────────────────────────────────────────────────────────────

def is_market_efficient(row) -> bool:
    """
    Filter — Directional efficiency (Kaufman ER) on 1h rolling 24-bar window.

    Measures whether recent price movement was directional or just noise:
      ER = |net displacement over 24h| / sum(|bar-by-bar moves| over 24h)

    Require ER >= MIN_ER (0.15).

    Rationale:
    - ER 0.10–0.15 is the worst zone in both IS and OOS: the market has just
      enough trend signal to fire entries but not enough momentum to reach 2× TP.
    - ER >= 0.15 skips this danger zone while keeping clearly trending conditions.
    - ER < 0.10 (choppy) is filtered; ER 0.10–0.15 (ambiguous) is also filtered;
      ER >= 0.15 (directional) is allowed.
    """
    er24 = row.get('er24')
    if pd.isna(er24):
        return False
    return er24 >= MIN_ER
