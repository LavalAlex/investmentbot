def calculate_sl_tp(
    entry: float,
    direction: str,
    candle_low: float,
    candle_high: float,
) -> tuple[float, float] | tuple[None, None]:
    """
    Place SL at the trigger candle's natural extreme.
    TP is set at 2× the risk distance (R:R = 2:1).

    Returns (sl, tp) or (None, None) if risk distance is zero.
    """
    if direction == 'long':
        sl = candle_low
        risk = entry - sl
        if risk <= 0:
            return None, None
        tp = entry + 2.0 * risk

    else:  # short
        sl = candle_high
        risk = sl - entry
        if risk <= 0:
            return None, None
        tp = entry - 2.0 * risk

    return sl, tp


def check_exit(
    direction: str,
    sl: float,
    tp: float,
    candle,
) -> tuple[str, float] | None:
    """
    Check whether SL or TP was hit on `candle`.
    If both are hit (same candle), resolve by candle direction:
      - bearish candle → assume SL hit first for LONG, TP hit first for SHORT
      - bullish candle → assume TP hit first for LONG, SL hit first for SHORT
    Returns (reason, exit_price) or None.
    """
    if direction == 'long':
        sl_hit = candle['low'] <= sl
        tp_hit = candle['high'] >= tp
    else:
        sl_hit = candle['high'] >= sl
        tp_hit = candle['low'] <= tp

    if sl_hit and tp_hit:
        bearish = candle['close'] < candle['open']
        if direction == 'long':
            return ('SL', sl) if bearish else ('TP', tp)
        else:
            return ('SL', sl) if not bearish else ('TP', tp)

    if sl_hit:
        return 'SL', sl
    if tp_hit:
        return 'TP', tp
    return None
