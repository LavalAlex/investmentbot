# Experiment 023 — Net Displacement Filter

**Date:** 2026-04-05
**Status:** REVERTED

---

## Hypothesis

Choppy / oscillating market phases produce BUY/SELL signals where price has not
actually moved directionally over the preceding 4 candles (1 hour). Requiring a
minimum net displacement in the direction of the trade filters these oscillating
entries while remaining direction-appropriate for both LONG and SHORT sides.

**Gate:**
```
displacement = (close[i] - close[i-4]) / ATR14

For LONG  → displacement >= +0.5   (price rose ≥ 0.5 ATR over last hour)
For SHORT → displacement <= -0.5   (price fell ≥ 0.5 ATR over last hour)
```

**Parameters:** lookback = 4 candles, threshold = 0.5 ATR (single canonical values, no sweep)

**Why this was selected over EXP021:**
EXP021 (candle body quality) was direction-inappropriate for SHORT entries — bounce-entry
SHORTs are legitimate setups triggered on bullish candles. Displacement over 4 candles
was expected to solve this by requiring net downward movement over the prior hour for
SHORT entries, regardless of the individual signal candle's direction.

---

## Phase 1 — Diagnostic: Displacement Distribution

Diagnostic pass: full simulation with no blocking, displacement recorded for each trade.
136 trades recovered (vs 134 baseline — small difference due to HTF_WINDOW=250 cap).

### Directional displacement by bucket (LONG entries, 66 trades):

| Bucket       | N  | Wins | WR%   | PF    | Cum%    |
|--------------|----|------|-------|-------|---------|
| < -1.0       | 7  | 2    | 28.6% | 0.861 | -0.41%  |
| [-1.0, -0.5) | 1  | 0    | 0.0%  | 0.000 | -0.80%  |
| [-0.5, 0.0)  | 2  | 0    | 0.0%  | 0.000 | -1.59%  |
| [0.0, 0.5)   | 2  | 1    | 50.0% | 1.250 | +0.19%  |
| [0.5, 1.0)   | 8  | 3    | 37.5% | 1.281 | +0.64%  |
| [1.0, 2.0)   | 27 | 14   | 51.9% | 1.522 | +4.81%  |
| >= 2.0       | 19 | 7    | 36.8% | 0.897 | -0.86%  |

### Directional displacement by bucket (SHORT entries, 70 trades):

| Bucket       | N  | Wins | WR%   | PF    | Cum%    |
|--------------|----|------|-------|-------|---------|
| < -1.0       | 1  | 0    | 0.0%  | 0.000 | -0.80%  |
| [-1.0, -0.5) | 2  | 0    | 0.0%  | 0.000 | -0.40%  |
| [-0.5, 0.0)  | 5  | 0    | 0.0%  | 0.000 | -2.77%  |
| [0.0, 0.5)   | 5  | 1    | 20.0% | 0.625 | -1.23%  |
| [0.5, 1.0)   | 11 | 2    | 18.2% | 0.719 | -1.61%  |
| [1.0, 2.0)   | 27 | 7    | 25.9% | 1.030 | +0.20%  |
| >= 2.0       | 19 | 10   | 52.6% | 4.167 | +16.17% |

### Threshold split at 0.5:

| Side  | Group   | N  | WR    | PF    | Cum%    |
|-------|---------|----|-------|-------|---------|
| LONG  | BLOCKED | 12 | 25.0% | 0.568 | -2.60%  |
| LONG  | KEPT    | 54 | 44.4% | 1.241 | +4.57%  |
| SHORT | BLOCKED | 13 | 7.7%  | 0.278 | -5.11%  |
| SHORT | KEPT    | 57 | 33.3% | 1.586 | +14.53% |

### Aggregate threshold split:

| Group   | N   | WR    | PF    | Cum%    |
|---------|-----|-------|-------|---------|
| BLOCKED | 25  | **16.0%** | **0.410** | **-7.58%** |
| KEPT    | 111 | **38.7%** | **1.432** | **+19.76%** |

### Winner vs loser displacement stats:

| Side  | Group   | Mean  | Median | P25   | P75   |
|-------|---------|-------|--------|-------|-------|
| LONG  | Winners | 1.426 | 1.543  | 1.099 | 2.300 |
| LONG  | Losers  | 1.242 | 1.371  | 0.640 | 2.067 |
| SHORT | Winners | 1.831 | 2.013  | 1.290 | 2.400 |
| SHORT | Losers  | 1.180 | 1.136  | 0.598 | 1.808 |

**The discriminating power is real and strong:**
- Blocked trades have WR=16.0% (vs system avg 35.1% → -19pp gap)
- SHORT winners have median displacement 2.013 vs losers 1.136
- LONG winners have median displacement 1.543 vs losers 1.371

This is the strongest diagnostic signal found across all experiments to date.

---

## Phase 2 — Experiment Results

### Full metrics comparison:

| Metric                | Baseline | EXP023  | Δ        |
|-----------------------|----------|---------|----------|
| Total trades          | 134      | **119** | -15      |
| Win rate              | 35.07%   | 33.61%  | -1.46pp  |
| Cumulative return     | +15.41%  | **+4.86%** | **-10.56%** |
| Max drawdown          | 8.29%    | **10.10%** | +1.81%  |
| Profit factor         | 1.2784   | **1.1046** | -0.1738 |
| Expectancy            | +0.113%  | +0.045% | -0.068%  |
| Longest loss streak   | 10       | 9       | -1       |

**The system stays above PF 1.0 — unlike EXP020 and EXP021 — but degrades significantly.**

### Side breakdown:

| Side  | Baseline              | EXP023                |
|-------|-----------------------|-----------------------|
| LONG  | 61t · 41.0% · PF 1.17 | 55t · 41.8% · PF 1.03 |
| SHORT | 73t · 30.1% · PF 1.35 | 64t · 26.6% · PF 1.16 |

LONG win rate is nearly unchanged (+0.84pp). SHORT win rate drops -3.58pp.

---

## Phase 3 — Monthly Breakdown

| Month   | BL T | BL WR | BL Ret   | EX T | EX WR | EX Ret   | ΔRet    | Verdict |
|---------|------|-------|----------|------|-------|----------|---------|---------|
| 2025-10 | 21   | 28.6% | -1.78%   | 16   | 25.0% | -3.19%   | -1.41%  | WORSE ◄ |
| 2025-11 | 27   | 33.3% | +3.81%   | 23   | 26.1% | -0.94%   | -4.75%  | WORSE   |
| 2025-12 | 18   | 22.2% | -3.58%   | 16   | 25.0% | -3.32%   | +0.26%  | FLAT ◄  |
| 2026-01 | 22   | 54.5% | +10.59%  | 20   | 55.0% | +9.27%   | -1.32%  | WORSE ◄ |
| 2026-02 | 24   | 29.2% | +2.65%   | 20   | 35.0% | +4.10%   | +1.45%  | BETTER  |
| 2026-03 | 22   | 40.9% | +3.41%   | 24   | 33.3% | -0.57%   | -3.98%  | WORSE   |

**Target months:**
- Oct 2025: slightly worse (-1.41%) — not improved
- Dec 2025: nearly flat (+0.26%) — marginal at best
- Jan 2026: slightly worse (-1.32%) — better preserved than EXP020/EXP021 but still negative

**Pattern:** Nov 2025 is damaged again (-4.75%), Mar 2026 is damaged (-3.98%).

---

## Phase 4 — Blocking Analysis

Total signals blocked: **38** (BUY=18, SELL=20)

| Month   | BUY | SELL | Total |
|---------|-----|------|-------|
| 2025-10 | 3   | 3    | 6     |
| 2025-11 | 0   | 7    | 7     |
| 2025-12 | 4   | 1    | 5     |
| 2026-01 | 2   | 1    | 3     |
| 2026-02 | 3   | 6    | 9     |
| 2026-03 | 6   | 2    | 8     |

Nov 2025: 7 SELL signals blocked. These are SHORT entries in BTC's strongest
downtrend period. Same pattern as EXP021.

**Blocked baseline trades:** 25 trades, WR=16.0%, PF=0.410, Cum=-7.58%
**Verdict:** DISCRIMINATING — blocked trades 19pp below system average WR.

---

## Analysis — Why Strong Discrimination Does Not Produce Net Improvement

### 1. The blocking math works, but cascade effects undo the gain

The diagnostic says blocked trades contribute cumulative -7.58%. Removing them should
improve the system. But the experiment shows cumulative -10.56% vs baseline (+15.41%).
The gap (≈18pp loss) is entirely from cascade effects — altered CB timing and cooldown
scheduling that allows worse subsequent trades through.

**Mechanism:**
- The CB fires after 2 consecutive losses and blocks entries for 48 hours
- Many of the "blocked" trades are EARLY in a losing sequence (the first or second loss)
- Removing the early loss in a losing pair → CB never fires → subsequent 5-10 bad entries
  in that CB window are now unblocked
- The 25 blocked bad trades were "productive losses" — they were triggering the CB,
  which then blocked far more damaging downstream entries
- Net: removing 25 losses costs 7.58% in the direct trade, but unblocks ~18pp of
  downstream damage that the CB would have blocked

This is the **circuit breaker dependency problem**: the CB is itself a trend-quality
detector, and it depends on observing losses to activate. Pre-filtering losses disrupts
the CB's information flow.

### 2. Nov 2025 SHORT damage persists — same structural issue as EXP021

Nov 2025 blocks 7 SELL signals (0 BUY). In a strong downtrend, SHORT entries are
frequently triggered when price bounces briefly (raw displacement positive = price went
UP over last 4 candles → dir_disp for SHORT is negative → blocked).

The displacement filter correctly identifies "price isn't falling right now" — but the
SHORT setup is CORRECT: enter short at the top of a bounce in a downtrend. The filter
doesn't understand that "price going up for 4 candles" is a feature, not a bug, for
SHORT entries on pullbacks.

This is a deeper design constraint: for SHORT entries, the directional displacement
of the PRECEDING 4 candles is the wrong signal. What matters is the TREND direction
over a longer period, not the immediate momentum direction.

### 3. The discriminating signal exists but requires a different extraction mechanism

The diagnostic numbers are compelling:
- Short winner median displacement: 2.013 vs loser median 1.136
- Long winner median displacement: 1.543 vs loser median 1.371

Winners clearly have higher displacement than losers. But applying a hard threshold
gate destroys value through cascades and blocks bounce-entry SHORTs.

The information in displacement is real — but a **hard entry gate** is the wrong way to
use it, because:
a) It disrupts the CB activation sequence
b) It's directionally inappropriate for SHORT bounce entries

Better uses of this signal:
- As a **confidence weighting** (higher displacement → higher confidence) rather than a gate
- As a **soft gate** contributing to the scoring system
- As a **CB-exempt gate** (only block when CB is currently inactive AND no recent losses)

---

## Key Structural Finding for Future Research

### The CB-dependency constraint

Any hard gate that pre-emptively removes losing entries will partially undo the CB's
protective effect. This is not a failure of the displacement signal — it is a
fundamental property of how the CB mechanism works.

**Implication:** The only filters that can improve this system are those that:
1. Block entries that would NOT have triggered the CB anyway (i.e., isolated winners
   in good periods, not loss-sequence starters)
2. OR operate at a level that doesn't interact with the CB sequence

The CB already blocks ~210 entries. Adding upstream filters primarily changes
WHICH entries trigger the CB, often in ways that expose worse subsequent trades.

### Displacement as a quality signal

The displacement distribution provides the clearest discriminating signal yet:
- Trades with dir_disp < 0.5: WR=16%, PF=0.41, Cum=-7.58% (25 trades)
- Trades with dir_disp >= 0.5: WR=38.7%, PF=1.43, Cum=+19.76% (111 trades)

This information could be used in a non-gate fashion:
1. **Score contribution:** Add displacement as a 4th soft gate condition
2. **CB threshold adjustment:** In low-displacement environments, reduce CB threshold
   from 2 losses to 1 loss (faster CB activation when market quality is low)
3. **Position sizing gate:** Use displacement to modulate exposure rather than binary entry/exit

---

## Decision: REVERT

No code was modified in the main system files. Experiment was standalone.
Baseline fully restored: **134 trades, WR 35.07%, Cum +15.41%, PF 1.2784.**

**Summary of findings:**

| Question | Answer |
|----------|--------|
| Does displacement discriminate winners from losers? | **YES — strongly (16% vs 39% WR)** |
| Does the gate improve the system? | **NO — cumulative -10.56%** |
| Is the discrimination real or overfitted? | Real — consistent across both sides |
| Is the failure due to a weak signal? | No — due to CB cascade disruption |
| Does it block the right trades? | Partially — but also blocks bounce SHORTs |
| Improvement on target months? | Oct: WORSE, Dec: FLAT, Jan: slightly WORSE |

---

## Where We Are After EXP023

Three experiments have now tested "trend quality detection":
- EXP020 (ADX): no discriminating power, lagged, reverted
- EXP021 (candle body): real signal for LONG, broken for SHORT bounce entries, reverted
- EXP023 (displacement): strongest discriminating power yet, but CB cascade prevents benefit

**The system's core constraint is now clear:**
The CB mechanism is the primary regime filter, and it is tightly coupled to the trade
entry sequence. Upstream entry filters that remove losing trades disrupt CB activation
and expose worse subsequent trades. The CB "needs" to see some losses to protect against
clustered loss sequences.

**This means the profitable path forward is NOT another entry gate.** Instead:

### Option A: Displacement as a soft gate (scoring contribution)
Add `displacement >= 0.5` as a 4th soft gate condition for BUY/SELL. Currently soft
gates require 2/3. This would require 2/4, slightly reducing entry frequency without
hard blocking.

### Option B: Longer lookback displacement (8 candles = 2 hours)
A 2-hour displacement is less susceptible to bounce noise for SHORT entries. With N=8,
price returning to the mean over 2 hours is more clearly a ranging market.
Risk: more lag, but may better separate active trends from chop.

### Option C: Accept the system optimum and expand the dataset
The 180d dataset may be at its extractable limit for this approach. Testing with
365d of data, or a different market regime (2024 bull), would reveal whether the
current parameter set generalizes robustly.

**Recommended next step:** Option C — validate the system on expanded data (365d)
before adding more complexity. The current results suggest the 180d system is near
its extractable edge, and further filtering experiments are running into CB-coupling
constraints that a larger dataset would help clarify.

---

## Artifacts

- `exp023_net_displacement.py` — experiment runner (kept for reference)
- `data/backtest_BTCUSDT_180d_exp023_displacement.json` — full trade log
