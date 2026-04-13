# EXP006-v2 — Walk-Forward Robustness Validation

## Hypothesis

EXP002 has passed IS/OOS testing and cross-asset validation.
The remaining risk is time-regime dependency: the system might look good only because
the test periods happened to contain favorable market conditions.

Walk-forward across sequential non-overlapping 3-month windows will reveal:
- Whether the edge persists across different market environments
- Whether any single period is carrying the overall result
- Whether win rate is stable or highly regime-dependent

## Setup

**Strategy:** EXP002-v2 — zero modifications.
**Data:**
- BTC: 12 months continuous (OOS Mar–Sep 2025 + IS Sep–Mar 2026, concatenated)
- ETH: 6 months IS only (Sep 2025 – Mar 2026)

**Walk-forward structure:**
Since there is no optimization, "train" serves only as indicator warm-up. The system
runs live from the first available bar, with equity evolving continuously. Performance
is then evaluated in sequential 3-month windows based on trade close timestamps.

**BTC windows (4 × 3 months):**
- W1: Apr–Jun 2025   (OOS first half)
- W2: Jul–Sep 2025   (OOS second half)
- W3: Oct–Dec 2025   (IS first half)
- W4: Jan–Mar 2026   (IS second half)

**ETH windows (2 × 3 months):**
- W1: Oct–Dec 2025
- W2: Jan–Mar 2026

## Results

### BTC — 4 windows

| Window | Trades | Win Rate | Return | Max DD | PF |
|---|---|---|---|---|---|
| W1: Apr–Jun 2025 | 210 | 35.2% | +10.4% | 11.7% | **1.071** |
| W2: Jul–Sep 2025 | 200 | 38.0% | +29.5% | 9.6% | **1.197** |
| W3: Oct–Dec 2025 | 222 | 36.5% | +20.6% | 16.8% | **1.122** |
| W4: Jan–Mar 2026 | 211 | 37.0% | +23.1% | 17.8% | **1.146** |

**Summary:**
- PF > 1.0: **4/4 windows**
- PF range: 1.071 – 1.197 (std dev: 0.045)
- PF median: 1.146
- WR range: 35.2% – 38.0% (**spread: 2.8pp** across 12 months)
- Best window: W2 (PF 1.197, +29.5%)
- Worst window: W1 (PF 1.071, +10.4%)

### ETH — 2 windows

| Window | Trades | Win Rate | Return | Max DD | PF |
|---|---|---|---|---|---|
| W1: Oct–Dec 2025 | 242 | 36.0% | +17.9% | 21.9% | **1.099** |
| W2: Jan–Mar 2026 | 205 | 40.0% | +47.4% | 12.3% | **1.325** |

**Summary:**
- PF > 1.0: **2/2 windows**
- PF range: 1.099 – 1.325 (std dev: 0.113)
- WR range: 36.0% – 40.0% (spread: 4.0pp)

### Shared calendar view (BTC and ETH, same 6 months)

| Period | BTC PF | BTC Return | ETH PF | ETH Return |
|---|---|---|---|---|
| Oct–Dec 2025 | 1.122 | +20.6% | 1.099 | +17.9% |
| Jan–Mar 2026 | 1.146 | +23.1% | 1.325 | +47.4% |

Both assets profitable in both shared windows. The cross-asset consistency here provides
strong corroborating evidence that the edge is structural, not period-specific.

## Decision: ROBUST SYSTEM

**6/6 windows profitable** across two assets and 12 total months of data.

### What the results show

**1. The edge is not period-specific.**
BTC is profitable in all 4 windows spanning Apr 2025 – Mar 2026. This covers:
- Two different market directions (pre and post Sep 2025 BTC leg)
- The December 2025 choppy period (W3 is still PF 1.122, because Oct and Nov offset Dec)
- Two distinct volatility regimes

**2. Win rate is remarkably stable.**
BTC WR varies only 2.8pp across 12 months (35.2%–38.0%). This is the most important
consistency signal: the strategy finds the same type of setup regardless of the
overall market regime. A system with regime dependency would show WR swings of 10–15pp.

**3. The edge is thin but consistent.**
PF 1.071–1.197 is a narrow range, not because performance is high but because it is
*stable*. The worst window (BTC W1, Apr–Jun 2025) still has PF 1.071. The system
earns consistently, not spectacularly.

**4. No single window is carrying the result.**
BTC returns per window: +10.4%, +29.5%, +20.6%, +23.1%. There is no 3-month period
where the system earns most of its lifetime return. W2 is the best at +29.5% but the
others are not outliers.

**5. DD is bounded and consistent.**
W1 and W2 DD (9.6%–11.7%) are lower than W3 and W4 (16.8%–17.8%). The higher W3/W4
DD corresponds to the Dec 2025 choppy environment that we identified in EXP003 analysis.
Even in the worst drawdown period the system stays within the 18% DD seen in EXP002 IS.

**6. BTC and ETH corroborate each other.**
In the two shared calendar windows, BTC and ETH show similar PF values (1.122 vs 1.099
for Oct–Dec; 1.146 vs 1.325 for Jan–Mar). The directionality matches: both improve
from W1 to W2 in the shared period. ETH W2 is stronger (+47.4%) due to its more
favorable market structure in Jan–Mar 2026.

### Why the Dec 2025 bad month doesn't break the walk-forward

In per-month analysis (EXP002/EXP003), December IS was −$1,260. But in the walk-forward,
W3 (Oct–Dec 2025) shows PF 1.122 and +20.6% return. This is because:
- October (+$1,421) and November (+$1,773) offset December (−$1,260)
- Within a 3-month evaluation window, the system recovers from bad months
- This confirms the "losing months as irreducible noise" interpretation from EXP003:
  they are not regime collapses but temporary underperformance in an otherwise functional system

## Final system classification

**The pullback continuation strategy (EXP002) is a robust system.**

| Criterion | Result |
|---|---|
| Majority of windows PF > 1 | ✓ 6/6 windows |
| No single dominant window | ✓ BTC returns: 10–30% range |
| Consistent win rate | ✓ 2.8pp spread over 12 months (BTC) |
| Cross-asset confirmation | ✓ BTC and ETH agree on shared periods |
| DD bounded | ✓ Max 17.8% across all windows |
| Edge held through different regimes | ✓ Bullish, choppy, ranging all positive |

## Limitations of this validation

1. **ETH has only 2 windows.** The ETH data covers only the IS period (Sep–Mar 2026).
   A full 12-month ETH walk-forward would require fetching earlier ETH data.

2. **12 months is a short track record.** This is strong evidence of robustness given
   the data available, but a longer history (24–36 months) would provide more confidence.

3. **Shared IS/OOS boundary.** BTC W3 and W4 correspond to the IS period, W1 and W2
   to OOS. The fact that OOS windows are also profitable validates the IS/OOS test from
   EXP002 — they show the same result from a different angle.

## Readiness assessment for Phase 2

| Criteria | Status |
|---|---|
| IS/OOS consistent (EXP002) | ✓ |
| Cross-asset generalization (EXP005) | ✓ BTC + ETH + BNB |
| Walk-forward robustness (EXP006) | ✓ 6/6 windows |
| Parameter optimization avoided | ✓ |
| Overfitting risk low | ✓ EXP003/004 showed filters don't overfit IS |

**The system is ready for Phase 2 (paper trading preparation).**

## What to do in Phase 2

1. **Paper trading setup** — Deploy EXP002 on BTC/USDT live data (no real orders).
   Track realized vs backtested metrics in real time.

2. **Live signal monitoring** — Implement a signal scanner that logs entry signals
   as they occur. Compare signal frequency to backtest (~2–3 per day).

3. **Slippage and execution modeling** — The backtest uses close price as entry.
   In live trading, entries occur at market on bar close, introducing fill slippage.
   Model 0.05%–0.1% slippage to see how much it reduces PF.

4. **ETH inclusion** — Consider running EXP002 on ETH paper trading in parallel,
   given its strong walk-forward result (PF 1.099–1.325).
