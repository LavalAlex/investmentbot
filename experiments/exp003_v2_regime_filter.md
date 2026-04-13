# EXP003-v2 — Regime Filter (Directional Efficiency)

## Hypothesis

Losing months in EXP002 (IS Dec 2025, OOS Apr/Jun 2025) may share a structural market
characteristic that can be detected and used to pause trading.

By identifying "bad regimes" at entry time, we avoid low-quality environments without
changing the core pullback continuation logic.

## Analysis of losing months

### Step 1 — Monthly characterization (1h data)

| Month | Result | Price range | EMA wander | Sign changes/d | ATR% |
|---|---|---|---|---|---|
| IS Nov-2025 | WIN +1773 | 30.0% | 27.0% | 1.5 | 0.78% |
| IS Dec-2025 | LOSS -1260 | **10.9%** | **8.2%** | 1.5 | 0.65% |
| IS Jan-2026 | WIN +1737 | 22.0% | 17.7% | 1.4 | 0.54% |
| OOS Apr-2025 | LOSS -894 | 23.8% | 20.7% | 1.6 | 0.72% |
| OOS May-2025 | WIN +2467 | 17.6% | 16.2% | 1.3 | 0.56% |
| OOS Jun-2025 | LOSS -538 | **10.8%** | **8.3%** | 1.8 | 0.47% |
| OOS Jul-2025 | WIN +1710 | 15.1% | 12.9% | 1.3 | 0.46% |

Dec and Jun share clearly: tight price range, low EMA wander, higher slope direction changes.
Apr is structurally different — wide range, volatile, both directions losing.

### Step 2 — Filters tested and rejected

Before settling on Efficiency Ratio, the following were evaluated against EXP002 trade data:

**EMA slope persistence (consecutive same-direction bars):**
- Losing months don't have shorter runs consistently. Dec avg run = 16.5h almost identical to Nov = 16.4h.
- At persist >= 8: losing months barely improved, winning months degraded.
- **Rejected.**

**EMA20/EMA50 slope alignment (both slopes same direction):**
- In Dec, Apr, Jun: aligned trades performed WORSE (lower WR) than misaligned trades.
- Filter would keep the losing trades and discard the winners.
- **Rejected.**

**EMA20/EMA50 price-level alignment (EMA20 above/below EMA50):**
- Same pattern: aligned trades systematically worse than misaligned in loss months.
- Dec aligned: -904 (29% WR). Jun aligned: -1185 (29% WR). Both worse than unfiltered.
- **Rejected.**

### Step 3 — Efficiency Ratio (Kaufman ER)

Static trade-level analysis showed:
- ER 0.10–0.15 bucket was the worst zone in both IS and OOS (WR=27-28%, large losses)
- ER >= 0.15 retained higher-WR trades on paper (IS: 40%, net +4504 vs +3968)
- Jun OOS improved from -538 to +286 at ER >= 0.10

**Chosen filter: `ER >= 0.15` on 24-bar 1h rolling window (Kaufman Efficiency Ratio)**

Formula: `ER = |close[i] - close[i-24]| / sum(|close[j] - close[j-1]|, j=i-23..i)`

This measures directional efficiency: 1.0 = perfectly trending, 0.0 = perfectly choppy.

## Implementation

- `indicators_v2.py` — added `efficiency_ratio(series, window)` (vectorized)
- `strategy_pullback.py` — added `MIN_ER = 0.15`, `er24` to `prepare_1h` and alignment, `is_market_efficient(row)`
- `backtest_exp003.py` — ER filter applied as first signal check (before EXP002 filters)

One new parameter: `MIN_ER = 0.15`

## Results

### In-sample (Sep 2025 – Mar 2026)

| Metric | EXP002 | EXP003 | Change |
|---|---|---|---|
| Total trades | 442 | 229 | -48% |
| Win rate | 36.2% | 36.7% | +0.5pp |
| Total return | +39.7% | +22.9% | **-17pp** |
| Max drawdown | 17.8% | **21.3%** | **+3.5pp worse** |
| Profit factor | 1.115 | **1.155** | +0.04 |
| Expectancy | $8.98 | $10.0 | +$1.0 |

Monthly IS:
```
2025-09  n=  4  WR=25%  net=  -103
2025-10  n= 43  WR=35%  net=  +156
2025-11  n= 35  WR=26%  net=  -801  ← WAS +1773 in EXP002, now WORSE
2025-12  n= 35  WR=26%  net=  -738  ← WAS -1260, slight improvement
2026-01  n= 46  WR=50%  net= +2141
2026-02  n= 39  WR=38%  net=  +612
2026-03  n= 27  WR=44%  net= +1023
```

### Out-of-sample (Mar – Sep 2025)

| Metric | EXP002 | EXP003 | Change |
|---|---|---|---|
| Total trades | 417 | 264 | -37% |
| Win rate | 36.9% | 35.6% | **-1.3pp** |
| Total return | +48.4% | +15.2% | **-33pp** |
| Max drawdown | 11.7% | **15.4%** | **+3.7pp worse** |
| Profit factor | **1.155** | 1.089 | **-0.07 worse** |
| Expectancy | $11.62 | $5.76 | **-$5.86 worse** |

Monthly OOS:
```
2025-03  n=  6  WR=17%  net=  -300
2025-04  n= 39  WR=23%  net= -1125  ← unchanged / slightly worse
2025-05  n= 48  WR=40%  net=  +759
2025-06  n= 41  WR=37%  net=  +340  ← WAS -538, improved
2025-07  n= 34  WR=38%  net=  +459
2025-08  n= 66  WR=38%  net=  +877
2025-09  n= 30  WR=40%  net=  +511
```

### Filter rejection breakdown (IS)

| Filter | Bars rejected |
|---|---|
| Efficiency (ER) | 6,712 |
| Trend strength | 1,858 |
| Pullback quality | 5,583 |
| Candle quality | 395 |
| Range floor | 7 |

ER is now the dominant filter (6,712 bars), more rejections than pullback quality.

## Decision: REVERT

The ER filter does not improve the system.

**What went wrong:**
- The static trade-level bucketing analysis (ER buckets by WR) was misleading.
  The ER 0.10–0.15 danger zone was partly a correlation artifact.
- In practice, the filter removed many **good trades from winning months**,
  particularly November IS which went from +$1,773 to −$801 (a catastrophic regression).
- The filter helped Jun OOS (+$339 vs −$538) but this was more than offset by the
  damage to other months.
- OOS PF regressed from 1.155 → 1.089 (below EXP002 baseline).
- Both IS and OOS max drawdown got worse, not better.

**The deeper finding from the analysis:**
No tested filter (ER, slope persistence, slope alignment, price-level alignment) could
reliably separate the losing months from winning months without removing too many good trades.
The pattern is consistent across all approaches:

- Dec IS, Apr OOS, Jun OOS are bad for the STRATEGY in those periods.
- The bad trades do not have a consistently distinct signal characteristic.
- Any filter aggressive enough to eliminate them also removes good trades from other months.

**Why Dec and Jun are hard:**
- Both are low-range, choppy months. The strategy fires entries but price doesn't follow through.
- This isn't about entry quality — it's about market follow-through that can't be measured
  reliably at the bar where the entry fires.

**Why Apr OOS is hard:**
- High volatility, wide range, but contradictory direction. The strategy enters both ways and loses.
- No indicator tested could detect this in advance.

**Structural lesson for future experiments:**
- The losing months represent regime failures that are not predictable by simple EMA or
  volatility indicators computed at entry time.
- A meaningful regime filter may require either:
  a) A longer lookback (multi-day trend evaluation) — more complex
  b) Volume or order-flow information (not available in OHLCV)
  c) Acceptance that these months are irreducible losses at the current system stage

## What to try next (EXP004 candidates)

Given the findings, the regime approach needs a different direction:
- Instead of filtering entries, consider adjusting **which direction is tradeable per day**
  based on a daily-bar or multi-day trend measure
- Or: accept the losing months as a cost of doing business and focus EXP004 on improving
  the winning month performance rather than patching the losers
- Or: test a 1:1 R:R vs 2:1 — in choppy markets the high TP is rarely reached; a lower TP
  might improve win rate enough to stay flat in bad months
