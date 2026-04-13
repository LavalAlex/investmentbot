# Experiment 020 — ADX Trend Strength Filter

**Date:** 2026-04-01
**Status:** REVERTED

---

## Hypothesis

The current system detects trend DIRECTION (EMA alignment, RSI midline) but not
trend STRENGTH. Adding 1h ADX14 > 20 as a hard gate (applied to both BUY and SELL)
would suppress entries in ranging/choppy conditions and improve performance in the
losing months (Oct 2025, Dec 2025) without significantly harming the strong months
(Nov 2025, Jan 2026).

**Change:** Added ADX14 calculation to `indicators.py`. Added `1h ADX14 > 20` as a
hard gate to both BUY `hard_filters` and SELL `sell_hard_filters` in `signal_engine.py`.
Also updated `_htf_confirmation()` to return `htf_adx14`.

---

## Results

### Metrics Comparison

| Metric | Baseline | EXP020 (ADX > 20) | Δ |
|--------|----------|-------------------|---|
| Total trades | 134 | **104** | **-30** |
| Win rate | 35.07% | **28.85%** | **-6.22pp** |
| Cumulative return | +15.41% | **-1.84%** | **-17.26pp** |
| Max drawdown | 8.29% | **14.34%** | **+6.05pp** |
| Profit factor | 1.2784 | **0.9719** | **-0.306** |
| Expectancy | +0.1128% | **-0.0125%** | **-0.1253pp** |

**LONG side:**
| Metric | Baseline | EXP020 | Δ |
|--------|----------|--------|---|
| Trades | 61 | 43 | -18 |
| Win rate | 40.98% | 34.88% | -6.1pp |
| Profit factor | 1.1688 | 0.9146 | -0.254 |

**SHORT side:**
| Metric | Baseline | EXP020 | Δ |
|--------|----------|--------|---|
| Trades | 73 | 61 | -12 |
| Win rate | 30.14% | 24.59% | -5.55pp |
| Profit factor | 1.3516 | 1.0033 | -0.348 |

The system crosses below PF 1.0 → net-losing system.

---

### Monthly Breakdown

| Month | BL Trades | BL WR | BL Ret | EX Trades | EX WR | EX Ret | ΔRet | Verdict |
|-------|-----------|-------|--------|-----------|-------|--------|------|---------|
| 2025-10 | 21 | 28.6% | -1.78% | 20 | 25.0% | -2.16% | -0.38% | ✗ |
| **2025-11** | **27** | **33.3%** | **+3.81%** | **16** | **12.5%** | **-5.69%** | **-9.49%** | **✗✗** |
| 2025-12 | 18 | 22.2% | -3.58% | 12 | 16.7% | -2.98% | +0.60% | ✓ |
| **2026-01** | **22** | **54.5%** | **+10.59%** | **18** | **44.4%** | **+5.21%** | **-5.38%** | **✗** |
| 2026-02 | 24 | 29.2% | +2.65% | 21 | 33.3% | +3.89% | +1.24% | ✓ |
| 2026-03 | 22 | 40.9% | +3.41% | 17 | 35.3% | +0.31% | -3.10% | ✗ |

**Key observation:** Nov 2025 loses -9.49% and Jan 2026 loses -5.38% under the ADX gate.
These were the two most profitable months. Only Dec 2025 (+0.60%) shows marginal improvement.

---

### ADX Distribution (Baseline Trades by Outcome)

| ADX Range | Total | Wins | Losses | WR% |
|-----------|-------|------|--------|-----|
| [10, 20) | 30 | 10 | 20 | 33% |
| [20, 30) | 47 | 15 | 32 | **32%** |
| [30, 40) | 30 | 13 | 17 | 43% |
| [40, 50) | 16 | 6 | 10 | 38% |
| [50, 60) | 9 | 3 | 6 | 33% |
| [60, 70) | 2 | 0 | 2 | 0% |

**ADX ≤ 20 (blocked trades):** 30 trades, 10W / 20L, WR **33.3%**

Winner ADX stats: mean 30.4, median 28.8, p25 20.5, p75 38.5
Loser ADX stats: mean 29.7, median 26.9, p25 20.0, p75 36.9

---

### Step 5 — Validation

1. **Does ADX reduce trades in losing months?** BARELY
   - Oct 2025: 21→20 (-1 trade), return Δ -0.38% — made it WORSE
   - Dec 2025: 18→12 (-6 trades), return Δ +0.60% — marginal improvement

2. **Does ADX preserve trades in strong months?** NO
   - Jan 2026: 22→18 (-4 trades), return Δ -5.38%
   - Nov 2025: 27→16 (-11 trades), return Δ -9.49% ← catastrophic

3. **Are blocked trades mostly losers?** YES — but it doesn't matter
   - 30 blocked trades: 10W / 20L = 33.3% WR
   - This is nearly identical to the system's overall 35.07% WR
   - ADX is blocking losers AND winners at approximately the same rate

---

## Analysis — Why the Hypothesis Failed

### 1. ADX WR is flat across all levels — no discriminating power

The win rate by ADX bucket is:
```
ADX [10,20): 33%   ADX [20,30): 32%   ADX [30,40): 43%
ADX [40,50): 38%   ADX [50,60): 33%
```

There is no monotonic relationship between ADX level and trade quality.
The system's WR is essentially constant (32–43%) regardless of whether
ADX is 12 or 55. ADX does not predict trade outcomes for this strategy.

### 2. The existing confluence filters already capture what ADX measures

ADX > 20 indicates "a trend exists." But our system already requires, to enter:
- 15m EMA20 > EMA50 (trend confirmed on short timeframe)
- 1h EMA20 > EMA50 (trend confirmed on higher timeframe)
- Price > 1h EMA200 (macro trend confirmed)
- 1h RSI > 50 (momentum not bearish)
- 15m market structure = BULLISH/BEARISH (HH/HL confirmed)

By the time all five conditions are true, the market IS trending by any reasonable
definition. ADX > 20 is testing for something the existing gates already confirm.
The ADX gate is redundant — it adds bureaucracy without adding information.

### 3. The blocked trades at ADX ≤ 20 are legitimate entries

ADX can be low during two distinct phases:
- **Phase A:** True ranging/choppy market (oscillating sideways)
- **Phase B:** EARLY in a new trend (ADX lags the trend — it takes 14+ periods to reflect a new directional move)

Phase B entries are exactly the most profitable ones. Nov 2025 had the strongest
directional moves, but ADX at the START of those moves was still sub-20 or transitioning
through 20. Blocking "ADX just crossed 20" entries means missing the early momentum
that drives the largest wins.

The -9.49% impact on Nov 2025 (11 blocked trades, most of them likely early-trend
quality entries) confirms this directly.

### 4. ADX lagging causes asymmetric damage

For the same reason that EMA lagging causes "late entry" problems, ADX lagging means:
- When a new trend starts: ADX is still < 20 → gate blocks entry → miss the move
- When a trend matures: ADX is > 20 → gate allows entry → enter mid-trend or late

This is the opposite of what was intended. ADX as a hard gate effectively selects for
LATE-trend entries and blocks EARLY-trend entries — worsening the already-identified
late-entry structural issue.

### 5. Cascade effects amplify the damage

Blocking 30 trades changes the CB state, cooldown timing, and entry sequence for
subsequent candles. The actual WR of trades taken under EXP020 (28.85%) is LOWER
than expected from simple subtraction (which would predict ~35.6%). This means the
cascading effects of altered CB timing cost additional wins beyond the 10 directly
blocked winners.

---

## Decision: REVERT

`indicators.py`: ADX14 calculation removed.
`signal_engine.py`: `_htf_confirmation` reverted to 5-value return (no ADX).
Hard gate `1h ADX14 > 20` removed from both BUY and SELL filter dicts.

**Baseline fully restored: 134 trades, WR 35.07%, Cum +15.41%, PF 1.2784.**

---

## Key Finding for Future Research

**ADX does not improve this system because:**
1. The existing EMA/RSI/structure confluence already requires trend presence
2. ADX is redundant with the existing trend-confirmation hard gates
3. ADX lags trend starts, blocking the most profitable early-trend entries
4. Win rate is flat across all ADX levels — no discriminating power found

**The ranging-market problem requires a different solution.**

The root cause is not *absence of trend* (ADX would fix that).
The root cause is *absence of momentum within the trend* — price is technically
above the EMAs and in a valid trend structure, but is oscillating without
sustained directional drive. ADX is too slow to detect this.

**More targeted alternatives to investigate:**

1. **Candle body quality**: Enter only when the entry candle's close is meaningfully
   in the direction of the trade (body > X% of ATR14). Small-body doji-like candles
   at an EMA suggest hesitation, not momentum. This is instantaneous (no lag).

2. **Price acceleration**: Is price moving AWAY from EMA20 (accelerating into the
   trend) or converging toward it (stalling)? Entry when `(close - EMA20)/EMA20`
   is expanding suggests live momentum.

3. **EMA cross recency**: How many candles since EMA20 crossed EMA50? Fresh crosses
   have more remaining trend than stale ones. The earlier research framework
   (EXP020 research analysis) identified this as Hypothesis 3.

---

## Artifacts

- `exp020_adx_filter.py` — experiment runner (kept for reference)
- `data/backtest_BTCUSDT_180d_exp020_adx.json` — full trade log with ADX gate
