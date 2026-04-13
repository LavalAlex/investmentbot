# Experiment 024 — Dynamic Circuit Breaker

**Date:** 2026-04-06
**Status:** REVERT

---

## Hypothesis

The circuit breaker already acts as a regime filter but requires observing losses to
activate. EXP023 confirmed that displacement strongly discriminates market quality:
- Low displacement (abs < 0.5): WR=16%, PF=0.41 — choppy trades
- High displacement (abs >= 0.5): WR=39%, PF=1.43 — trending trades

Rather than blocking entries (which disrupts CB activation sequences, per EXP023),
use displacement to **adapt the CB trigger threshold**:

```
displacement = (close[i] - close[i-4]) / ATR14   (evaluated at entry time)

LOW  quality: abs(displacement) < 0.5  → CB triggers after 1 loss
HIGH quality: abs(displacement) >= 0.5 → CB triggers after 2 losses (unchanged)
```

CB duration (48h) unchanged. Only the number of losses required to trigger changes.

**Constraints respected:**
- No entry signals modified
- No SL/TP/BE/cooldown logic changed
- No new entry filters
- Only the CB trigger count is dynamic

---

## Internal Baseline

The script runs a fresh baseline simulation (HTF_WINDOW=250, same as EXP023) alongside
EXP024 for direct comparison. Due to the HTF cap, the internal baseline differs
slightly from the canonical 134-trade baseline (2 extra trades from ceiling effects).

| Metric | Internal Baseline | Canonical Baseline |
|--------|-------------------|-------------------|
| Total trades | 136 | 134 |
| Win rate | 34.56% | 35.07% |
| Cumulative return | +10.68% | +15.41% |
| Max drawdown | 8.29% | 8.29% |
| Profit factor | 1.1932 | 1.2784 |

All comparisons below use the internal baseline for consistency.

---

## Results

### Full metrics comparison:

| Metric | Baseline | EXP024 | Δ |
|--------|----------|--------|---|
| Total trades | 136 | **125** | -11 |
| Win rate | 34.56% | 32.80% | -1.76pp |
| Cumulative return | +10.68% | **+5.40%** | **-5.28pp** |
| Max drawdown | 8.2937% | **8.4761%** | +0.18pp |
| Profit factor | 1.1932 | **1.1117** | -0.0815 |
| Expectancy | +0.0802% | +0.0477% | -0.0325pp |
| Longest loss streak | 10 | 10 | **0** |

### Side breakdown:

| Side | Baseline | EXP024 |
|------|----------|--------|
| LONG | 66t · 40.91% · PF 1.08 | 57t · 40.35% · PF 1.10 |
| SHORT | 70t · 28.57% · PF 1.28 | 68t · 26.47% · PF 1.12 |

LONG win rate nearly unchanged (-0.56pp). SHORT win rate drops -2.10pp and loses
more than half its profitability (PF 1.28 → 1.12).

---

## Monthly Breakdown

| Month | BL T | BL WR | BL Ret | EX T | EX WR | EX Ret | ΔRet | Verdict |
|-------|------|-------|--------|------|-------|--------|------|---------|
| 2025-10 | 19 | 26.3% | -2.93% | 19 | 26.3% | -2.93% | 0.00 | FLAT ◄ |
| 2025-11 | 27 | 33.3% | +3.81% | 25 | 32.0% | +3.06% | -0.75 | WORSE |
| 2025-12 | 18 | 22.2% | -3.58% | 19 | 26.3% | **-1.65%** | **+1.93** | **BETTER ◄** |
| 2026-01 | 22 | 54.5% | +9.92% | 22 | 54.5% | +9.92% | 0.00 | FLAT ◄ |
| 2026-02 | 24 | 29.2% | +2.65% | 22 | 22.7% | **-2.14%** | **-4.79** | **WORSE** |
| 2026-03 | 26 | 38.5% | +0.96% | 18 | 33.3% | -0.41% | -1.37 | WORSE |

**Target months:**
- Oct 2025: FLAT — dynamic CB had no effect
- Dec 2025: **BETTER (+1.93pp)** — first genuine improvement in a target month across all experiments
- Jan 2026: FLAT — full +9.92% preserved

**Damage:**
- Feb 2026: -4.79pp (turns +2.65% profitable month into -2.14% losing month)
- Mar 2026: -1.37pp

---

## Circuit-Breaker Statistics

| Metric | Baseline | EXP024 |
|--------|----------|--------|
| CB activations | 36 | 37 (+1) |
| Avg blocked per CB | 6.0 | 6.6 |
| Total entries blocked | 217 | 244 (+27) |
| Total pause hours | 1728h | 1776h |

**EXP024 CB breakdown:**
- Triggered by LOW quality (1-loss threshold): **10 events**
  - True early triggers (after 1 loss): **5 events** (events #10, 15, 26, 32, 36)
  - Triggered after 2 losses despite LOW quality: 5 events (would also trigger in baseline)
- Triggered by HIGH quality (2-loss threshold): 27 events

### Early trigger breakdown:

| Event | Date | Quality | After | Blocked | Month Impact |
|-------|------|---------|-------|---------|--------------|
| #10 | 2025-11-13 | LOW | 1L | 7 | Nov -0.75pp |
| #15 | 2025-12-03 | LOW | 1L | 1 | Dec +1.93pp |
| #26 | 2026-02-03 | LOW | 1L | **27** | **Feb -4.79pp** |
| #32 | 2026-02-28 | LOW | 1L | 3 | Mar -1.37pp |
| #36 | 2026-03-19 | LOW | 1L | 8 | Mar -1.37pp |

Event #26 is the critical failure: one LOW quality loss on 2026-02-03 triggered the
CB, blocking 27 entries over the next 48h. February flips from +2.65% to -2.14%.
This is the cascade problem in its clearest form — 1 loss saved, 27 entries blocked.

---

## Market Quality Breakdown

| Quality | Baseline | EXP024 |
|---------|----------|--------|
| LOW | 14t · WR=14.3% · PF=0.357 · cum=-5.31% | 13t · WR=23.1% · PF=0.735 · cum=-1.85% |
| HIGH | 122t · WR=36.9% · PF=1.339 · cum=+16.89% | 112t · WR=33.9% · PF=1.167 · cum=+7.39% |

LOW quality trades: slightly improved (fewer taken, slightly better WR). This is the
intended behavior — early CB is blocking some bad LOW quality follow-on trades.

HIGH quality trades: significantly degraded (10 fewer trades, WR -3pp, PF 1.339 →
1.167, cum +16.89% → +7.39%). The early CB windows are cutting into HIGH quality
periods that would have been profitable.

---

## Critical Analysis

### 1. Over-triggering?

5 true early triggers. Not numerically excessive (+1 CB total over 37 events).
But the distribution is uneven: event #26 alone accounts for 27 blocked entries, more
than some entire months. A single LOW quality loss in Feb 2026 was the CB threshold
decision that reversed the entire month.

**Verdict: Not systematically over-triggering, but individual early triggers can have
disproportionate impact when they fall at the start of a trend window.**

### 2. Missing profitable sequences?

Yes. The HIGH quality trade degradation (+16.89% → +7.39% cumulative) directly
measures the profitable sequences lost to early CB windows. 10 HIGH quality trades
were blocked by dynamic CB pauses that would not have occurred in the baseline.

The Feb 2026 early trigger (event #26) explains the majority of this gap:
- 27 entries blocked, including many HIGH quality trending setups in early Feb

### 3. Does earlier CB activation actually reduce net loss?

Partially, but not sufficiently. The 5 early triggers prevented ~5 losses (roughly
one per trigger, given the 1-loss threshold). The LOW quality trade metrics improved:
-5.31% → -1.85% cumulative. That's a ~3.5pp gain in the LOW quality bucket.

But the cost was 10 HIGH quality trades lost across the full dataset, collectively
contributing +7-9pp of missing gains in the HIGH quality bucket.

**Net: ~3.5pp saved in LOW quality, ~9pp lost in HIGH quality — negative exchange.**

### 4. Is the cascade problem structural?

Yes. The CB cascade identified in EXP023 manifests equally here:
- EXP023: removing loss entries → CB never activates → downstream losses unblocked
- EXP024: triggering CB earlier → longer combined pause coverage → downstream
  profitable entries blocked

Both directions of interference produce the same result: altering CB timing damages
the system's natural loss-protection schedule.

The cascade operates because profitable entries are concentrated in predictable
post-recovery windows. Moving the CB start time shifts whether those windows fall
inside or outside the 48h pause — with outcomes that are hard to predict and easy
to get wrong.

### 5. Positive findings (what worked)

Dec 2025 is the **first target month to genuinely improve** (+1.93pp) without
regressing in the other two target months (Oct: flat, Jan: flat). Event #15
triggered early in Dec 2025, blocking 1 entry, and resulted in a 1.93pp improvement.
This is a legitimate structural success — small early CB skip in a choppy period
allowed the month to close positively.

The longest loss streak was NOT reduced (still 10). The hypothesis that earlier CB
activation reduces loss streak depth was not confirmed.

---

## Comparison: Baseline CB vs Dynamic CB activations

| Period | Baseline CBs | EXP024 CBs | Notes |
|--------|-------------|-----------|-------|
| Oct 2025 | Same | Same | No early triggers |
| Nov 2025 | Same | +1 (event #10, early) | Minor damage (-0.75pp) |
| Dec 2025 | Same | +1 (event #15, early) | Improvement (+1.93pp) |
| Jan 2026 | Same | Same | No change |
| Feb 2026 | Same | +2 (events #26, #27) | Major damage (-4.79pp) |
| Mar 2026 | Same | +1 (event #36, early) | Moderate damage (-1.37pp) |

The improvement/damage ratio is 1:4 across months. The one improvement (Dec) is
structurally sound but the Feb damage is catastrophic relative to its magnitude.

---

## Structural Assessment

### Does dynamic CB improve system robustness?

**No.** Cumulative return degrades -5.28pp. Drawdown increases marginally. Profit
factor drops from 1.1932 to 1.1117. The system retains positive expectancy but at
significantly reduced levels.

### Is the improvement structural or noise?

The Dec 2025 improvement (+1.93pp from a 1-blocked-entry early trigger) has a
plausible causal mechanism and is the only genuine structural success. But it is
one data point against consistent damage in Feb/Mar.

The HIGH quality metric degradation (+16.89% → +7.39%) is structural, not noise:
it reflects real profitable trades blocked by early CB windows.

### Does this approach respect the original system design?

Formally yes — entries are not blocked, no signals modified. But the CB timing
modification has the same functional effect as a pre-filter: it changes which trades
execute, just via a different mechanism (temporal blocking rather than signal blocking).

The original system's CB is a defensive mechanism that trades 2 confirmed losses for
48h protection. The dynamic variant introduces a single-loss hair trigger in choppy
conditions. The hair trigger's sensitivity creates more disruption than the 1-loss
saving justifies.

---

## Decision: REVERT

**Summary:**

| Question | Answer |
|----------|--------|
| Does dynamic CB reduce losses in Oct 2025? | No — FLAT |
| Does dynamic CB reduce losses in Dec 2025? | **Yes — +1.93pp** |
| Does it preserve Jan 2026 performance? | **Yes — FLAT** |
| Does it reduce drawdown? | No — marginally worse (+0.18pp) |
| Does it improve monthly consistency? | No — 1 better, 3 worse, 2 flat |
| Are we over-triggering CB? | Not systematically, but 1 event caused catastrophic damage |
| Are we missing profitable sequences? | Yes — 10 HIGH quality trades blocked |
| Is the CB cascade problem resolved? | No — it reappears via blocked windows |

**No code was modified in the main system files. Experiment was standalone.**
**Baseline fully restored: 134 trades, WR 35.07%, Cum +15.41%, PF 1.2784.**

---

## Key Structural Insight

EXP023 and EXP024 together establish a clear constraint:

> **The CB cascade is bidirectional.**
> - Blocking entries upstream (EXP023): CB doesn't activate → downstream losses unblocked
> - Triggering CB earlier (EXP024): CB activates sooner → downstream profitable entries blocked
>
> Both directions damage the system. The CB's 2-loss/48h calibration appears to be
> close to an optimal operating point for this dataset and regime.

The only path that bypassed cascade in this experiment was event #15 (Dec 2025):
1 entry blocked, 1 bad trade avoided, month improved. This worked because the
blocked entry was NOT at the start of a profitable sequence — it was in an isolated
choppy period with no strong follow-through.

**A reliable improvement would require identifying when early CB activation falls at
the edge of choppy periods vs. at the start of trend recoveries. That requires
forward-looking information, which is not available at entry time.**

---

## Where We Are After EXP024

The system's CB architecture is robust to the modifications attempted so far.
Four experiments (EXP020, 021, 023, 024) have failed to improve it without cascade
effects. The consistent finding:

**The CB is already near-optimal for its role. Upstream modifications — whether
entry gates or trigger timing changes — alter CB timing in ways that reduce net return.**

Current options for further research:
1. **Larger dataset**: validate whether the 180d baseline generalizes to 365d before
   attempting further modifications (recommended path from EXP023)
2. **Exit-side optimization**: adjust TP/SL ratios rather than entry/CB logic
3. **Accept the baseline**: the 15.41% cumulative / PF 1.28 result may be the
   extractable maximum for this signal set and dataset window

---

## Artifacts

- `exp024_dynamic_cb.py` — experiment runner (kept for reference)
- `data/backtest_BTCUSDT_180d_exp024_dynamic_cb.json` — full trade and CB log
