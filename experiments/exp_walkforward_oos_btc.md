# Walk-Forward Out-of-Sample Validation — BTC/USDT

**Date:** 2026-04-06
**Type:** Validation (no parameter changes)
**Verdict: NOT VALIDATED**

---

## Setup

### Out-of-sample window
```
15m signal data : 2025-03-30 → 2025-09-26  (180d)
1h  HTF data    : 2025-03-10 → 2025-09-26  (200d, for EMA200 warmup)
```

### In-sample window (the tuned baseline)
```
15m signal data : 2025-09-26 → 2026-03-25  (180d)
```

### Baseline parameters used (UNCHANGED)
```
SL=0.6%  TP=1.2% (LONG)  TP=2.2% (SHORT)
BE trigger=+0.8%
CB=2 consecutive losses → 48h pause
Cooldown=45min post-trade
Regime filter LONG: ON (block LONG when 1h close < 1h EMA200)
Regime filter SHORT: OFF
Fee=0.2% round-trip
```

No modifications were made to any strategy file. `backtest.py` was called directly
via `backtest_oos.py` as a standalone runner pointing at the OOS datasets.

---

## Confirmed Date Ranges

The in-sample 15m dataset starts at exactly `2025-09-26T01:00:00+00:00` (BTC ~$109,472).
The OOS 15m dataset ends at `2025-09-26T00:59:59+00:00` — perfectly contiguous.

There is no data overlap. The OOS window is the 180d block immediately preceding the
in-sample tuning period.

---

## OOS Results

| Metric | OOS Result |
|--------|-----------|
| Period | 2025-03-30 → 2025-09-26 |
| Total trades | 104 |
| Win rate | **20.19%** |
| Cumulative return | **-24.39%** |
| Max drawdown | **26.15%** |
| Profit factor | **0.4753** |
| Expectancy | -0.2654% |
| Longest loss streak | 13 |
| CB activations | 37 |
| CB blocked entries | 233 |
| Regime blocked (LONG) | 3 |

### Side breakdown:

| Side | OOS |
|------|-----|
| LONG | 65t · WR=26.15% · PF=0.5060 · cum=-15.48% |
| SHORT | 39t · WR=10.26% · PF=0.4211 · cum=-10.55% |

### Monthly breakdown:

| Month | Trades | WR | Return |
|-------|--------|----|--------|
| 2025-03 | 2 | 0.0% | -0.40% |
| 2025-04 | 21 | 19.0% | -6.65% |
| 2025-05 | 26 | 23.1% | -5.91% |
| 2025-06 | 12 | 16.7% | -4.72% |
| 2025-07 | 18 | 33.3% | -2.43% |
| 2025-08 | 14 | 14.3% | -3.58% |
| 2025-09 | 11 | 9.1% | -3.57% |

**Every single month is negative. No month has positive return.**

---

## Full Comparison: In-Sample vs Out-of-Sample

| Metric | In-Sample | OOS | Δ |
|--------|-----------|-----|---|
| Total trades | 134 | 104 | -30 |
| Win rate | 35.07% | **20.19%** | -14.88pp |
| Cumulative return | +15.41% | **-24.39%** | -39.80pp |
| Max drawdown | 8.29% | **26.15%** | +17.86pp |
| Profit factor | 1.2784 | **0.4753** | -0.8031 |
| Expectancy | +0.113% | **-0.265%** | -0.378pp |
| Longest loss streak | 10 | **13** | +3 |

### Side comparison:

| | In-Sample | OOS | Δ WR | Δ PF |
|--|-----------|-----|------|------|
| LONG | 61t · 41.0% · PF 1.17 · +3.52% | 65t · 26.2% · PF 0.51 · -15.48% | -14.8pp | -0.66 |
| SHORT | 73t · 30.1% · PF 1.35 · +11.49% | 39t · 10.3% · PF 0.42 · -10.55% | -19.8pp | -0.93 |

Both sides fail completely. Neither LONG nor SHORT generates a positive edge OOS.

---

## Key Analysis

### Q1: Does the strategy still have a positive edge out-of-sample?

**NO.**

PF=0.4753. Cumulative return=-24.39%. WR=20.19%. Every single month is negative.
This is not mild degradation — this is total edge destruction OOS.

### Q2: Is performance concentrated in one month?

Irrelevant in this case — every month loses. The worst month is April 2025 (-6.65%).
July 2025 is the least bad (-2.43%, WR=33.3%) but still negative.

There is no single month carrying the in-sample result. All months are uniformly bad.
This means the OOS failure is a structural property of the entire 6-month window,
not an artifact of one bad month.

### Q3: Is the SHORT side still the main driver?

**No — and this is the most important structural clue.**

In-sample, SHORT drove 73 trades at PF=1.35, contributing +11.49% of the +15.41% total.
Out-of-sample, only 39 SHORT trades (53% drop) at WR=10.26%, PF=0.42, contributing -10.55%.

The SHORT count dropped almost in half (73 → 39). The regime filter for LONG blocked
only 3 entries. This means:
- The BTC market structure in Apr-Sep 2025 produced far fewer confirmed SHORT setups
- The short setups that did trigger had catastrophic WR (10.26% vs 30.14% in-sample)
- The 2.2% SHORT TP was almost never reached — price didn't fall 2.2% from SHORT entries

This is the primary failure mode: the OOS period was NOT a regime where the SHORT
signal + 2.2% TP structure could win.

### Q4: Does drawdown remain acceptable?

**NO.** OOS DD=26.15% vs in-sample 8.29%.

The drawdown is more than 3× worse out-of-sample. This is beyond the "acceptable
degradation" range for a deployed strategy. A 26% drawdown on a pure signal system
(no leverage) would require recovering from deep negative to reach break-even.

### Q5: Does this look like a generalizable system or a dataset-specific one?

**Dataset-specific.**

- PF ratio (OOS/IS): 0.37 — well below the 0.70 threshold for "reasonable degradation"
- The WR drops 14.88pp (not a mild statistical fluctuation — this is structural)
- The SHORT side nearly disappears (73t → 39t) AND becomes catastrophically unprofitable
- Zero profitable months across 7 months of OOS data

All indicators point to a system that was tuned to a specific market regime:
the high-volatility, large-swing period of Oct 2025 → Mar 2026.

---

## Root Cause Analysis

### What was different about the in-sample vs OOS regimes?

**In-sample (Oct 2025 → Mar 2026):**
- BTC near all-time highs ($109k) declining toward $71k over 6 months
- Large, sustained directional moves (HIGH displacement → SHORT setups with strong follow-through)
- High volatility enabling 2.2% SHORT TP to be reached consistently
- Monthly WR ranged from 22.2% (weak) to 54.5% (strong) — varied but with clear trending months

**OOS (Apr 2025 → Sep 2025):**
- BTC recovering from post-ATH correction, approaching $110k by late September
- Likely more oscillating, range-bound behavior with unclear directionality
- Lower/different volatility profile — 2.2% SHORT TP rarely reached (WR=10.26%)
- Monthly WR ranged from 0.0% to 33.3% — uniformly terrible
- ONLY 39 SHORT setups triggered vs 73 in-sample (fewer confirmed bearish structures)

**The 1h EMA200 regime filter (REGIME_FILTER_LONG=True) did not save the system.**
Only 3 LONG entries were regime-blocked OOS. This means BTC was predominantly above
its 1h EMA200 during Apr-Sep 2025 — i.e., macro-bullish — which allowed LONG entries
through but those LONGs still failed at 26.2% WR.

The SHORT side's catastrophic failure is the core driver. When BTC is in a
macro-bullish recovery phase:
- SHORT setups (bearish signals on 15m) fail more frequently
- The 2.2% TP for shorts requires sustained moves that don't develop in rising markets
- Bounce-type shorts (the system's best SHORT setups) reverse too quickly

### Why the in-sample result is suspicious in retrospect

The in-sample period contains BTC declining from ~$109k to ~$71k (a -35% move over 6 months).
This is an unusually directional bear market. The SHORT-dominant nature of the in-sample
edge (+11.49% SHORT vs +3.52% LONG) reflects this: the system was profitable primarily
because it was trading in the direction of a sustained 6-month decline.

This is not a generalizable structural edge — it is a regime-specific profitability
that happened to align with the in-sample market direction.

### The CB cannot rescue regime-specific failure

37 CB activations OOS (same as in-sample: 36). 233 entries blocked (vs 217 in-sample).
The CB fired at the same rate, blocked roughly the same number of entries, but the
underlying signal quality was so poor (20% WR) that even with CB protection, the
system lost -24.39%.

This demonstrates that the CB is a loss-compression tool, not an edge-generation tool.
When the underlying signal has no edge (PF=0.47), CB can slow the decline but cannot
make it profitable.

---

## Verdict: NOT VALIDATED

| Question | Answer |
|----------|--------|
| Positive edge OOS? | NO — PF=0.47, Cum=-24% |
| Any profitable month? | NO — 0 of 7 months positive |
| SHORT side survived? | NO — PF=0.42, WR=10% |
| LONG side survived? | NO — PF=0.51, WR=26% |
| Drawdown acceptable? | NO — 26.15% vs 8.29% IS |
| Generalizable? | NO — regime-specific failure |

**The current baseline does not generalize to the preceding 6-month window.**
**The in-sample edge is dataset-specific and should not be deployed.**

---

## Final Recommendation

**STOP optimization and treat the current system as unconfirmed.**

The walk-forward test is the most important diagnostic available. This result is
clear and honest: the strategy is not ready and likely not sound as currently designed.

Specific findings that must be addressed before further progress:

### 1. The SHORT side is the system's core weakness
The in-sample profitability was SHORT-dominated (73 trades, PF=1.35). OOS, shorts
were scarce (39 trades) and catastrophic (PF=0.42). A system that loses its primary
edge entirely under a different regime is not fit for deployment.

**Required:** Understand when SHORT setups work and don't work at the structural level,
not just at the parameter level.

### 2. The regime filter is incomplete
REGIME_FILTER_LONG blocks LONGs when BTC < 1h EMA200. It has no equivalent SHORT
protection. In the OOS period, BTC was macro-bullish (above EMA200) — the filter
correctly blocked some LONGs, but LONGs still failed (WR=26%). Meanwhile, SHORT
entries in a bullish macro regime were not blocked, and they were catastrophic.

**Required:** A regime-aware SHORT filter (e.g., block SHORTs when BTC is in a strong
uptrend) is needed to match the LONG-side protection.

### 3. The 2.2% SHORT TP is too ambitious in non-trending regimes
In the OOS period, BTC's 15m volatility apparently didn't sustain 2.2% moves down
from SHORT entries. The SHORT TP structure requires trending, not oscillating, markets.

**Required:** SHORT TP may need to be adaptive or the system needs a mechanism to
identify whether the market is in a trending vs oscillating regime before entering SHORTs.

### 4. The in-sample 6-month window is too narrow and directional
Testing on a period that happens to coincide with a sustained bear market will always
produce SHORT-heavy profitability. The 180d in-sample window needs to include at least
one full bull-bear cycle before parameter choices can be trusted.

**Required:** Use at least 12 months of in-sample data spanning different regimes.

---

## Path Forward

Before any further optimization or deployment consideration:

1. **Understand the OOS regime** — chart BTC from Apr–Sep 2025. Confirm whether it
   was a bull recovery, range market, or other structure. This will clarify whether
   the OOS failure is expected or surprising given market context.

2. **Add a macro SHORT regime filter** — if BTC is above its 1h EMA200 (bullish macro),
   short entries should be blocked or highly selective. This mirrors the existing LONG
   filter and may recover much of the OOS performance.

3. **Expand the dataset to at least 12 months** — covering both the current bear period
   (in-sample) and the prior bull run (OOS), so parameters cannot over-fit to one phase.

4. **Do NOT paper-trade the current system.** The OOS result is too poor to justify
   even paper monitoring as a way to validate live behavior.

---

## Artifacts

- `fetch_oos.py` — OOS data fetcher (explicit date range, Apr–Sep 2025)
- `backtest_oos.py` — OOS backtest runner (calls backtest.py directly, no code changes)
- `data/BTCUSDT_15m_oos_180d.csv` — 17280 OOS 15m candles
- `data/BTCUSDT_1h_oos_200d.csv` — 4800 OOS 1h candles
- `data/backtest_BTCUSDT_oos_walkforward.json` — full trade and signal log
