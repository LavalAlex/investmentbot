"""
Claude trade quality filter.

Reviews BUY signals from the signal engine and returns APPROVE or REJECT.
Called after signal_engine outputs BUY, before position entry.

Safe failure policy: any error (missing key, API failure, malformed response)
defaults to REJECT, consistent with the project rule of preferring NO_TRADE
over uncertain setups.
"""

import json

import anthropic
import pandas as pd

from config import ANTHROPIC_API_KEY, CLAUDE_FILTER_MODEL

_SYSTEM_PROMPT = """\
You are a trade quality filter for a BTC/USDT spot trading system on the 15m timeframe.

A signal engine has already passed this setup through multiple technical filters \
(EMA alignment, RSI range, volume, market structure, 1h trend confirmation). \
Your role is a final quality check.

Return ONLY valid JSON with no markdown, no explanation outside the JSON:
{"decision": "APPROVE" or "REJECT", "reason": "<one concise sentence>"}

APPROVE if:
- Momentum is clearly aligned with the trend
- RSI is in a healthy range (not borderline, not overextended)
- Volume confirms participation
- No significant risk flags

REJECT if:
- Risk notes indicate elevated volatility or weak participation
- Confluence looks marginal or mixed
- The setup appears overextended or entered in chop
- Any required data is missing or suspicious

When in doubt, REJECT. Capital preservation is the priority.\
"""


def review_signal(payload: dict, row: pd.Series) -> dict:
    """
    Send a BUY signal payload and current indicator values to Claude for review.

    Args:
        payload: full signal dict from generate_signal (signal == "BUY")
        row:     the latest closed candle row with computed indicators

    Returns:
        {"decision": "APPROVE" | "REJECT", "reason": str}
    """
    if not ANTHROPIC_API_KEY:
        return {
            "decision": "REJECT",
            "reason": "ANTHROPIC_API_KEY not configured — filter defaulting to REJECT.",
        }

    market_context = {
        "close":      round(float(row["close"]), 2),
        "ema20":      round(float(row["ema20"]), 2),
        "ema50":      round(float(row["ema50"]), 2),
        "rsi14":      round(float(row["rsi14"]), 2),
        "atr14_pct":  round(float(row["atr14"]) / float(row["close"]) * 100, 3),
        "vol_ratio":  round(float(row["vol_ratio"]), 3),
    }

    message_body = json.dumps(
        {"signal_payload": payload, "market_context": market_context},
        indent=2,
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_FILTER_MODEL,
            max_tokens=128,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message_body}],
        )
        raw = response.content[0].text.strip()
        result = json.loads(raw)
        decision = str(result.get("decision", "")).upper()
        reason = str(result.get("reason", ""))
        if decision not in ("APPROVE", "REJECT"):
            return {
                "decision": "REJECT",
                "reason": f"Unexpected decision value '{decision}' — defaulting to REJECT.",
            }
        return {"decision": decision, "reason": reason}

    except Exception as e:
        return {"decision": "REJECT", "reason": f"Filter error: {e}"}
