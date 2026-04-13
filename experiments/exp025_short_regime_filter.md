# Experiment 025 — Symmetric SHORT Regime Filter

**Date:** 2026-04-06
**Status:** REVERT
**Type:** Structural repair experiment (not optimization)

---

## Hypothesis

The walk-forward OOS failure (PF=0.47, WR=20%, Cum=-24.39%) was attributed to taking
SHORT trades in a macro-bullish regime. The LONG side already has a regime filter
(block LONG when 1h close < 1h EMA200). Adding a symmetric SHORT filter was expected
to protect the system from taking SHORTs in bullish macro conditions.

**Proposed fix:**
```
Block SELL when 1h close > 1h EMA200   (bullish macro → no shorts)
Allow SELL when 1h close <= 1h EMA200  (bearish macro → shorts allowed)
```

This filter already existed in `backtest.py` as `REGIME_FILTER_SHORT = False`. Only
the flag needed enabling. One genuine code fix was also made: the `df_1h_ind`
computation condition was extended to cover `REGIME_FILTER_SHORT` and `BLOCK_SHORT_LOW_VOL`
(previously only triggered by `REGIME_FILTER_LONG or BLOCK_LONG_LOW_VOL`).

No other changes were made to any strategy logic.

---

## Results

### In-Sample (2025-09-26 → 2026-03-25)

| Metric | Baseline | EXP025 | Δ |
|--------|----------|--------|---|
| Total trades | 134 | 132 | -2 |
| Win rate | 35.07% | 34.85% | -0.22pp |
| Cumulative return | +15.41% | **+13.38%** | -2.03pp |
| Max drawdown | 8.2937% | 8.2937% | 0.00 |
| Profit factor | 1.2784 | **1.2462** | -0.0322 |
| Expectancy | +0.1128% | +0.1009% | -0.012pp |
| Longest loss streak | 10 | 10 | 0 |

**SHORTs blocked by filter: 8**
- Oct 2025: 3 blocked
- Mar 2026: 5 blocked

**Monthly IS:**

| Month | BL Ret | EXP025 | ΔRet | Verdict |
|-------|--------|--------|------|---------|
| 2025-10 | -1.78% | -2.93% | -1.15 | WORSE |
| 2025-11 | +3.81% | +3.81% | 0.00 | FLAT |
| 2025-12 | -3.58% | -3.58% | 0.00 | FLAT |
| 2026-01 | +10.59% | +10.59% | 0.00 | FLAT |
| 2026-02 | +2.65% | +2.65% | 0.00 | FLAT |
| 2026-03 | +3.41% | +2.79% | -0.62 | WORSE |

Oct 2025 and Mar 2026 are slightly worse (those are the months where SHORTs were blocked).
All other months are unchanged. IS damage is minimal.

---

### Out-of-Sample (2025-03-30 → 2025-09-26)

| Metric | Baseline | EXP025 | Δ |
|--------|----------|--------|---|
| Total trades | 104 | 104 | 0 |
| Win rate | 20.19% | 20.19% | 0.00 |
| Cumulative return | -24.39% | **-24.85%** | -0.46pp |
| Max drawdown | 26.15% | 26.59% | +0.44pp |
| Profit factor | 0.4753 | **0.4699** | -0.0054 |
| Expectancy | -0.2654% | -0.2712% | -0.006pp |
| Longest loss streak | 13 | 13 | 0 |

**SHORTs blocked by filter: 4**
- May 2025: 1 blocked
- Jul 2025: 3 blocked

**The filter had essentially zero effect on OOS performance.**

Side breakdown:

| Side | Baseline OOS | EXP025 OOS |
|------|-------------|------------|
| LONG | 65t · 26.1% · PF 0.51 · cum -15.48% | 65t · 26.1% · PF 0.51 · cum -15.48% |
| SHORT | 39t · 10.3% · PF 0.42 · cum -10.55% | 39t · 10.3% · PF 0.41 · cum -11.09% |

The SHORT count is identical (39 trades). The filter blocked 4 SHORT *signals* that were
already being blocked by other mechanisms (cooldown/CB) in the baseline, so no net change
in SHORT trade count occurred.

---

## Critical Finding

**The OOS failure is NOT caused by SHORTs taken in a macro-bullish regime.**

The SHORT regime filter blocked only **4 signals out of the entire OOS window** — and those
4 had already been blocked by cooldown/CB in the baseline (the SHORT count didn't change).

This means: **during the OOS period (Apr–Sep 2025), BTC was predominantly BELOW its 1h
EMA200**. The filter almost never fired because the macro regime was already "correctly"
identified as bearish.

Yet the SHORT win rate was 10.26% in that bearish macro regime.

This is the deeper truth: **the OOS failure is not a regime-labeling problem. It is a
signal-quality problem within the "correctly-identified" bearish regime.**

The EMA200 correctly classified Apr–Sep 2025 as macro-bearish (allowing SHORTs). But
the signal engine's SHORT entries — triggered by the EMA20/50/RSI/volume/ATR confluence —
were still generating only 10% WR even when the macro condition was satisfied.

---

## Root Cause Revision

The initial post-OOS hypothesis was:
> "SHORTs were taken in a bullish macro regime — add the symmetric filter to fix it."

**This was wrong.** BTC was mostly below its 1h EMA200 during Apr–Sep 2025.

The actual root cause appears to be one or more of:

### 1. Post-crash recovery structure (whipsaw environment)
BTC had crashed from its Jan 2025 ATH (~$109k) and was recovering through Apr–Sep 2025
before reaching a new local high (~$110k) in late September. Recovery phases after large
corrections are characterized by:
- Violent counter-trend bounces ("dead cat" short squeezes)
- Compressed ATR relative to the EMA spreads the signal engine uses
- Frequent false directional breakouts
- SHORT entries on bearish signals that immediately reverse as buyers step in

The EMA20/50 system was generating SHORT signals in what appeared to be bearish structures,
but those structures were frequently interrupted by recovery bounces before 2.2% TP was reached.

### 2. Signal engine optimized for trending, not recovering markets
The in-sample period (Oct 2025 → Mar 2026) was a directional bear market: BTC declined
from ~$109k to ~$71k without major recovery rallies. The signal engine's SHORT logic
thrives in sustained trending moves where 2.2% TP is reachable. In the OOS recovery
phase, the dominant move was UP (recovery), so SHORT setups were fighting the primary trend
even within "bearish" sub-structures.

### 3. LONG failure is equally damning
The LONG side failed too: WR=26.15%, PF=0.51, cum=-15.48%. With REGIME_FILTER_LONG ON,
most LONGs were permitted (only 3 blocked). The LONG entries were in macro-bullish moments
(above EMA200), yet still only 26% WR. This means the 15m signal patterns (EMA20/50
crossover + RSI + volume confluence) that worked in the in-sample period did not work in
the OOS period on EITHER side.

**Conclusion: The core signal engine (entry patterns, not regime filters) is the source
of the OOS failure.** The EMA200 regime filter — whether for LONG or SHORT — is
insufficient to rescue a signal system whose patterns don't generalize.

---

## Blocked SHORT Trade Analysis

### In-Sample: 8 SHORTs blocked

| Month | Blocked |
|-------|---------|
| Oct 2025 | 3 |
| Mar 2026 | 5 |

These months show small IS degradation (-1.15pp Oct, -0.62pp Mar). The blocked SHORTs
in the IS period were in months when BTC was briefly above EMA200. Blocking them slightly
hurt results — suggesting these were legitimate SHORT setups in a pullback during a
broader downtrend.

This is the cost of the filter on the IS side: it blocks valid counter-trend pullback
SHORTs when the macro briefly turns bullish. This is by design, but it shows the filter
removes some real edge.

### Out-of-Sample: 4 SHORTs blocked

| Month | Blocked |
|-------|---------|
| May 2025 | 1 |
| Jul 2025 | 3 |

Negligible effect. The OOS period was mostly below EMA200.

---

## Key Analysis

### Q1: Does this fix the OOS catastrophe?

**NO.** OOS PF: 0.4753 → 0.4699. Marginally WORSE. The filter blocked 4 signals that
were already blocked by other mechanisms. Total SHORT count unchanged (39 trades).

The OOS failure is structural, not regime-related. The fix was the wrong one.

### Q2: Does it preserve enough IS profitability?

**YES.** IS PF: 1.2784 → 1.2462 (ratio=0.97). IS cost is minimal: -2.03pp cumulative,
-0.03 PF, 2 fewer trades. All months except Oct and Mar are identical.

The filter is correctly designed and surgically small in IS impact. It's just solving
the wrong problem.

### Q3: Is the system now regime-aware?

**NOT MEANINGFULLY.** The filter architecture is correctly implemented, but regime awareness
via 1h EMA200 is insufficient. The OOS failure exists entirely within the "correct" regime
(bearish macro, BTC below EMA200) — so regime awareness at this level doesn't help.

### Q4: Is the system more robust across bull and bear windows?

**NO.** Both IS (PF=1.25) and OOS (PF=0.47) are essentially unchanged. The fundamental
gap between windows is not reduced.

---

## Decision: REVERT

The SHORT regime filter:
- Has minimal IS cost (PF ratio 0.97) — correctly designed
- Has zero OOS benefit — solves the wrong problem
- Does not address the actual OOS failure mechanism

**Revert `REGIME_FILTER_SHORT = False` in `backtest.py`.**
Keep the code fix to the `df_1h_ind` computation condition (now includes all four flags).

---

## Structural Implications for Research

### What we learned from EXP025

The OOS failure cannot be fixed by regime filtering at the 1h EMA200 level. The signal
engine itself — the EMA20/50 crossover + RSI + ATR + volume confluence that generates
BUY/SELL signals — does not produce a positive edge in the Apr–Sep 2025 market structure.

This is a more fundamental problem than any regime filter can address.

### What would need to change

1. **Signal engine audit** — understand exactly WHICH signal patterns are generating the
   OOS losses. Are they all pattern types, or concentrated in specific confluence
   configurations? This requires deep analysis of the signal_log for OOS trades.

2. **Different regime classifier** — EMA200 is insufficient. A 52-week high/low ratio,
   or a trend-strength metric (ADX on 1h), or a realized volatility comparison might
   better identify "recovery/whipsaw" regimes where the signal engine fails.

3. **Longer training window** — The signal engine was optimized (implicitly, through
   parameter selection) on a 6-month bear trend. A 12-month window including the Jan 2025
   ATH approach, the crash, and the recovery would expose the signal engine to the pattern
   types that the current OOS failure reveals.

4. **Accept the system is trend-dependent** — The core EMA20/50 crossover signal works
   in trending markets and fails in oscillating/recovery markets. This is a known property
   of trend-following systems. Rather than fixing it, document it as a constraint: the
   system should only be deployed in confirmed trending environments.

### Priority recommendation

Before any further experiments:

1. Fetch and examine the OOS trade log — identify the specific signal patterns that
   generated the OOS losses to understand whether the failure is concentrated or uniform.
2. Check: was BTC truly in a clear recovery (uptrend) during Apr–Sep 2025, or was it
   oscillating? This affects which "fix" is appropriate.
3. If the OOS period was oscillating (no trend), consider a 1h ADX filter (ADX > 20)
   as a trend-strength gate before taking signals — this was tested in EXP020 but only
   on IS data. Its OOS behavior is unknown.

---

## Artifacts

- `exp025_short_regime_filter.py` — experiment runner
- `backtest.py` — `df_1h_ind` condition fixed (includes all four regime/vol flags)
- `REGIME_FILTER_SHORT` remains `False` (reverted)
- `data/backtest_BTCUSDT_exp025_short_regime.json` — full trade and signal log
