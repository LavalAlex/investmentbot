# Experiment 011 — Extend SHORT Take Profit to 1.8%

**Date:** 2026-03-23
**Status:** KEPT — new approved baseline

---

## Hypothesis

Experiment 009 showed SHORT TP=1.5% improved the SHORT side. Experiment 010 confirmed that LONG
does not benefit from wider TP (bounces are capped). The question is: does 1.8% SHORT TP capture
even more of the strong bearish momentum moves?

Each win at 1.8% earns 1.6% net vs 1.3% at 1.5% (+23% per win). Some of the 29 current wins
(1.5% baseline) may reverse before 1.8%, converting wins to losses, but if the majority still
reach the extended target, overall PF should improve further.

**Change:** SHORT_TAKE_PROFIT_PCT 1.5% → 1.8%
**Expected improvement:** Higher per-win reward on SHORT side, further PF improvement

---

## Results

| Metric | Exp 009 baseline (SHORT TP=1.5%) | Exp 011 (SHORT TP=1.8%) | Δ |
|--------|----------------------------------|------------------------|---|
| Total trades | 142 | 136 | -6 |
| Win rate | 38.03% | 35.29% | -2.7pp |
| Cumulative return | +5.71% | **+7.92%** | **+2.21pp** |
| Max drawdown | 10.56% | 10.64% | +0.08pp |
| Profit factor | 1.1079 | **1.1529** | **+0.045** |
| Expectancy | +0.043% | +0.061% | improved |
| Longest loss streak | 5 | 10 | +5 |
| CB events | 34 | 35 | +1 |
| CB blocked entries | 228 | 229 | +1 |
| LONG trades | 61 | 61 | 0 |
| LONG WR | 40.98% | 40.98% | unchanged |
| LONG PF | 1.1130 | 1.1130 | unchanged |
| LONG cum return | +2.39% | +2.39% | unchanged |
| SHORT trades | 81 | 75 | -6 |
| SHORT WR | 35.80% | 30.67% | -5.1pp |
| SHORT PF | 1.1046 | **1.1821** | **+0.075** |
| SHORT cum return | +3.24% | **+5.40%** | **+2.16pp** |

---

## Analysis

The hypothesis was correct again. The strong bearish moves in this dataset (BTC from 112k to 65k)
frequently have enough momentum to carry 1.8% past entry. The 6 trades that were wins at 1.5% but
failed to reach 1.8% have been absorbed into losses — this is reflected in 6 fewer total trades
(timing of TP exit changes subsequent signal opportunities due to 45-min cooldown) and 5pp lower
SHORT WR.

The LONG side remains completely unaffected — confirming the asymmetric exit architecture is correct.

NOTE: Longest loss streak increased from 5 to 10. This is a sequence metric (counting consecutive
losses in the trade log across CB pauses). With CB firing after 2 consecutive losses, the 10-trade
losing streak spans multiple CB cycles. Critically, max drawdown barely moved (+0.08pp), confirming
the CB is containing actual equity damage.

TP sensitivity pattern so far:
  SHORT TP 1.2% → PF 1.0082, cum -0.02%  (v2 baseline)
  SHORT TP 1.5% → PF 1.1046, cum +3.24%  (exp009)
  SHORT TP 1.8% → PF 1.1821, cum +5.40%  (exp011)

Every extension has improved both PF and return. Next question: does 2.0% continue the trend?

---

## Decision: KEEP

This is the new approved baseline. Parameters:
- TAKE_PROFIT_PCT = 1.2        (LONG)
- SHORT_TAKE_PROFIT_PCT = 1.8  (SHORT)
- All other parameters unchanged

---

## Insight for Future Research

The trend in SHORT TP improvement has been consistent: 1.2% → 1.5% → 1.8%, each time better.
Next experiment should test 2.0% SHORT TP. After that, if still improving, try 2.2%.

Risk to monitor: as SHORT TP extends, SHORT WR drops (39% → 36% → 31%). At some point the WR
drops below the breakeven threshold for the R:R in use. With SL=0.6% (net loss ~0.8%) and
TP=1.8% (net win 1.6%), breakeven WR = 0.8/(0.8+1.6) = 33.3%. Current 30.67% is BELOW this.

Wait — this means SHORT is profitable only because the break-even mechanism reduces average losses
below 0.8%. Many losses are -0.2% (BE stops), not -0.8% full stops. The BE mechanism is critical
to the system's profitability at this TP width.

Future: consider if 2.0% TP causes SHORT WR to drop further. If BE mechanism can't compensate,
PF will decline. Watch for this inflection point.
