# Experiment 017 — Block SHORT in Low-Volatility 1h Environments

**Date:** 2026-03-24
**Status:** REVERTED

---

## Hypothesis

BLOCK_LONG_LOW_VOL already exists in the codebase (disabled). Dec 2025 had 0%
SHORT WR (6 trades, all losses) — likely a choppy consolidation period. SHORT TP
is 2.2%, requiring sustained momentum. Low-volatility conditions (1h ATR < its
expanding historical median) don't sustain this momentum.

**Change:** Added `BLOCK_SHORT_LOW_VOL = True` — block SHORT when 1h ATR < expanding median
**Expected improvement:** Filter Dec-type choppy months, improve SHORT PF

---

## Results

| Metric | Baseline | Exp 017 (SHORT low-vol filter) | Δ |
|--------|----------|--------------------------------|---|
| Total trades | 134 | 120 | -14 |
| Win rate | 35.07% | 32.50% | -2.57pp |
| Cumulative return | +15.41% | +0.90% | -14.51pp |
| Max drawdown | 8.29% | 12.88% | +4.59pp |
| Profit factor | 1.2784 | 1.0292 | -0.249 |
| SHORT trades | 73 | 59 | -14 |
| SHORT WR | 30.14% | 23.73% | -6.41pp |
| SHORT PF | 1.3516 | 0.9474 | -0.404 |
| Low-vol SHORT blocked | 0 | 48 | +48 |

---

## Analysis

The filter blocked 48 SHORT entries and made SHORT PF collapse to 0.9474 (negative
expectancy). The 48 blocked SHORTs were collectively profitable.

The intuition was wrong: high-volatility periods are the BEST time for SHORTs (large
ATR → more room to hit 2.2% TP). The "low-volatility SHORTs" that were blocked turned
out to be slow grinders that also reach TP, just more gradually.

Conversely, even high-volatility SHORTs can hit SL (they move 0.6% adversely just as
easily). The ATR filter doesn't cleanly separate good from bad SHORT setups.

The 14-trade reduction in SHORTs removed more good trades than bad ones, destroying
the SHORT PF.

BLOCK_SHORT_LOW_VOL left in codebase as `False`.

---

## Decision: REVERT

`BLOCK_SHORT_LOW_VOL = False`. Volatility level alone is not a useful SHORT filter.

---

## Insight for Future Research

Unlike LONGs (where BLOCK_LONG_LOW_VOL was designed for breakout failure in flat
conditions), SHORTs can work in any volatility environment when the trend is down.
A flat market that's trending down slowly can still produce 2.2% drops. Volatility
filtering removes too many valid SHORT setups.
