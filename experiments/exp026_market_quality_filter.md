# Experiment 026 — Market Quality Filter

**Date:** 2026-04-06
**Status:** REJECT

---

## Hypothesis

The signal engine fails in choppy / recovery / oscillating market structures.
A combination of three 1h features can detect these "low quality" conditions
and block trades before they occur:

1. **ADX(14)** — trend strength; low ADX = no trend = choppy
2. **ATR(14)/price** — normalized volatility; low = flat/compressed market
3. **Range ratio** — (24h high-low range) / ATR14; low = insufficient movement

Rule: block **both** LONG and SHORT when ANY feature is below threshold.

MQ check is placed **after** the CB — CB still fires on observed losses,
preserving the CB activation sequence as much as possible.

### Configs tested (5 representative combinations, not a brute-force grid):

| Config | ADX≥ | ATR/p≥ | range≥ |
|--------|------|---------|--------|
| A: loose | 15 | 0.003 | 1.5 |
| B: med-loose | 18 | 0.003 | 2.0 |
| C: medium | 18 | 0.005 | 2.0 |
| D: med-tight | 20 | 0.005 | 2.5 |
| E: tight | 20 | 0.007 | 2.5 |

---

## Diagnostic — 1h Feature Distributions

### IS (Oct 2025 → Mar 2026):

| Feature | p10 | p25 | median | p75 | p90 |
|---------|-----|-----|--------|-----|-----|
| ADX(14) | 16.27 | 19.90 | 25.78 | 35.94 | 46.32 |
| ATR/price | 0.0034 | 0.0045 | 0.0065 | 0.0086 | 0.0105 |
| range_ratio_24 | 3.49 | 4.14 | 5.07 | 6.27 | 7.51 |

### OOS (Apr 2025 → Sep 2025):

| Feature | p10 | p25 | median | p75 | p90 |
|---------|-----|-----|--------|-----|-----|
| ADX(14) | 14.15 | 17.75 | 23.28 | 31.69 | 41.40 |
| ATR/price | 0.0031 | 0.0039 | 0.0050 | 0.0063 | 0.0077 |
| range_ratio_24 | 3.54 | 4.10 | 4.88 | 5.97 | 7.20 |

### LOW quality fraction by config:

| Config | IS LOW% | OOS LOW% | Δ (OOS-IS) |
|--------|---------|----------|------------|
| A: loose | 12.7% | 20.2% | +7.5pp |
| B: med-loose | 21.7% | 31.5% | +9.8pp |
| C: medium | 40.6% | 60.4% | +19.8pp |
| D: med-tight | 46.6% | 64.8% | +18.2pp |
| E: tight | 65.1% | 89.4% | +24.3pp |

**The three features DO discriminate IS from OOS: OOS has consistently more LOW quality time.**
However, the difference is moderate — not dramatic enough to create clean separation.
Crucially, the **range_ratio** is almost never below 2.5 in either window (IS p10=3.49,
OOS p10=3.54). The range_ratio threshold does almost no work — the ADX and ATR/price
thresholds carry the entire filtering burden.

---

## Results Summary

| Config | Window | T | WR | Cum% | DD% | PF | MQ_blocked |
|--------|--------|---|----|------|-----|-----|------------|
| A: loose | IS | 126 | 31.75% | +5.96% | 7.39% | 1.1215 | 23 |
| A: loose | OOS | 99 | 21.21% | **-24.37%** | 24.80% | 0.4591 | 36 |
| B: med-loose | IS | 120 | 28.33% | -3.81% | 13.88% | 0.9371 | 59 |
| B: med-loose | OOS | 87 | 16.09% | -26.72% | 27.59% | 0.3615 | 86 |
| C: medium | IS | 102 | 18.63% | -18.09% | 19.32% | 0.6140 | 147 |
| C: medium | OOS | 61 | 16.39% | -19.26% | 19.60% | 0.3698 | 200 |
| D: med-tight | IS | 92 | 18.48% | -17.12% | 18.23% | 0.6042 | 175 |
| D: med-tight | OOS | 60 | 16.67% | **-18.43%** | 18.77% | 0.3615 | 231 |
| E: tight | IS | 73 | 27.40% | -0.87% | 7.05% | 0.9875 | 295 |
| E: tight | OOS | 19 | 5.26% | -11.54% | 11.54% | 0.0758 | 423 |
| **BASELINE** | **IS** | **134** | **35.07%** | **+15.41%** | **8.29%** | **1.2784** | **0** |
| **BASELINE** | **OOS** | **104** | **20.19%** | **-24.39%** | **26.15%** | **0.4753** | **0** |

**No configuration improves OOS profit factor above the baseline (0.4753).**
Every config produces OOS PF ≤ 0.4753. The "best" for OOS PF is config A at 0.4591 —
still worse than the unfiltered baseline.

---

## Key Analysis

### Q1: Does OOS improve significantly?

**NO.** This is the core result.

| Config | OOS PF | Δ vs baseline | OOS cum | IS PF ratio |
|--------|--------|---------------|---------|------------|
| A | 0.4591 | -0.0162 | -24.37% | 0.88 |
| B | 0.3615 | -0.1138 | -26.72% | 0.73 |
| C | 0.3698 | -0.1055 | -19.26% | 0.48 |
| D | 0.3615 | -0.1138 | -18.43% | 0.47 |
| E | 0.0758 | -0.3995 | -11.54% | 0.77 |
| Baseline | 0.4753 | — | -24.39% | 1.00 |

Every configuration makes OOS PF worse, not better. The filter removes trades but
does not improve the quality of remaining trades.

### Q2: Does the system stop trading during bad OOS months?

Yes and no. The filter blocks significant numbers of signals in OOS:
- Config C: 200 blocked, 61 trades remain (41% of baseline)
- Config D: 231 blocked, 60 trades remain (58% of baseline)

But the remaining trades are ALSO losing:
- Config C OOS: 61 trades, WR=16.4%, PF=0.37 — still unprofitable
- Config D OOS: 60 trades, WR=16.7%, PF=0.36 — still unprofitable

The filter reduces the NUMBER of losing trades but cannot make the REMAINING ones profitable.
Every remaining month in OOS is still negative for all configs.

This is the definitive finding: **the OOS failure is uniform — there are no "HIGH quality"
sub-periods within OOS where the signal engine generates profitable signals.**

### Q3: How much trading time is removed?

| Config | IS removed | OOS removed | OOS/IS ratio |
|--------|-----------|------------|--------------|
| A | 15.4% | 26.7% | 1.73× |
| B | 33.0% | 49.7% | 1.51× |
| C | 59.0% | 76.6% | 1.30× |
| D | 65.5% | 79.4% | 1.21× |
| E | 80.2% | 95.7% | 1.19× |

The ratio of OOS-to-IS removal narrows as thresholds increase. At config E, 95.7%
of OOS time is classified as LOW quality — but this also removes 80.2% of IS time.
Removing 80% of the profitable IS trades to avoid 95% of the unprofitable OOS trades
is not a viable strategy.

### Q4: Are we over-filtering?

| Config | IS PF ratio | Assessment |
|--------|------------|-----------|
| A | 0.88 | Acceptable, but OOS unchanged |
| B | 0.73 | Borderline, OOS worse |
| C | 0.48 | Severely over-filtered IS |
| D | 0.47 | Severely over-filtered IS |
| E | 0.77 | IS still near-breakeven, but OOS at PF=0.076 |

Only config A preserves IS adequately (PF ratio=0.88). But config A barely affects OOS
(36 blocked, PF virtually unchanged at 0.4591 vs 0.4753). There is no config that
simultaneously preserves IS AND improves OOS.

---

## Critical Finding: Why the Filter Cannot Work Here

### The OOS signal is uniformly bad across ALL quality conditions

Looking at the OOS trades that survived config C (61 trades, "HIGH quality" periods only):
- WR = 16.39% (vs OOS baseline 20.19%)
- PF = 0.3698 (vs OOS baseline 0.4753)

The "HIGH quality" OOS trades are **worse** than the average OOS trade. This means the
quality filter is not separating good trades from bad trades — it's removing the slightly
less-bad trades and leaving the worse ones.

This is because the OOS failure is structural: **every signal in the OOS period is losing,
regardless of ADX/ATR/range conditions.** The signal engine's patterns (EMA20/50 + RSI + volume
confluence) produce consistently incorrect directional calls during Apr–Sep 2025.

### Feature distributions overlap too much

The key reason the filter fails: IS and OOS have nearly identical feature distributions.

- IS ADX median: 25.78 vs OOS ADX median: 23.28 — only 2.5 units lower
- IS ATR/price median: 0.0065 vs OOS ATR/price median: 0.0050 — 23% lower
- IS range_ratio median: 5.07 vs OOS range_ratio median: 4.88 — 4% lower

These differences are real but not sufficient to cleanly separate the two windows.
Any threshold that primarily blocks OOS also blocks substantial IS trading time.
There is no threshold that neatly says "OOS bad, IS good."

### The range_ratio feature is uninformative for this use case

Both IS and OOS have range_ratio consistently above 3.5 at the 10th percentile.
The 24h range is always substantially larger than the 1h ATR — this is expected:
a 24-hour high-low range almost always spans multiple ATR multiples.

The range_ratio threshold of 1.5 or 2.0 never fires in either window. The feature
adds no discrimination at the tested thresholds. A higher threshold (e.g., 4.0)
would filter more, but both windows would be equally affected.

### The "less loss" confusion

Configs C and D reduce OOS cumulative loss from -24.39% to -18-19%. This looks like
improvement, but it is not: they achieve this by simply removing 76-79% of all OOS
trades. Of course fewer trades means less cumulative loss — but the remaining trades
are equally bad (PF=0.36-0.37). This is not market quality selection; it's just
trading less in a period where trading less means losing less.

---

## Summary Table

| Question | Answer |
|----------|--------|
| Does OOS improve? | NO — no config improves OOS PF above baseline |
| Does it stop bad months? | Partially — but remaining trades still lose uniformly |
| How much removed? | Config A removes 15% IS / 27% OOS (too little). Config E removes 80% IS / 96% OOS (too much) |
| Over-filtering? | Yes above config A — IS PF collapses to 0.47-0.99 |
| Root cause addressed? | NO — the signal engine generates losses in ALL quality conditions OOS |

---

## Decision: REJECT

The market quality filter using ADX(14)/ATR/range_ratio on 1h data:
- Does not improve OOS profit factor under any tested configuration
- Damages IS performance significantly at any meaningful filter level
- Reduces cumulative OOS losses only by removing most of the trading — not by selecting better trades
- Cannot address the fundamental issue: the signal engine fails uniformly across all quality conditions in Apr–Sep 2025

**This is the third attempted structural fix for the OOS failure:**
- EXP025: SHORT regime filter (EMA200) — REVERT (wrong diagnosis)
- EXP026: Market quality filter (ADX/ATR/range) — REJECT (correct diagnosis, wrong instrument)

**Correct diagnosis confirmed: the OOS failure is a signal-engine problem, not a filter problem.**
No external filter layer can rescue a signal engine whose patterns don't generalize.

---

## Where We Are

Five consecutive structural experiments (EXP020–026, excluding EXP022 which was not run)
have all failed. The pattern is consistent:

1. **Entry gates** (EXP020–023): CB cascade kills gains
2. **CB timing adjustments** (EXP024): cascade works in both directions
3. **Regime filters** (EXP025): OOS was already in the "correct" regime
4. **Market quality filters** (EXP026): signal is uniformly bad in OOS regardless of quality

**The system does not generalize. The in-sample period (sustained bear market, high volatility)
produced a specific type of signal that the engine captures well. The OOS period (recovery
phase, different volatility) produces a different type of signal that the engine fails on.**

### What has NOT been tried

1. **Expanding the training window** — the only remaining structural fix. 12+ months
   would force the signal engine to encounter both trending and recovery market structures
   during implicit calibration.

2. **Signal engine redesign** — replace or augment the EMA20/50 confluence with patterns
   that work in non-trending markets (e.g., mean-reversion signals in ranging conditions).

3. **Accepting the constraint** — document the system as "trend-following only" and deploy
   only when a higher-level regime classifier (e.g., 1h ADX > 30 sustained for 2 weeks)
   confirms an active trend. This is not a filter; it's a deployment constraint.

Of these, option 3 is the most honest near-term path: the current system works in trending
conditions (confirmed by IS), does not work in recovery/oscillating conditions (confirmed
by OOS), and no filter layer can bridge that gap. The right question is whether the current
IN-SAMPLE trending market is likely to continue — and that is a market judgment, not a
signal-engine question.

---

## Artifacts

- `exp026_market_quality_filter.py` — experiment runner (5 configs × IS + OOS)
- `data/backtest_BTCUSDT_exp026_market_quality.json` — full results, all configs
