# Experiment 010 — Extend LONG Take Profit to 1.5% (matching SHORT)

**Date:** 2026-03-23
**Status:** REVERTED

---

## Hypothesis

Experiment 009 showed SHORT TP=1.5% improves the SHORT side. The natural question is whether the
same applies to LONG. Bullish moves during Oct (112k→125k) and Jan (90k→98k) had momentum well
beyond 1.2%. Extending LONG TP to 1.5% should capture more of those moves.

**Change:** TAKE_PROFIT_PCT 1.2% → 1.5% (LONG side only; SHORT_TAKE_PROFIT_PCT stays at 1.5%)
**Expected improvement:** Higher per-win reward on LONG side, improved LONG PF

---

## Results

| Metric | Exp 009 baseline (SHORT TP=1.5%) | Exp 010 (both TP=1.5%) | Δ |
|--------|----------------------------------|------------------------|---|
| Total trades | 142 | 140 | -2 |
| Win rate | 38.03% | 35.00% | -3.0pp |
| Cumulative return | +5.71% | +5.15% | -0.56pp |
| Profit factor | 1.1079 | 1.0972 | -0.011 |
| Max drawdown | 10.56% | 10.75% | +0.19pp |
| CB events | 34 | 36 | +2 |
| LONG trades | 61 | 59 | -2 |
| LONG WR | 40.98% | 33.90% | -7.1pp |
| LONG PF | 1.1130 | 1.0868 | -0.026 |
| LONG cum return | +2.39% | +1.84% | -0.55pp |
| SHORT trades | 81 | 81 | 0 |
| SHORT WR | 35.80% | 35.80% | unchanged |
| SHORT PF | 1.1046 | 1.1046 | unchanged |

---

## Analysis

The hypothesis was wrong for the LONG side. Extending LONG TP to 1.5% converted 5 winning trades
into non-wins (25→20 wins). These 5 trades reached 1.2% TP but the market reversed before 1.5%.

Why LONG fails with 1.5% TP but SHORT succeeds:
- The 180d window is a macro bear market (BTC fell from 112k to 65k)
- LONG trades are counter-trend bounces or short-lived bullish stretches that often fade
- SHORT trades align with the dominant macro direction — bear moves have more runway
- In the macro bearish context, LONG moves tend to be capped; extending TP pushes beyond the
  available headroom and converts wins to losses

The 2 extra CB events confirm that the additional LONG losses created more consecutive-loss streaks,
further disrupting trade sequencing.

---

## Decision: REVERT

Reverted TAKE_PROFIT_PCT back to 1.2%. SHORT_TAKE_PROFIT_PCT stays at 1.5% (from Exp 009).

---

## Insight for Future Research

The asymmetric TP configuration (LONG=1.2%, SHORT=1.5%) is confirmed as optimal in this regime:
- LONG = tighter TP captures bounces before they fade
- SHORT = wider TP captures more of the macro bearish momentum

Next experiments should explore: can we improve LONG quality without changing TP? Can we extend
SHORT TP further (1.8%)? Does the break-even trigger need adjustment now that SHORT TP is wider?
