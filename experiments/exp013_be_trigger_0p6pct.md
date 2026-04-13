# Experiment 013 — Lower Break-Even Trigger: 0.8% → 0.6%

**Date:** 2026-03-24
**Status:** REVERTED

---

## Hypothesis

The 24 LONG regular SL hits (-0.8% each) are the biggest drag on LONG profitability.
LONG SL = 0.6%, TP = 1.2%. Setting BE trigger = 0.6% (equal to SL distance) would mean:
any trade reaching +0.6% favorable immediately protects the trade at entry.
Trades that briefly go +0.6% then reverse to entry become -0.2% (fees only) instead of -0.8%.
No winner should be converted to loser — trades reaching TP (1.2%) still hit TP.

**Change:** `BREAK_EVEN_TRIGGER_PCT = 0.8` → `0.6`
**Expected improvement:** Reduce average LONG SL loss, improve LONG PF

---

## Results

| Metric | Baseline | Exp 013 (BE=0.6%) | Δ |
|--------|----------|-------------------|---|
| Total trades | 134 | 120 | -14 |
| Win rate | 35.07% | 26.67% | -8.4pp |
| Cumulative return | +15.41% | -2.04% | -17.45pp |
| Max drawdown | 8.29% | 8.48% | +0.19pp |
| Profit factor | 1.2784 | 0.9690 | -0.309 |
| LONG trades | 61 | 56 | -5 |
| LONG WR | 40.98% | 30.36% | -10.6pp |
| LONG PF | 1.1688 | 0.8041 | -0.365 |
| SHORT trades | 73 | 64 | -9 |
| SHORT WR | 30.14% | 23.44% | -6.7pp |
| SHORT PF | 1.3516 | 1.0965 | -0.255 |

---

## Analysis

Catastrophic failure. The 0.6% BE trigger is AT the 15m noise level. Trades that were
on their way to TP (1.2% LONG or 2.2% SHORT) routinely fluctuate through the 0.6% zone
before continuing. Triggering BE at 0.6% converted many TP winners into BE stops, collapsing
the win rate from 35% to 26.67%. Return went from +15.41% to -2.04%.

Key insight: the 0.8% BE trigger is well-calibrated for 15m BTC noise. Moves below 0.8%
from entry are within normal intracandle variance. Only after 0.8% favorable does the
trade reliably have a "real" favorable move that deserves BE protection.

---

## Decision: REVERT

`BREAK_EVEN_TRIGGER_PCT` restored to 0.8. No further exploration of lower BE triggers.

---

## Insight for Future Research

The BE trigger at 0.8% is a hard constraint — do not move it lower. Moving it higher
(>0.8%) is also risky for different reasons (analyzed separately). The 0.8% threshold
appears correctly calibrated for 15m BTC volatility structure.
