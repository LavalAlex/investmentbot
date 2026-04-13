# Experiment 021 — Candle Body Quality Filter

**Date:** 2026-04-05
**Status:** REVERTED

---

## Hypothesis

The current system detects trend direction but not current-candle momentum commitment.
Entries triggered by small-body / doji-like 15m candles near EMAs represent hesitation
rather than trend participation. These entries fail to sustain the directional move
needed to reach TP and hit SL during choppy oscillation phases (Oct 2025 ATH chop,
Dec 2025 post-crash consolidation).

**Gate tested:**
```
BUY  → body_ratio = (close - open) / atr14  >= 0.3
SELL → body_ratio = (open - close) / atr14  >= 0.3
```

Applied as the final gate before position entry (after cooldown, CB, regime filter).
A negative body_ratio (candle closed against trade direction) is also blocked.

**Canonical threshold:** 0.3 (one value, no sweep)

**Why this approach was selected:**
- Zero lag (current candle — no rolling window)
- Low redundancy with existing filters (no existing body/ATR check)
- Specifically named as the top post-ADX alternative in the EXP020 write-up
- ADX failed by lagging; body quality is instantaneous
- Winners have meaningfully higher body ratios than losers (confirmed by diagnostic)

---

## Phase 1 — Diagnostic: Body Ratio Distribution

The diagnostic pass re-ran the baseline simulation with body_ratio tracking
(no blocking). It returned 136 trades vs baseline 134 — the 2-trade difference
is due to the HTF_WINDOW=250 cap used for performance optimization causing minor
EMA200 differences at margin cases. The analysis remains valid.

### Body ratio distribution across all 136 diagnostic trades:

| Bucket                          | N  | Wins | WR%   | PF    | Cum%    |
|---------------------------------|----|------|-------|-------|---------|
| < 0.0 (counter-direction candle) | 58 | 17   | 29.3% | 0.920 | -2.39%  |
| [0.0, 0.1)                       | 2  | 1    | 50.0% | 1.250 | +0.19%  |
| [0.1, 0.2)                       | 4  | 1    | 25.0% | 0.417 | -1.40%  |
| [0.2, 0.3)                       | 4  | 2    | 50.0% | 5.000 | +1.60%  |
| [0.3, 0.5)                       | 10 | 4    | 40.0% | 1.595 | +2.20%  |
| [0.5, 0.8)                       | 18 | 6    | 33.3% | 0.918 | -0.71%  |
| >= 0.8                           | 40 | 16   | 40.0% | 1.736 | +11.34% |

### Threshold split at 0.3:

| Group          | N  | WR    | PF    | Cum%    |
|----------------|----|-------|-------|---------|
| BLOCKED (< 0.3)| 68 | 30.9% | 0.943 | -2.03%  |
| KEPT   (>= 0.3)| 68 | 38.2% | 1.479 | +12.98% |

### Winner vs Loser body_ratio stats:

| Group  | Mean  | Median | P25    | P75   |
|--------|-------|--------|--------|-------|
| Winner | 0.444 | 0.438  | -0.387 | 1.188 |
| Loser  | 0.183 | 0.155  | -0.437 | 0.812 |

**Key diagnostic finding:** Winners have meaningfully higher body ratios than losers
(mean 0.444 vs 0.183; median 0.438 vs 0.155). The underlying information dimension
IS real. Blocked trades collectively lose (PF=0.943, WR=30.9% vs system 35.1%).

---

## Phase 2 — Experiment Results

### Full metrics comparison:

| Metric                | Baseline | EXP021 | Δ       |
|-----------------------|----------|--------|---------|
| Total trades          | 134      | **106** | **-28** |
| Win rate              | 35.07%   | **28.30%** | **-6.77pp** |
| Cumulative return     | +15.41%  | **-3.43%** | **-18.85pp** |
| Max drawdown          | 8.29%    | **11.87%** | **+3.57pp** |
| Profit factor         | 1.2784   | **0.9378** | **-0.341** |
| Expectancy            | +0.113%  | **-0.028%** | **-0.141pp** |
| Longest loss streak   | 10       | **13** | **+3** |

**The system crosses below PF 1.0 → net-losing system.**

### Side breakdown:

| Side  | Baseline              | EXP021                |
|-------|----------------------|-----------------------|
| LONG  | 61t · 41.0% · PF 1.17 | 43t · 37.2% · PF 0.94 |
| SHORT | 73t · 30.1% · PF 1.35 | 63t · 22.2% · PF 0.94 |

---

## Phase 3 — Monthly Breakdown

| Month   | BL T | BL WR | BL Ret  | EX T | EX WR | EX Ret  | ΔRet   | Verdict |
|---------|------|-------|---------|------|-------|---------|--------|---------|
| 2025-10 | 21   | 28.6% | -1.78%  | 15   | 20.0% | -3.57%  | -1.79% | WORSE ◄ |
| 2025-11 | 27   | 33.3% | +3.81%  | 19   | 26.3% | -0.77%  | -4.58% | WORSE   |
| 2025-12 | 18   | 22.2% | -3.58%  | 14   |  7.1% | -5.09%  | -1.51% | WORSE ◄ |
| 2026-01 | 22   | 54.5% | +10.59% | 16   | 37.5% | +2.35%  | -8.24% | WORSE ◄ |
| 2026-02 | 24   | 29.2% | +2.65%  | 21   | 33.3% | +3.44%  | +0.79% | BETTER  |
| 2026-03 | 22   | 40.9% | +3.41%  | 21   | 38.1% | +0.44%  | -2.97% | WORSE   |

**Target months (Oct, Dec 2025):** WORSE in both cases.
**Protected months (Jan 2026):** Catastrophically damaged (-8.24%).
**Only Feb 2026 shows marginal improvement (+0.79%).**

---

## Phase 4 — Blocking Analysis

Total signals blocked: **92** (BUY=49, SELL=43)
Body ratio of blocked signals: min=-2.11, max=0.28, mean=-0.43

### Monthly distribution of blocked signals:

| Month   | BUY | SELL | Total |
|---------|-----|------|-------|
| 2025-10 | 11  | 3    | 14    |
| 2025-11 | 5   | 20   | 25    |
| 2025-12 | 11  | 3    | 14    |
| 2026-01 | 8   | 4    | 12    |
| 2026-02 | 1   | 9    | 10    |
| 2026-03 | 12  | 4    | 16    |

**Critical observation:** In Nov 2025 (the second most profitable month), the body
quality gate blocked **20 SELL signals** out of 25 total blocks. These were SHORT
entries in the strongest down-trending month. The gate catastrophically damaged the
best-performing SHORT month by blocking its most active entries.

---

## Analysis — Why the Gate Failed Despite Real Discriminating Power

### 1. The diagnostic found real information, but the gate direction is asymmetric

**For BUY signals:** Requiring a bullish candle (close > open) with meaningful body
makes intuitive sense — we want price moving in our direction before entering long.

**For SELL signals (SHORT):** This is WRONG. The most reliable SHORT entries are
frequently triggered on **bullish bounce candles** in downtrends. The trend is down,
RSI is below 50, EMAs are crossed bearishly, but the signal candle itself is a brief
relief bounce (bullish candle → negative SELL body_ratio → blocked).

The system was generating valid SHORT entries during Nov 2025's strong bear trend,
but MANY of those entry candles were minor bounces (bullish bodies) within the larger
downtrend. Blocking SELL signals when the candle is bullish eliminates the best
SHORT entries: the bounce-and-continue SHORT is a core SHORT setup.

**Result:** 20/25 of Nov 2025's blocked signals were SELL on bullish bounce candles —
exactly the opposite of what should be blocked.

### 2. The cascading effect amplifies damage

Blocking 28 trades changes CB trigger times and cooldown scheduling for all subsequent
candles. The actual WR of trades taken under EXP021 (28.3%) is significantly below
what "kept trades" suggested (38.2% in the diagnostic). This gap is the cascade effect:
altering the CB state lets through different (worse) sets of subsequent trades.

This is the same cascade effect that damaged ADX (EXP020) by -9.49% in Nov 2025.
Here, the Nov 2025 damage is -4.58% — same direction, similar mechanism.

### 3. The aggregate discriminating signal is real but not directionally consistent

The diagnostic shows:
- Trades with body_ratio ≥ 0.3 collectively win (WR=38.2%, PF=1.479)
- Trades with body_ratio < 0.3 collectively lose (WR=30.9%, PF=0.943)

BUT this aggregate result HIDES an asymmetry:
- For LONG trades: the signal candle should logically be bullish → body quality likely helps
- For SHORT trades: the signal candle is frequently bearish (but often the best entry
  is after a bounce, i.e., a bullish candle within the downtrend)

Applying the gate symmetrically to both sides is incorrect. The gate may have merit
for LONG entries only, but cannot be applied to SELL (SHORT) entries as designed.

### 4. The blocked trades in the diagnostic are below system WR but not by enough

The 68 blocked baseline trades have WR=30.9% (vs system WR=35.1% → only -4.2pp below).
For the gate to clearly improve the system, blocked trade WR should be substantially
below the breakeven threshold (~28-30% at current SL/TP).

At WR=30.9%, blocked trades are above breakeven. Removing them:
- Eliminates net-negative contributors (PF=0.943 < 1.0)
- BUT the remaining trades get disrupted by cascade effects
- Net result: system performs worse

---

## Key Structural Finding

**Body quality information is real and directional:**
- Median winner body_ratio: 0.438
- Median loser body_ratio:  0.155
- This IS a meaningful information gap between winners and losers

**But the gate as designed fails because:**
1. SHORT entries legitimately trigger on bullish bounce candles (correct SHORT setup)
2. Requiring bearish signal candle for SELL blocks the best SHORT entries
3. Cascading effects amplify the damage past what the blocked-trade analysis predicts

**What might actually work:**
1. Apply body quality gate to **LONG entries only** (BUY requires bullish candle with body ≥ X% ATR)
2. For SHORT entries: use a different metric, e.g., EMA slope on 1h showing consistent decline
3. Or: look at the PRIOR N candles' net direction, not just the signal candle's body

---

## Decision: REVERT

No code was modified in the main system files.
The experiment script `exp021_candle_body_quality.py` is standalone.
The baseline remains fully intact: **134 trades, WR 35.07%, Cum +15.41%, PF 1.2784.**

---

## Anti-Overfitting Assessment

- One threshold tested (0.3) — no sweep conducted ✓
- Result is unambiguously worse across 5/6 months — no cherry-picking ✓
- The gate is not "almost good enough" — it crosses PF below 1.0 → clear REVERT ✓
- The improvement is not explained by a strong month artificially inflating results —
  the strong months were DAMAGED, not helped ✓

---

## Recommendation for Next Step

### Option A: BUY-only body quality gate
Test the body quality gate on **BUY (LONG) entries only**. The diagnostic shows
body quality is more logically aligned with BUY entries. Remove the SELL gate entirely.
If LONG-only body quality improves WR on LONG side without damaging SHORT, this
represents genuine value extraction.

### Option B: Multi-candle displacement (BUY + SELL)
Instead of the single signal candle's body, measure net displacement over 4-6 candles:
`(close[i] - close[i-4]) / atr14`
- For BUY: requires net upward movement over last 4 × 15m = 1h
- For SELL: requires net downward movement over last 4 × 15m = 1h

This is direction-appropriate for both sides and still low-lag (4 candles = 1h lookback).
A SHORT triggered after a bounce would FAIL this test if the 4-candle net is positive
(bounce has not faded yet) — but this is not necessarily the right behavior either.

### Option C: LONG-side analysis only
Given that LONG PF (1.1688) is lower than SHORT PF (1.3516), the most impactful
improvement would come from a LONG-specific filter. Focus exclusively on LONG
entry quality detection, leaving SHORT logic unchanged.

**Recommended next step:** Option A — BUY-only body quality gate (EXP022).
This isolates the body quality concept to the side where it is logically sound,
without introducing the asymmetric SHORT entry problem.

---

## Artifacts

- `exp021_candle_body_quality.py` — experiment runner (kept for reference)
- `data/backtest_BTCUSDT_180d_exp021_body.json` — full trade log with body gate
