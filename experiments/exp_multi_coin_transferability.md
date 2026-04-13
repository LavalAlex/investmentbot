# Multi-Coin Transferability Experiment

**Date**: 2026-03-25 01:02 UTC  
**Strategy**: BTC/USDT 15m baseline (parameters unchanged)  
**Data window**: 180d of 15m + 200d of 1h (EMA200 warmup)  
**Timeframe**: 15m  

## Objective

Measure whether the approved BTC baseline strategy is transferable to other
major liquid coins — without changing any parameters.
This is a selection step, not an optimisation step.

## Strategy Parameters

| Parameter | Value |
|-----------|-------|
| Stop Loss | 0.6% |
| Long Take Profit | 1.2% |
| Short Take Profit | 2.2% |
| Break-Even Trigger | 0.8% |
| Fee (round-trip) | 0.2% |
| Circuit Breaker | 2 consecutive losses → 48h pause |
| Regime Filter (LONG) | Enabled |

## Approval Criteria

A coin is **APPROVED** only if **all three** checks pass:

1. Profit Factor > 1.05
2. Cumulative Return > 0%
3. Return / Max Drawdown >= 0.5

---

## Results Summary

| Symbol | Verdict | Trades | Win Rate | Cum Return | Max DD | Profit Factor | Expectancy | Loss Streak |
|--------|---------|--------|----------|------------|--------|---------------|------------|-------------|
| BTC/USDT | ✅ APPROVE | 134 | 35.07% | +15.4125% | 8.2937% | 1.2784 | +0.1128% | 10 |
| ETH/USDT | ❌ REJECT | 123 | 17.89% | -26.9697% | 28.4662% | 0.5143 | -0.2513% | 21 |
| BNB/USDT | ❌ REJECT | 136 | 25.00% | -14.1336% | 21.3268% | 0.7862 | -0.1058% | 10 |
| SOL/USDT | ❌ REJECT | 120 | 15.83% | -36.3506% | 36.5881% | 0.4068 | -0.3712% | 26 |
| XRP/USDT | ❌ REJECT | 125 | 15.20% | -36.2131% | 36.3566% | 0.3690 | -0.3557% | 22 |
| DOGE/USDT | ❌ REJECT | 141 | 21.28% | -24.2433% | 24.2433% | 0.6356 | -0.1916% | 19 |

---

## Long / Short Side Breakdown

| Symbol | Long Trades | Long WR | Long Return | Long PF | Short Trades | Short WR | Short Return | Short PF |
|--------|-------------|---------|-------------|---------|--------------|----------|--------------|----------|
| BTC/USDT | 61 | 40.98% | +3.5216% | 1.1688 | 73 | 30.14% | +11.4864% | 1.3516 |
| ETH/USDT | 59 | 20.34% | -15.3865% | 0.4352 | 64 | 15.62% | -13.6895% | 0.5817 |
| BNB/USDT | 67 | 29.85% | -10.0584% | 0.6582 | 69 | 20.29% | -4.5309% | 0.8915 |
| SOL/USDT | 52 | 17.31% | -17.4086% | 0.3507 | 68 | 14.71% | -22.9345% | 0.4424 |
| XRP/USDT | 44 | 27.27% | -10.3048% | 0.5281 | 81 | 8.64% | -28.8848% | 0.2932 |
| DOGE/USDT | 50 | 30.00% | -7.9887% | 0.6660 | 91 | 16.48% | -17.6658% | 0.6207 |

---

## Monthly Returns by Coin

### BTC/USDT — APPROVE

| Month | Trades | Wins | Losses | Return |
|-------|--------|------|--------|--------|
| 2025-10 | 21 | 6 | 15 | -1.7758% |
| 2025-11 | 27 | 9 | 18 | +3.8050% |
| 2025-12 | 18 | 4 | 14 | -3.5811% |
| 2026-01 | 22 | 12 | 10 | +10.5895% |
| 2026-02 | 24 | 7 | 17 | +2.6509% |
| 2026-03 | 22 | 9 | 13 | +3.4135% |

### ETH/USDT — REJECT

| Month | Trades | Wins | Losses | Return |
|-------|--------|------|--------|--------|
| 2025-09 | 3 | 0 | 3 | -2.3809% |
| 2025-10 | 21 | 6 | 15 | +0.2121% |
| 2025-11 | 20 | 4 | 16 | -2.1310% |
| 2025-12 | 22 | 5 | 17 | -4.0524% |
| 2026-01 | 25 | 5 | 20 | -7.0673% |
| 2026-02 | 13 | 1 | 12 | -5.1110% |
| 2026-03 | 19 | 1 | 18 | -9.8462% |

### BNB/USDT — REJECT

| Month | Trades | Wins | Losses | Return |
|-------|--------|------|--------|--------|
| 2025-09 | 4 | 2 | 2 | +0.9915% |
| 2025-10 | 30 | 9 | 21 | +1.7376% |
| 2025-11 | 21 | 5 | 16 | -4.1127% |
| 2025-12 | 21 | 4 | 17 | -3.0965% |
| 2026-01 | 21 | 5 | 16 | -3.0637% |
| 2026-02 | 20 | 4 | 16 | -5.0869% |
| 2026-03 | 19 | 5 | 14 | -2.2440% |

### SOL/USDT — REJECT

| Month | Trades | Wins | Losses | Return |
|-------|--------|------|--------|--------|
| 2025-09 | 2 | 0 | 2 | -0.9984% |
| 2025-10 | 18 | 2 | 16 | -7.0469% |
| 2025-11 | 18 | 2 | 16 | -11.9849% |
| 2025-12 | 19 | 0 | 19 | -13.4854% |
| 2026-01 | 25 | 6 | 19 | -5.5626% |
| 2026-02 | 20 | 5 | 15 | -0.9647% |
| 2026-03 | 18 | 4 | 14 | -2.8800% |

### XRP/USDT — REJECT

| Month | Trades | Wins | Losses | Return |
|-------|--------|------|--------|--------|
| 2025-09 | 2 | 0 | 2 | -1.5936% |
| 2025-10 | 20 | 4 | 16 | -6.7015% |
| 2025-11 | 21 | 4 | 17 | -6.9448% |
| 2025-12 | 18 | 0 | 18 | -11.8816% |
| 2026-01 | 24 | 6 | 18 | -2.3890% |
| 2026-02 | 20 | 1 | 19 | -7.9753% |
| 2026-03 | 20 | 4 | 16 | -5.6759% |

### DOGE/USDT — REJECT

| Month | Trades | Wins | Losses | Return |
|-------|--------|------|--------|--------|
| 2025-09 | 4 | 0 | 4 | -2.5761% |
| 2025-10 | 21 | 4 | 17 | -5.1166% |
| 2025-11 | 20 | 2 | 18 | -4.1547% |
| 2025-12 | 21 | 5 | 16 | -0.9708% |
| 2026-01 | 26 | 6 | 20 | -3.3216% |
| 2026-02 | 26 | 8 | 18 | -2.8298% |
| 2026-03 | 23 | 5 | 18 | -8.0887% |

---

## Approved Coins

**1 / 6 coins approved.**

### BTC/USDT

- PASS: profit_factor 1.2784 > 1.05
- PASS: cumulative_return +15.4125% > 0
- PASS: return/drawdown ratio 1.86 >= 0.5 (return=+15.41%, dd=8.29%)

---

## Rejected Coins

**5 / 6 coins rejected.**

### ETH/USDT

**Approval check results:**

- REJECT: profit_factor 0.5143 <= 1.05
- REJECT: cumulative_return -26.9697% <= 0
- REJECT: return/drawdown ratio -0.95 < 0.5 (return=-26.97%, dd=28.47%)

**Likely reasons:**

- Profit factor below 1.0 (0.5143) — gross losses exceed gross gains. The SL/TP asymmetry is not favourable for this coin.
- Win rate very low (17.9%) — the signal scoring model does not align well with this coin's price structure or regime transitions.
- Longest loss streak = 21 — extended drawdown periods suggest the strategy enters in unfavourable regimes for this asset.
- Negative cumulative return (-26.9697%) with 28.47% drawdown — strategy is net-losing on this asset at current parameters.

### BNB/USDT

**Approval check results:**

- REJECT: profit_factor 0.7862 <= 1.05
- REJECT: cumulative_return -14.1336% <= 0
- REJECT: return/drawdown ratio -0.66 < 0.5 (return=-14.13%, dd=21.33%)

**Likely reasons:**

- Profit factor below 1.0 (0.7862) — gross losses exceed gross gains. The SL/TP asymmetry is not favourable for this coin.
- Win rate very low (25.0%) — the signal scoring model does not align well with this coin's price structure or regime transitions.
- Longest loss streak = 10 — extended drawdown periods suggest the strategy enters in unfavourable regimes for this asset.
- Negative cumulative return (-14.1336%) with 21.33% drawdown — strategy is net-losing on this asset at current parameters.

### SOL/USDT

**Approval check results:**

- REJECT: profit_factor 0.4068 <= 1.05
- REJECT: cumulative_return -36.3506% <= 0
- REJECT: return/drawdown ratio -0.99 < 0.5 (return=-36.35%, dd=36.59%)

**Likely reasons:**

- Profit factor below 1.0 (0.4068) — gross losses exceed gross gains. The SL/TP asymmetry is not favourable for this coin.
- Win rate very low (15.8%) — the signal scoring model does not align well with this coin's price structure or regime transitions.
- Longest loss streak = 26 — extended drawdown periods suggest the strategy enters in unfavourable regimes for this asset.
- Negative cumulative return (-36.3506%) with 36.59% drawdown — strategy is net-losing on this asset at current parameters.

### XRP/USDT

**Approval check results:**

- REJECT: profit_factor 0.3690 <= 1.05
- REJECT: cumulative_return -36.2131% <= 0
- REJECT: return/drawdown ratio -1.00 < 0.5 (return=-36.21%, dd=36.36%)

**Likely reasons:**

- Profit factor below 1.0 (0.3690) — gross losses exceed gross gains. The SL/TP asymmetry is not favourable for this coin.
- Win rate very low (15.2%) — the signal scoring model does not align well with this coin's price structure or regime transitions.
- Longest loss streak = 22 — extended drawdown periods suggest the strategy enters in unfavourable regimes for this asset.
- Negative cumulative return (-36.2131%) with 36.36% drawdown — strategy is net-losing on this asset at current parameters.

### DOGE/USDT

**Approval check results:**

- REJECT: profit_factor 0.6356 <= 1.05
- REJECT: cumulative_return -24.2433% <= 0
- REJECT: return/drawdown ratio -1.00 < 0.5 (return=-24.24%, dd=24.24%)

**Likely reasons:**

- Profit factor below 1.0 (0.6356) — gross losses exceed gross gains. The SL/TP asymmetry is not favourable for this coin.
- Win rate very low (21.3%) — the signal scoring model does not align well with this coin's price structure or regime transitions.
- Longest loss streak = 19 — extended drawdown periods suggest the strategy enters in unfavourable regimes for this asset.
- Negative cumulative return (-24.2433%) with 24.24% drawdown — strategy is net-losing on this asset at current parameters.

---

## Conclusions

- **Approved**: 1 / 6 coins
- **Rejected**: 5 / 6 coins

### Interpretation

- Strategy **transferability** is not guaranteed across assets.
- Differences in volatility regime, liquidity, and correlation structure
  cause the same signal logic to perform unevenly.
- **Do not trade rejected coins** with this strategy — results indicate
  structural misalignment, not just bad luck.
- Approved coins should proceed to **paper trading validation** before
  any live consideration.
- No parameter optimisation has been performed — these results reflect
  **raw transferability** of the BTC baseline.

### Next Steps

1. Paper-trade approved coins in parallel with BTC monitoring.
2. Collect 30+ live paper trades per coin before any further decisions.
3. Do not optimise parameters per-coin until paper data is available.
