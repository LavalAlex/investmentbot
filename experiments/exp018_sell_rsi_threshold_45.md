# Experiment 018 — Tighten SELL Hard Filter: 1h RSI14 < 50 → < 45

**Date:** 2026-03-24
**Status:** REVERTED

---

## Hypothesis

Requiring 1h RSI14 < 45 (meaningfully bearish) instead of < 50 (barely below midline)
should filter SHORTs taken in choppy conditions where momentum isn't clearly bearish.
Months like Dec 2025 (0% WR) may have included borderline RSI 45-50 SHORT entries
that didn't have enough momentum to sustain a 2.2% decline.

**Change:** `signal_engine.py`: `htf_rsi14 < 50` → `htf_rsi14 < 45` in sell_hard_filters
**Expected improvement:** Fewer marginal SHORTs, higher SHORT quality and PF

---

## Results

| Metric | Baseline | Exp 018 (RSI < 45) | Δ |
|--------|----------|---------------------|---|
| Total trades | 134 | 128 | -6 |
| Win rate | 35.07% | 32.03% | -3.04pp |
| Cumulative return | +15.41% | +2.18% | -13.23pp |
| Max drawdown | 8.29% | 10.87% | +2.58pp |
| Profit factor | 1.2784 | 1.0519 | -0.226 |
| SHORT trades | 73 | 66 | -7 |
| SHORT WR | 30.14% | 24.24% | -5.9pp |
| SHORT PF | 1.3516 | 0.9989 | -0.353 |

---

## Analysis

Lost 6 winning SHORT trades by requiring RSI < 45. The SHORTs with 1h RSI in the 45-49
range are NOT weak setups — they successfully reach the 2.2% TP. Bearish momentum at
RSI 45-49 on 1h is still sufficient to drive a 2.2% decline from entry.

Key finding: when a 1h RSI < 50 BUY hard filter condition is met alongside all other
SHORT hard filters (EMA cross bearish, price < EMA200), the 1h RSI in the 45-49
range is already a meaningful bearish reading and should not be excluded.

Additionally, checked that 1h RSI > 55 is equivalent to > 50 for BUY (both produce
identical results, confirming BUY signals always have RSI well above 55 when all
other conditions are met).

---

## Decision: REVERT

`signal_engine.py` restored to `htf_rsi14 < 50`. RSI threshold is correctly set.

---

## Insight for Future Research

The RSI < 50 threshold for SELL is non-redundant (it does filter some signals) but
cannot be tightened without losing real winners. The RSI > 50 threshold for BUY is
apparently non-binding (all BUY signals have RSI > 55 anyway). This suggests the BUY
side is already very selective, while the SELL side's RSI gate is meaningfully active.

Future experiments: the signal quality improvement path requires understanding why
specific SHORT setups fail (particularly Dec 2025 and Oct 2025 period). A multi-variable
analysis examining what distinguishes the 22 winning SHORTs from the 51 losing SHORTs
may reveal a pattern not captured by current hard/soft filters.
