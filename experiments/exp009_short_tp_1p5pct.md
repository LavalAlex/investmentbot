# Experiment 009 — Asymmetric SHORT Take Profit: 1.5% (LONG stays at 1.2%)

**Date:** 2026-03-23
**Status:** KEPT — new approved baseline

---

## Hypothesis

The SHORT side has PF 1.0082 with 33 wins out of 84 trades. All 33 wins exit at exactly 1.2% TP.
Many of these winning shorts occurred during strong bearish moves (BTC -7% Jan 31, -9% Feb 3-5,
-6% Feb 23-24) where price had significant momentum well beyond 1.2%. By extending SHORT TP to
1.5%, each winning short earns 1.3% net instead of 1.0% net (+30% per win). Some trades that
currently win at 1.2% might fail to reach 1.5% and become BE stops or losses, but the R:R math
should still be net positive if the majority of winners still hit the extended TP.

The LONG side (PF 1.1130) was left unchanged — asymmetric exit tuning only for SHORT.
Break-even trigger unchanged at 0.8% for both sides.

**Changes:**
- Added `SHORT_TAKE_PROFIT_PCT = 1.5` constant
- SHORT exit now uses `entry * (1 - SHORT_TAKE_PROFIT_PCT / 100)` for TP price
- LONG exit still uses `entry * (1 + TAKE_PROFIT_PCT / 100)` = 1.2%
- All other parameters unchanged

---

## Results

| Metric | v2 Baseline (both TP=1.2%) | Exp 009 (SHORT TP=1.5%) | Δ |
|--------|---------------------------|------------------------|---|
| Total trades | 145 | 142 | -3 |
| Win rate | 40.00% | 38.03% | -2.0pp |
| Cumulative return | +2.37% | **+5.71%** | **+3.34pp** |
| Max drawdown | — | 10.56% | — |
| Profit factor | 1.0513 | **1.1079** | **+0.057** |
| Expectancy | — | +0.043% | improved |
| Longest loss streak | — | 5 | — |
| CB events | 34 | 34 | 0 |
| CB blocked entries | 234 | 228 | -6 |
| LONG trades | 61 | 61 | 0 |
| LONG WR | 40.98% | 40.98% | unchanged |
| LONG PF | 1.1130 | 1.1130 | unchanged |
| LONG cum return | +2.39% | +2.39% | unchanged |
| SHORT trades | 84 | 81 | -3 |
| SHORT WR | 39.29% | 35.80% | -3.5pp |
| SHORT PF | 1.0082 | **1.1046** | **+0.096** |
| SHORT cum return | -0.02% | **+3.24%** | **+3.26pp** |

---

## Analysis

The hypothesis was correct. A significant portion of winning shorts had price momentum beyond 1.2%
— extending TP to 1.5% captured those gains. Net win per SHORT trade improved from ~1.0% to ~1.3%.

WIN RATE IMPACT: SHORT WR fell from 39.29% to 35.80% (4 wins converted to non-wins). These 4 trades
reached 1.2% TP but not 1.5%, either exiting as BE stops (-0.2%) or as full losses. Despite the WR
drop, the reward increase per win was sufficient to more than compensate.

BOTH SIDES NOW PROFITABLE: LONG PF 1.1130, SHORT PF 1.1046. The system for the first time has both
sides independently contributing positively to overall performance.

MEETS "GOOD TARGET": PF > 1.10, return meaningfully above zero (+5.71%), both sides coherent.

---

## Decision: KEEP

This is now the approved baseline. Parameters:
- TAKE_PROFIT_PCT = 1.2  (LONG only)
- SHORT_TAKE_PROFIT_PCT = 1.5  (SHORT only)
- All other parameters unchanged from v2

---

## Insight for Future Research

The SHORT side benefits from wider TP. This aligns with the nature of BTC bear moves — they tend
to be fast and steep, allowing larger price drops before mean-reversion. The question for the next
experiment: is 1.5% the optimal SHORT TP, or could it be extended further (1.8%)?

Testing 1.8% SHORT TP is a natural follow-up. Risk: further reduction in SHORT WR below a threshold
where fewer wins can support the overall system. R:R math must be checked carefully.
