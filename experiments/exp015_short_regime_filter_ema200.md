# Experiment 015 — SHORT Regime Filter: Block SHORT when 1h close > 1h EMA200

**Date:** 2026-03-24
**Status:** REVERTED

---

## Hypothesis

LONG entries are blocked when 1h close < 1h EMA200 (bearish macro). Symmetrically,
SHORT entries should be blocked when 1h close > 1h EMA200 (bullish macro). In Oct 2025,
BTC was near ATH (112-125k) — SHORTs taken counter-trend in this environment had only
12.5% WR and were the biggest SHORT losers.

**Change:** Added `REGIME_FILTER_SHORT = True` in backtest.py + SHORT block logic
**Expected improvement:** Block counter-trend SHORTs in bull regime, improve SHORT PF

---

## Results

| Metric | Baseline | Exp 015 (SHORT regime filter) | Δ |
|--------|----------|-------------------------------|---|
| Total trades | 134 | 132 | -2 |
| Win rate | 35.07% | 34.85% | -0.22pp |
| Cumulative return | +15.41% | +13.38% | -2.03pp |
| Max drawdown | 8.29% | 8.29% | 0 |
| Profit factor | 1.2784 | 1.2462 | -0.032 |
| SHORT trades | 73 | 71 | -2 |
| SHORT WR | 30.14% | 29.58% | -0.56pp |
| SHORT PF | 1.3516 | 1.2981 | -0.054 |
| SHORT regime blocked | 0 | 8 | +8 |

---

## Analysis

The filter blocked 8 SHORT entries and made results worse. The 8 blocked SHORTs were
net contributors to performance.

Root cause: the 1h EMA200 (span=200 1h bars = ~8.3 days) is NOT a macro indicator —
it's a short-term moving average. In a bear market reversal from ATH, the 1h EMA200
lags slightly above current price, meaning the BEST SHORT entries (early in the decline,
near ATH) are blocked while the move is just beginning. Once price crosses below EMA200
(confirming the downtrend), the early momentum is already captured by others.

This is the opposite of the LONG case, where blocking LONGs when price is below EMA200
correctly blocks counter-trend entries in an established downtrend.

REGIME_FILTER_SHORT left in codebase as `False` for future testing with longer MAs.

---

## Decision: REVERT

`REGIME_FILTER_SHORT = False`. SHORT entries near ATH tops are legitimately profitable.
