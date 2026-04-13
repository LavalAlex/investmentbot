# Experiment 019 — Time-Based Exit Near TP (TIME_EXIT_NEAR_TP)

**Date:** 2026-04-01
**Status:** REVERT

---

## Hypothesis

Trades that reach near TP (MFE ≥ 80–85% of TP distance) but fail to complete
often reverse to break-even or loss. A time-based exit after X candles (15m) may
capture these profits before momentum decays.

**Rule under test:**

```
if peak_tp_progress >= 0.85 AND candles_since_entry >= X:
    close trade (reason = TIME_EXIT_NEAR_TP)
```

Where `peak_tp_progress` = running max of (favorable move / TP distance) across all
candles since entry. Exit price = open of the candle where rule fires.

---

## Methodology

- BTC/USDT and ETH/USDT, 180d, 15m baseline (same configuration as current system)
- MFE computed by replaying each completed trade candle-by-candle from the OHLCV data
- TIME_EXIT fires only on candles **before** the natural exit candle (SL/TP is checked
  first per simulation logic — TIME_EXIT is unreachable once TP/SL triggers)
- X swept over: 4, 6, 8, 10, 12, 16 candles
- X selection criterion: largest X that still improves PF with ≥ 3 triggers
  (conservative — avoids overfitting to a single small threshold)

---

## Phase 1 — MFE Analysis

### BTC/USDT (134 trades)

| Metric | Value |
|--------|-------|
| Trades with MFE ≥ 80% of TP | **58 (43.3%)** |
| Of those → reached TP | **47 (81.0%)** |
| Of those → did NOT reach TP | **11 (19.0%)** |
| Non-completers' exit reason | STOP_LOSS (100%) |

**Near-TP non-completer time distribution (11 trades):**

| Metric | min | p25 | median | p75 | max | mean |
|--------|-----|-----|--------|-----|-----|------|
| candles_at_mfe | 2 | 6 | 26 | 47 | 76 | 27.4 |
| candles_total | 4 | 8 | 33 | 57 | 81 | 34.1 |
| candles_after_mfe | 0 | 1 | 5 | 10 | 21 | 6.7 |
| peak_tp_progress | 0.840 | — | — | — | 1.321 | 0.923 |

**Distribution of candles_at_mfe (non-completers):**
```
[ 2,  4) :  2  ##
[ 4,  8) :  1  #
[ 8, 10) :  1  #
[10, 15) :  1  #
[20, inf) :  6  ######
```

**TP-completers (near-TP) — candles_total:**
min=2, p25=6, median=12, p75=29, max=115, mean=20.7

### ETH/USDT (123 trades)

| Metric | Value |
|--------|-------|
| Trades with MFE ≥ 80% of TP | **34 (27.6%)** |
| Of those → reached TP | **22 (64.7%)** |
| Of those → did NOT reach TP | **12 (35.3%)** |
| Non-completers' exit reason | STOP_LOSS (100%) |

**Near-TP non-completer time distribution (12 trades):**

| Metric | min | p25 | median | p75 | max | mean |
|--------|-----|-----|--------|-----|-----|------|
| candles_at_mfe | 1 | 4 | 4 | 14 | 17 | 7.2 |
| candles_total | 3 | 6 | 11 | 17 | 36 | 12.0 |
| candles_after_mfe | 0 | 2 | 4 | 6 | 19 | 4.8 |

---

## Phase 2 — X Sweep

### BTC/USDT

| X | WR% | Cum% | DD% | PF | Exp% | #TE | ΔCum |
|---|-----|------|-----|----|------|-----|------|
| 4 | 40.30 | +5.37 | 7.35 | 1.1100 | +0.0434 | 31 | -10.04 |
| 6 | 40.30 | +7.55 | 7.35 | 1.1494 | +0.0590 | 28 | -7.86 |
| 8 | 39.55 | +10.41 | 6.98 | 1.1989 | +0.0788 | 23 | -5.00 |
| 10 | 39.55 | +9.90 | 6.98 | 1.1902 | +0.0754 | 22 | -5.51 |
| 12 | 39.55 | +11.29 | 6.98 | 1.2141 | +0.0848 | 20 | -4.13 |
| 16 | 38.81 | +13.87 | 6.98 | 1.2570 | +0.1022 | 16 | **-1.55** |
| **BL** | **35.07** | **+15.41** | **8.29** | **1.2784** | **+0.1128** | 0 | 0 |

### ETH/USDT

| X | WR% | Cum% | DD% | PF | Exp% | #TE | ΔCum |
|---|-----|------|-----|----|------|-----|------|
| 4 | 25.20 | -26.07 | 26.90 | 0.5193 | -0.2416 | 16 | **+0.90** |
| 6 | 23.58 | -26.93 | 28.38 | 0.5038 | -0.2511 | 13 | +0.04 |
| 8 | 21.95 | -27.23 | 28.55 | 0.5003 | -0.2544 | 11 | -0.26 |
| 10 | 21.95 | -27.19 | 29.14 | 0.5011 | -0.2540 | 9 | -0.22 |
| 12 | 21.14 | -26.52 | 28.43 | 0.5175 | -0.2465 | 7 | +0.45 |
| 16 | 21.14 | -27.02 | 28.54 | 0.5066 | -0.2520 | 7 | -0.05 |
| **BL** | **17.89** | **-26.97** | **28.47** | **0.5143** | **-0.2513** | 0 | 0 |

---

## Phase 3 — Detailed Comparison (Chosen X)

### BTC/USDT — X=16 (best available)

| Metric | Baseline | X=16 | Delta |
|--------|----------|-------|-------|
| Trades | 134 | 134 | — |
| Win rate | 35.07% | 38.81% | +3.74pp |
| Cum return | +15.41% | +13.87% | **-1.55%** |
| Max drawdown | 8.29% | 6.98% | -1.32% |
| Profit factor | 1.2784 | 1.2570 | **-0.0214** |
| Expectancy | +0.1128% | +0.1022% | -0.0106% |
| TIME_EXIT trades | — | 16 | — |

**What the 16 TIME_EXIT trades became without the rule (baseline):**
- TAKE_PROFIT: 11 (68.8%)
- STOP_LOSS: 5 (31.2%)

Avg TIME_EXIT return: **+0.97%** vs baseline avg of same trades: **+1.06%**
→ Per-trade profit reduction: **-0.09%**

### ETH/USDT — X=12 (best conservative)

| Metric | Baseline | X=12 | Delta |
|--------|----------|-------|-------|
| Trades | 123 | 123 | — |
| Win rate | 17.89% | 21.14% | +3.25pp |
| Cum return | -26.97% | -26.52% | **+0.45%** |
| Max drawdown | 28.47% | 28.43% | -0.03% |
| Profit factor | 0.5143 | 0.5175 | **+0.0032** |
| Expectancy | -0.2513% | -0.2465% | +0.0048% |
| TIME_EXIT trades | — | 7 | — |

**What the 7 TIME_EXIT trades became without the rule (baseline):**
- STOP_LOSS: 4 (57.1%)
- TAKE_PROFIT: 3 (42.9%)

Avg TIME_EXIT return: **+0.54%** vs baseline avg: **+0.46%**
→ Per-trade improvement: **+0.08%** (on 7 trades out of 123)

---

## Analysis — Why the Rule Doesn't Work

### 1. The premise is false for BTC

The hypothesis assumed "many trades reach near TP and then fail." The data shows:
- **81% of near-TP BTC trades already reach TP without intervention**
- Only 11 trades (8.2% of all trades) are the actual target
- The TIME_EXIT rule fires on many would-be winners, reducing their profit

### 2. No consistent time threshold

For the 11 BTC non-completers, `candles_at_mfe` ranges from 2 to 76 (median 26).
There is no cluster, no inflection point, no natural X. Any threshold X will either
fire too rarely (missing targets) or fire too often (catching winners).

**This rules out data-driven X calibration for BTC.**

### 3. The rule fires too late and on the wrong trades

At X=16 (least harmful for BTC): avg MFE TP-progress when TIME_EXIT fires = 107%.
These trades had already pushed THROUGH TP territory on some candle. The original
backtest TP exit captures those moments intracandle at TP price. TIME_EXIT fires later
at the open of a subsequent candle — at a worse price.

### 4. ETH shows weak positive signal but insufficient weight

ETH near-TP failures are faster (median 4 candles at MFE) and more frequent (35%).
X=12 yields +0.45% cumulative improvement and +0.003 PF on 7 trades out of 123.
This is statistically too thin (n=7) to justify a permanent system rule.
The improvement does not transfer to BTC, indicating regime or asset specificity.

---

## Decision: REVERT

**BTC: REVERT** — cumulative return reduced at all X values; PF reduced; rule fires predominantly on would-be winners.

**ETH: CONDITIONAL** — marginal improvement (+0.45% cum, +0.003 PF) on very few triggers (7 trades). Insufficient statistical weight for a permanent rule.

**Combined decision: REVERT** — the rule is not beneficial on the primary symbol (BTC)
and shows only noise-level improvement on ETH. The hypothesis was not supported by data.

---

## Root Cause Assessment

The problem the rule was meant to solve — "system identifies direction correctly but fails
to capture profits" — is not a TIMING problem. It is an SL placement problem.

Evidence:
- All 11 BTC non-completers exited as STOP_LOSS (not signal reversal)
- The break-even trigger is already in place (+0.8% trigger → SL moves to entry)
- Many near-TP failures are trades where: price reached 85%+ of TP, then reversed to
  break-even SL, meaning the BE stop was already doing its job (protecting capital)

What actually happens:
```
Entry → price moves up toward TP → BE stop activates → price reverses → exits at BE
```
This is CORRECT behavior. The system is protecting capital, not losing it.
The 11 non-completers are NOT failures — they are capital-protected exits.

---

## Insight for Future Research

If the goal is to capture more unrealized profit that the system generates:

1. **TP extension on strong momentum**: If price is near TP AND momentum is still strong
   (e.g., 1h RSI rising, volume expanding), consider trailing the TP slightly rather than
   exiting on time. The opposite of TIME_EXIT.

2. **Partial close at 85% TP**: Close half the position at 85% TP, trail the stop on the
   remaining half. Reduces risk of reversal without abandoning upside.

3. **Dynamic TP based on ATR**: If ATR expands after entry, extend TP proportionally.
   May capture breakout moves that currently stop at 1.2%.

4. **Focus on SHORT failures**: BTC SHORT win rate (30%) is lower than LONG (41%). The
   short-duration SHORT failures are more likely to be the pattern described in the
   hypothesis. Separate analysis may be warranted.

The TIME_EXIT concept in its current form is not the right tool.

---

## Artifacts

- `exp019_analysis.py` — fast replay-based MFE analysis script
- `exp019_time_exit_near_tp.py` — full re-simulation script (run separately)
