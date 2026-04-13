# Experiment 014 — Reduce Circuit Breaker Pause: 48h → 24h

**Date:** 2026-03-24
**Status:** REVERTED

---

## Hypothesis

The CB fires 35 times over 180 days, blocking 210 entries (avg 6 per event).
With 35 events × 48h = 1680h paused = 39% of trading time blocked, reducing the
pause to 24h would reopen trading in the second half of each pause period.
If those re-opened entries are net positive, performance improves.

**Change:** `CB_PAUSE_HOURS = 48` → `24`
**Expected improvement:** More SHORT trades in trending markets after CB fires

---

## Results

| Metric | Baseline | Exp 014 (CB=24h) | Δ |
|--------|----------|------------------|---|
| Total trades | 134 | 164 | +30 |
| Win rate | 35.07% | 31.71% | -3.4pp |
| Cumulative return | +15.41% | +1.77% | -13.64pp |
| Max drawdown | 8.29% | 13.14% | +4.85pp |
| Profit factor | 1.2784 | 1.0361 | -0.242 |
| CB events | 35 | 46 | +11 |
| CB blocked | 210 | 154 | -56 |
| LONG PF | 1.1688 | 0.9589 | -0.210 |
| SHORT PF | 1.3516 | 1.0803 | -0.271 |

---

## Analysis

The 30 additional trades allowed by the shorter pause are net negative. The market
regime that triggered the CB does not recover in 24 hours — the bad conditions persist
for the full 48h. This is consistent with exp008: reducing CB effectiveness (by either
threshold or duration) allows bad trades into the sequence.

Also, more CB events fire (46 vs 35) because trading restarts at 24h and immediately
triggers another CB — the system enters a ping-pong cycle of CB → re-open → new losses
→ new CB → repeat.

---

## Decision: REVERT

`CB_PAUSE_HOURS` restored to 48. The 48h pause duration is well-calibrated.

---

## Insight for Future Research

The CB pause cannot be reduced without allowing net-negative trades. The 48h pause
correctly captures the typical duration of a bad market regime. Do not test pause
durations below 48h. Future research should focus on SIGNAL quality, not protective
mechanisms (which are all well-calibrated).
