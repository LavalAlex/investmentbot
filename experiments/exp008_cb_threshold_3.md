# Experiment 008 — Raise Circuit Breaker Loss Threshold from 2 to 3

**Date:** 2026-03-23
**Status:** REVERTED

---

## Hypothesis

The 2-loss circuit breaker fires too frequently due to statistical variance at the system's observed
~40% win rate. P(2 consecutive losses) = 0.6² = 36% — nearly a coin flip. This means the CB
regularly pauses trading during normal loss streaks, blocking profitable entries especially during
sustained bearish trends where the first 1–2 short attempts whipsaw before the real move.

Raising the threshold to 3 consecutive losses should reduce CB interference with trade sequencing,
allow more trades through during trending periods, and improve the SHORT side which bears the most
cost from CB-induced opportunity loss.

**Change:** `CB_LOSS_THRESHOLD = 2` → `CB_LOSS_THRESHOLD = 3`
**All other parameters:** unchanged
**Expected improvement:** More trades in trending conditions, higher SHORT PF, better total return

---

## Results

| Metric | v2 Baseline (CB=2) | Exp 008 (CB=3) | Δ |
|--------|--------------------|----------------|---|
| Total trades | 145 | 171 | +26 |
| Win rate | 40.00% | 38.01% | -2.0pp |
| Cumulative return | +2.37% | -6.75% | -9.12pp |
| Max drawdown | — | 13.50% | — |
| Profit factor | 1.0513 | 0.9115 | -0.14 |
| Expectancy | +0.016% | -0.037% | negative |
| Longest loss streak | — | 10 | — |
| CB events | 34 | 23 | -11 |
| CB blocked entries | 234 | 158 | -76 |
| LONG trades | 61 | 64 | +3 |
| LONG WR | 40.98% | 37.50% | -3.5pp |
| LONG PF | 1.1130 | 0.9377 | -0.18 |
| LONG cum return | +2.39% | -1.83% | -4.2pp |
| SHORT trades | 84 | 107 | +23 |
| SHORT WR | 39.29% | 38.32% | -1.0pp |
| SHORT PF | 1.0082 | 0.8967 | -0.11 |
| SHORT cum return | -0.02% | -5.02% | -5.0pp |

---

## Analysis

The hypothesis was wrong. The CB at threshold=2 was NOT over-firing from variance noise — it was
blocking genuinely bad trades.

The 23 extra SHORT trades that came through with the looser threshold were net negative. The Nov-Feb
period (choppy bear market with high volatility) is the dominant regime in this dataset. In that
environment, getting stopped out of 2 shorts quickly usually means the market is whipping around,
not that the trades were bad timing. The additional trades exposed the system to more whipsaw losses.

CB events dropped from 34 to 23, but each new CB activation happened later (after 3 losses instead
of 2), meaning more damage had already been done before the pause kicked in.

The SHORT side went from -0.02% to -5.02% — the extra 23 SHORT trades collectively destroyed value.
The LONG side also degraded slightly, confirming the CB serves both directions.

**Conclusion:** CB at threshold=2 is functioning correctly. The circuit breaker is protective, not
a drag. Do not raise this threshold.

---

## Decision: REVERT

Reverted `CB_LOSS_THRESHOLD` to 2. No other code changes.

---

## Insight for Future Research

The CB is not the constraint on system performance. The SHORT side's weakness (PF 1.0082) comes
from signal quality, not from opportunity loss due to excessive CB pauses. Future improvement must
focus on either:
1. Exit logic for shorts (TP/SL/BE asymmetry between long and short)
2. A more selective entry criterion that reduces the number of "noise shorts"
3. Understanding why the Nov-Feb regime generates so many losing short entries despite bearish conditions
