# Experiment 012 — SHORT Take Profit Sweep: 1.8% → 2.0% → 2.2% → 2.5% (+ 2.3%, 2.4%)

**Date:** 2026-03-23
**Status:** KEPT at 2.2% — new approved baseline

---

## Hypothesis

Experiment 011 showed SHORT TP=1.8% improved further over 1.5%. The same 23 winning shorts (those
that reach 1.8%) may have enough momentum to also reach 2.0%, 2.2%, or higher. Each increment adds
0.2% net per win. The goal is to find the peak TP before wins start being lost.

**Change series:**
- SHORT_TAKE_PROFIT_PCT tested at: 2.0%, 2.2%, 2.3%, 2.4%, 2.5%
- LONG TP unchanged at 1.2%
- All other parameters unchanged

---

## Full TP Sweep Results

| SHORT TP | SHORT Wins | SHORT trades | SHORT PF | Total PF | Total Return | Max DD |
|----------|-----------|--------------|----------|----------|--------------|--------|
| 1.2% (v2)| 33        | 84           | 1.0082   | 1.0513   | +2.37%       | —      |
| 1.5%     | 29        | 81           | 1.1046   | 1.1079   | +5.71%       | 10.56% |
| 1.8%     | 23        | 75           | 1.1821   | 1.1529   | +7.92%       | 10.64% |
| 2.0%     | 23        | 75           | 1.2871   | 1.2104   | +11.52%      | 9.95%  |
| **2.2%** | **23**    | **75**       |**1.3791**|**1.2665**| **+15.27%**  |**9.79%**|
| 2.3%     | 20        | 72           | 1.2828   | 1.2174   | +11.91%      | 11.31% |
| 2.4%     | 18        | 71           | 1.2021   | 1.1698   | +9.04%       | 15.09% |
| 2.5%     | 16        | 68           | 1.1449   | 1.1154   | +5.83%       | 15.09% |

**Final approved baseline metrics at SHORT TP = 2.2%:**
- Total trades: 137 (LONG: 62, SHORT: 75)
- Win rate: 35.04%
- Cumulative return: +15.27%
- Max drawdown: 9.79%
- Profit factor: 1.2665
- Expectancy: +0.110%
- Longest loss streak: 11
- CB events: 36, blocked: 208
- LONG: 62 trades, WR 40.32%, cum +2.19%, PF 1.1033
- SHORT: 75 trades, WR 30.67%, cum +12.81%, PF 1.3791

---

## Key Structural Finding

**The 23 winning shorts in this dataset share a bimodal property:**
- All 23 wins cleared 2.2% from entry (1.8% net after fees)
- None of the 52 losses ever approached these levels (they reversed within 0.6-0.8%)
- The gap between "winning move" and "losing move" is large and stable from 1.8% to 2.2%

**The cliff is between 2.2% and 2.3%**: at 2.3%, 3 wins are lost, causing all metrics to worsen.
At 2.4%+ the drawdown jumps (back to 15% range) as losing sequences grow.

This structure reflects the nature of BTC bearish momentum: when the short thesis is correct,
price tends to drop sharply (2%+ from entry); when it's wrong, reversal is quick (never approaching
the TP level). The BE mechanism (at 0.8%) handles the "right direction, small move" case, turning
those near-misses from -0.8% losses into -0.2% losses.

---

## Decision: KEEP at 2.2%

Final approved baseline:
- TAKE_PROFIT_PCT = 1.2        (LONG)
- SHORT_TAKE_PROFIT_PCT = 2.2  (SHORT)

This configuration meets the stretch target (PF > 1.20) with both sides independently profitable.

---

## Insight for Future Research

The exit architecture is now significantly improved. Future experiments should address:

1. **LONG side improvement**: LONG PF is 1.1033 — can it be improved? The LONG side takes bad
   trades during macro-bearish periods (counter-trend bounces). Signal quality improvements
   (not filter tightening) may help.

2. **Be careful with further TP extension**: The 2.2% optimum is dataset-specific to some extent.
   In a bull market or less volatile period, BTC bearish moves may be shallower and 2.2% would
   convert many wins to losses. This parameter should be re-evaluated if market regime changes.

3. **Break-even trigger asymmetry**: With SHORT TP at 2.2% and BE at 0.8%, there's a 1.4% gap
   from BE to TP. Adjusting SHORT BE to 1.0% or 1.2% could reduce the whipsaw-to-BE outcomes
   while still protecting downside. This has not been tested.

4. **LONG SL tightening**: LONG currently has SL=0.6%, TP=1.2%. With a 2:1 R:R and 40% WR,
   the LONG side is marginally profitable. Adjusting LONG SL might improve LONG consistency.
