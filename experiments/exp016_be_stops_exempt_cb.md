# Experiment 016 — CB Counter: BE Stops Exempt (Only Full SL Losses Count)

**Date:** 2026-03-24
**Status:** REVERTED

---

## Hypothesis

Analysis of the 35 CB events showed:
- SL+SL (both full losses): 13 events (37%) — genuinely protective
- BE+BE (both near-zero): 3 events (9%) — possibly overcautious
- MIXED (one of each): 19 events (54%) — questionable

BE stops (-0.2%) are near-zero outcomes representing "free" trades that only cost fees.
Two consecutive BE stops should not indicate a broken regime the same way two SL losses do.

Proposed change: treat BE stops (pct_return > -0.3%) as neutral — they reset the
consecutive_losses counter like wins rather than incrementing it.

**Change:** CB counter: `pct_return <= 0` → `pct_return < -0.3` for increment; else reset
**Expected improvement:** ~22 fewer CB events (MIXED + BE+BE), more trading opportunities

---

## Results

| Metric | Baseline | Exp 016 (BE=exempt) | Δ |
|--------|----------|---------------------|---|
| Total trades | 134 | 151 | +17 |
| Win rate | 35.07% | 31.13% | -3.9pp |
| Cumulative return | +15.41% | +0.19% | -15.22pp |
| Max drawdown | 8.29% | 14.63% | +6.34pp |
| Profit factor | 1.2784 | 1.0149 | -0.263 |
| CB events | 35 | 24 | -11 |
| LONG PF | 1.1688 | 0.9731 | -0.196 |
| SHORT PF | 1.3516 | 1.0431 | -0.309 |

---

## Analysis

The 17 additional trades that now get through are heavily net-negative. This confirms
that the CB is not wrong when it triggers after a MIXED or BE+BE sequence — the
FOLLOWING trades (those that were blocked) are also bad regardless of how the
previous 2 losses were classified.

Why: a BE stop (near-zero loss) followed by an SL loss, or two BE stops in a row,
does indicate poor market conditions — the trade setup fires repeatedly but the
market doesn't follow through. The regime is genuinely choppy, not just unlucky.
The CB correctly identifies this pattern.

The same fundamental pattern as exp008 and exp014: reducing CB effectiveness
(by any mechanism) allows trades during bad regimes.

---

## Decision: REVERT

CB loss tracking restored to `pct_return <= 0`. All losses (including BE stops) count.

---

## Insight for Future Research

The CB circuit is robust to its trigger mechanism changes. Every attempt to relax
it has failed. The CB correctly identifies bad market regimes regardless of whether
the triggering losses were full SL or BE stops. Do not attempt further CB relaxation.

The fundamental conclusion: the 210 CB-blocked entries across 180 days are ALL net
negative. The circuit breaker is correctly identifying and blocking unprofitable periods.
