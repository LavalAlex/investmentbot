import pandas as pd
from indicators import add_indicators, latest_row
from structure import detect_structure


def generate_signal(df: pd.DataFrame, symbol: str, timeframe: str, df_htf: pd.DataFrame | None = None) -> dict:
    """
    Evaluate confluence of all indicators and market structure.
    Returns a signal payload conforming to the required JSON schema.
    Always returns NO_TRADE if data is incomplete or contradictory.
    """
    base = {
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": "NO_TRADE",
        "confidence": "LOW",
        "trend": "MIXED",
        "summary": "",
        "reasons": [],
        "risk_notes": [],
        "invalid_data": False,
    }

    row = latest_row(df)
    if row is None:
        base["summary"] = "Insufficient or malformed data."
        base["invalid_data"] = True
        return base

    close = row["close"]
    ema20 = row["ema20"]
    ema50 = row["ema50"]
    rsi = row["rsi14"]
    atr = row["atr14"]
    vol_ratio = row["vol_ratio"]
    atr_pct = atr / close if close > 0 else float("nan")

    structure = detect_structure(df)
    htf_ema20, htf_ema50, htf_structure, htf_ema200, htf_rsi14 = _htf_confirmation(df_htf)

    reasons = []
    risk_notes = []
    bullish_score = 0
    bearish_score = 0

    # --- Trend ---
    if ema20 > ema50:
        bullish_score += 1
        reasons.append(f"EMA20 ({ema20:.2f}) > EMA50 ({ema50:.2f}): bullish trend")
    elif ema20 < ema50:
        bearish_score += 1
        reasons.append(f"EMA20 ({ema20:.2f}) < EMA50 ({ema50:.2f}): bearish trend")

    if close > ema20:
        bullish_score += 1
        reasons.append(f"Price ({close:.2f}) above EMA20: bullish positioning")
    elif close < ema20:
        bearish_score += 1
        reasons.append(f"Price ({close:.2f}) below EMA20: bearish positioning")

    # --- Momentum ---
    if rsi < 30:
        bullish_score += 1
        reasons.append(f"RSI14 ({rsi:.1f}) oversold: potential bullish reversal")
    elif rsi > 70:
        bearish_score += 1
        reasons.append(f"RSI14 ({rsi:.1f}) overbought: potential bearish reversal")
        risk_notes.append("RSI overbought — momentum may be exhausted")
    elif 40 <= rsi <= 60:
        reasons.append(f"RSI14 ({rsi:.1f}) neutral: no momentum conviction")
    elif rsi > 50:
        bullish_score += 1
        reasons.append(f"RSI14 ({rsi:.1f}) above midline: mild bullish momentum")
    else:
        bearish_score += 1
        reasons.append(f"RSI14 ({rsi:.1f}) below midline: mild bearish momentum")

    # --- Volatility ---
    if pd.notna(atr_pct):
        if atr_pct > 0.03:
            risk_notes.append(f"ATR14 is {atr_pct:.1%} of price — elevated volatility, wider stops needed")
        else:
            reasons.append(f"ATR14 is {atr_pct:.1%} of price — volatility within normal range")

    # --- Volume ---
    if vol_ratio >= 1.5:
        reasons.append(f"Volume ratio {vol_ratio:.2f}x avg — elevated participation")
        if bullish_score > bearish_score:
            bullish_score += 1
        elif bearish_score > bullish_score:
            bearish_score += 1
    elif vol_ratio < 0.7:
        risk_notes.append(f"Volume ratio {vol_ratio:.2f}x avg — low participation, signal may be weak")

    # --- Market structure ---
    if structure == "BULLISH":
        bullish_score += 1
        reasons.append("Market structure: higher highs and higher lows")
    elif structure == "BEARISH":
        bearish_score += 1
        reasons.append("Market structure: lower highs and lower lows")
    else:
        reasons.append("Market structure: sideways or mixed")

    # --- Confluence decision ---
    trend_label = "BULLISH" if bullish_score > bearish_score else ("BEARISH" if bearish_score > bullish_score else "MIXED")
    base["trend"] = trend_label

    total = bullish_score + bearish_score
    dominant = max(bullish_score, bearish_score)
    confidence = _confidence(dominant, total)

    # --- BUY entry filters ---
    # Hard gates: all must pass
    hard_filters = {
        # Trend alignment (15m)
        f"15m EMA20 ({ema20:.2f}) > EMA50 ({ema50:.2f})":            ema20 > ema50,
        # Price above 15m EMA50: confirms price is in bullish territory
        f"Price ({close:.2f}) > 15m EMA50 ({ema50:.2f})":            close > ema50,
        # Trend direction (1h)
        f"1h EMA20 ({htf_ema20:.2f}) > 1h EMA50 ({htf_ema50:.2f})": htf_ema20 > htf_ema50,
        # Macro trend (1h EMA200)
        f"Price ({close:.2f}) > 1h EMA200 ({htf_ema200:.2f})":       close > htf_ema200,
        # Momentum regime: 1h RSI above midline confirms trend strength
        f"1h RSI14 ({htf_rsi14:.1f}) > 50":                          htf_rsi14 > 50,
        # Volatility floor: avoid flat/low-quality conditions
        f"ATR14/price ({atr_pct:.4f}) > 0.002":                      atr_pct > 0.002,
    }
    # Soft gates: at least 2 of 3 must pass
    soft_filters = {
        f"RSI14 ({rsi:.1f}) > 55":                       rsi > 55,
        f"Volume above average (ratio={vol_ratio:.2f})": vol_ratio > 1.0,
        "15m market structure is BULLISH":               structure == "BULLISH",
    }

    hard_pass = all(hard_filters.values())
    soft_passed = [label for label, ok in soft_filters.items() if ok]
    soft_failed = [label for label, ok in soft_filters.items() if not ok]
    soft_pass = len(soft_passed) >= 2

    buy_filters_pass = hard_pass and soft_pass

    # --- SELL entry filters (mirrored from BUY) ---
    # Hard gates: all must pass
    sell_hard_filters = {
        f"15m EMA20 ({ema20:.2f}) < EMA50 ({ema50:.2f})":            ema20 < ema50,
        f"1h EMA20 ({htf_ema20:.2f}) < 1h EMA50 ({htf_ema50:.2f})": htf_ema20 < htf_ema50,
        f"Price ({close:.2f}) < 1h EMA200 ({htf_ema200:.2f})":       close < htf_ema200,
        f"1h RSI14 ({htf_rsi14:.1f}) < 50":                          htf_rsi14 < 50,
        f"ATR14/price ({atr_pct:.4f}) > 0.002":                      atr_pct > 0.002,
    }
    # Soft gates: at least 2 of 3 must pass
    sell_soft_filters = {
        f"RSI14 ({rsi:.1f}) < 50":                       rsi < 50,
        f"Volume above average (ratio={vol_ratio:.2f})": vol_ratio > 1.0,
        "15m market structure is BEARISH":               structure == "BEARISH",
    }

    sell_hard_pass   = all(sell_hard_filters.values())
    sell_soft_passed = [label for label, ok in sell_soft_filters.items() if ok]
    sell_soft_failed = [label for label, ok in sell_soft_filters.items() if not ok]
    sell_filters_pass = sell_hard_pass and len(sell_soft_passed) >= 2

    if bullish_score >= 4 and bullish_score > bearish_score and confidence in ("MEDIUM", "HIGH"):
        if buy_filters_pass:
            base["signal"] = "BUY"
            base["confidence"] = confidence
            base["summary"] = (
                f"Bullish confluence across {bullish_score} factors with {confidence.lower()} confidence. "
                f"Hard filters passed. Soft filters: {len(soft_passed)}/3 met."
            )
        else:
            failed_hard = [label for label, ok in hard_filters.items() if not ok]
            base["signal"] = "NO_TRADE"
            base["confidence"] = confidence
            base["summary"] = (
                f"Bullish confluence present but entry filters not met "
                f"(hard failed: {len(failed_hard)}, soft passed: {len(soft_passed)}/3)."
            )
            for label in failed_hard:
                risk_notes.append(f"Hard filter failed: {label}")
            for label in soft_failed:
                risk_notes.append(f"Soft filter not met: {label}")
    elif bearish_score >= 4 and bearish_score > bullish_score and confidence in ("MEDIUM", "HIGH"):
        if sell_filters_pass:
            base["signal"] = "SELL"
            base["confidence"] = confidence
            base["summary"] = (
                f"Bearish confluence across {bearish_score} factors with {confidence.lower()} confidence. "
                f"Hard filters passed. Soft filters: {len(sell_soft_passed)}/3 met."
            )
        else:
            sell_failed_hard = [label for label, ok in sell_hard_filters.items() if not ok]
            base["signal"] = "NO_TRADE"
            base["confidence"] = confidence
            base["summary"] = (
                f"Bearish confluence present but entry filters not met "
                f"(hard failed: {len(sell_failed_hard)}, soft passed: {len(sell_soft_passed)}/3)."
            )
            for label in sell_failed_hard:
                risk_notes.append(f"Hard filter failed: {label}")
            for label in sell_soft_failed:
                risk_notes.append(f"Soft filter not met: {label}")
    else:
        base["signal"] = "NO_TRADE"
        base["confidence"] = confidence
        base["summary"] = (
            f"Insufficient confluence (bullish={bullish_score}, bearish={bearish_score}). "
            "No clear trade setup."
        )

    base["reasons"] = reasons
    base["risk_notes"] = risk_notes
    return base


def _htf_confirmation(df_htf: pd.DataFrame | None) -> tuple[float, float, str, float, float]:
    """
    Extract EMA20, EMA50, EMA200, RSI14, and market structure from the 1h df.

    Caller must ensure df_htf contains only confirmed-closed candles
    (i.e., the in-progress candle has been removed before passing).
    Uses df.iloc[-1] for indicator values (last confirmed candle).

    Returns (ema20, ema50, structure, ema200, rsi14).
    Returns (nan, nan, "SIDEWAYS", nan, nan) when data is absent or
    insufficient — this causes all HTF hard filters to fail, blocking BUY
    per the project's incomplete-data policy.

    Note: EMA200 accuracy requires ~200+ 1h candles. Ensure HTF_CANDLE_LIMIT
    in main.py (and fetch_history.py DAYS_1H) provides sufficient history.
    """
    _fallback = (float("nan"), float("nan"), "SIDEWAYS", float("nan"), float("nan"))

    if df_htf is None or df_htf.empty:
        return _fallback

    df_ind = add_indicators(df_htf)
    if df_ind.empty:
        return _fallback

    row = df_ind.iloc[-1]
    required = ["ema20", "ema50", "ema200", "rsi14"]
    if row[required].isnull().any():
        return _fallback

    structure = detect_structure(df_ind)
    return (
        float(row["ema20"]),
        float(row["ema50"]),
        structure,
        float(row["ema200"]),
        float(row["rsi14"]),
    )


def _confidence(dominant: int, total: int) -> str:
    if total == 0:
        return "LOW"
    ratio = dominant / total
    if ratio >= 0.85 and dominant >= 4:
        return "HIGH"
    if ratio >= 0.70 and dominant >= 3:
        return "MEDIUM"
    return "LOW"
