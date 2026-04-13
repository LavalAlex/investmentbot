# Experiment Session Summary — 2026-03-24

## Objective
Improve Profit Factor from ~1.28 toward 1.30–1.35 through controlled single-parameter
experiments without breaking the existing edge.

## Confirmed Current Baseline
After exp012 (SHORT TP = 2.2%), the approved baseline is:

| Metric | Value |
|--------|-------|
| Total trades | 134 |
| Win rate | 35.07% |
| Cumulative return | +15.41% |
| Max drawdown | 8.29% |
| Profit factor | 1.2784 |
| Expectancy | +0.113% |
| LONG: trades/WR/PF | 61 / 40.98% / 1.1688 |
| SHORT: trades/WR/PF | 73 / 30.14% / 1.3516 |
| CB events / blocked | 35 / 210 |

**Parameters:** SL=0.6% · LONG TP=1.2% · SHORT TP=2.2% · BE=0.8% · CB=2 losses/48h

---

## Experiments This Session

### Exp 013 — BE trigger 0.8% → 0.6% — REVERTED
- Result: PF collapsed to 0.969, return -2.04%
- Reason: 0.6% is within 15m noise range; converted TP winners to BE stops

### Exp 014 — CB pause 48h → 24h — REVERTED
- Result: PF 1.04, return +1.77%, max DD 13.1%
- Reason: trades in hours 24-48 of CB pause are net-negative; regime persists

### Exp 015 — SHORT regime filter (1h close > EMA200) — REVERTED
- Result: PF 1.246, return +13.38%
- Reason: 1h EMA200 is an 8-day MA; blocks early-bear SHORTs at ATH (most profitable)

### Exp 016 — BE stops exempt from CB counter — REVERTED
- Result: PF 1.015, return +0.19%, max DD 14.6%
- Reason: regime is still bad after BE sequences; blocked trades are genuinely bad

### Exp 017 — Block SHORT in low-vol 1h environments — REVERTED
- Result: PF 1.029, SHORT PF 0.947, return +0.90%
- Reason: SHORTs work in any volatility regime when trend is down; filter too broad

### Exp 018 — SELL hard filter 1h RSI < 50 → < 45 — REVERTED
- Result: PF 1.052, lost 6 SHORT wins, return +2.18%
- Reason: 1h RSI 45-49 SHORTs have enough momentum to reach 2.2% TP

### Asymmetric cooldown (TP=15min, loss=45min) — REVERTED (in-process test)
- Result: PF 1.14, return +7.19%, max DD 12.2%
- Reason: re-entering quickly after a TP win leads to net-negative trades

---

## Key Structural Findings

### 1. All protection mechanisms are tightly calibrated
The CB threshold (2 losses), CB pause (48h), BE trigger (0.8%), cooldown (45min),
and regime filter (LONG only) are all at well-calibrated values. Any relaxation
admits net-negative trades. Any tightening cuts net-positive trades.

### 2. The circuit breaker is consistently protective
Across 4 experiments that tried to reduce CB effectiveness:
- Raising CB threshold (exp008): worse
- Reducing CB pause (exp014): worse
- Exempting BE stops (exp016): worse
The 210 CB-blocked entries are collectively net-negative regardless of CB mechanism.

### 3. Entry filter thresholds are non-binding or correctly set
- 1h RSI > 50 for BUY: equivalent to > 55 in practice (non-binding)
- 1h RSI < 50 for SELL: meaningful gate, cannot be tightened to < 45
- SHORT TP 2.2%: confirmed optimal (2.3% still worse with current data)

### 4. The system is at a local optimum for the 180-day dataset
After 10 experiments (008-018), every direction of parameter change has been reverted.
The baseline is a stable local optimum. The gap between current PF (1.28) and target
(1.30-1.35) may require:
- Longer training data to discover patterns not visible in 180 days
- Signal engine improvements distinguishing winner/loser SHORT setups
- Multi-variable analysis (which features correlate with winning SHORTs?)

---

## Analysis of What Distinguishes Winning SHORTs (22) from Losing SHORTs (51)

From the 73 SHORT trades:
- 22 TP hits: strong directional momentum, 2.2% sustained decline
- 18 BE stops: went 0.8% favorable, then reversed to entry
- 33 regular SL hits: price moved 0.6% against the trade, full SL

The winning SHORTs are concentrated in Nov 2025 (8 wins) and Jan-Feb 2026 (11 wins).
The losing months are Oct (7 losses in 8 trades) and Dec (6 losses in 6 trades).

What distinguishes them:
- Oct 2025: BTC near ATH, brief local weakness → failed reversal
- Dec 2025: Post-crash consolidation sideways → no momentum for 2.2% TP
- Nov/Feb: Strong directional bear moves → clean 2.2% drops

**The core insight:** SHORT works when BTC is in an active bear trend with momentum
(big drops), not when it's at a local high (Oct ATH) or consolidating (Dec sideways).
The existing filters largely capture this, but ~12 "regime mismatch" SHORTs still get
through. Identifying these would require a structural market-phase classifier, which
goes beyond single-parameter tuning.

---

## Code Changes Made This Session (Permanent, Harmless)

1. `backtest.py`: Added `REGIME_FILTER_SHORT = False` constant with documentation
2. `backtest.py`: Added `BLOCK_SHORT_LOW_VOL = False` constant with documentation
3. `backtest.py`: Added tracking for `regime_blocked_shorts` and `low_vol_blocked_shorts`
4. `backtest.py`: Added print lines for the new counters
5. `backtest.py`: `save_results` now includes `regime_filter_short` parameter

These additions improve observability and leave infrastructure for future SHORT filtering
experiments without changing any behavior (flags default to False).

---

## Conclusion

**Baseline is maintained at PF 1.2784, return +15.41%, max DD 8.29%.**

The target of PF > 1.30-1.35 is not achievable through isolated parameter changes
on the current 180-day dataset. The system appears to be at or near its parameter
optimum for this training period.

**Next recommended approaches:**
1. Gather more data (365 days) to find patterns robust across multiple market cycles
2. Analyze the feature vectors of all 73 SHORTs to find a discriminating pattern
   between winners and losers (ML-assisted analysis, not parameter tuning)
3. Test the strategy on different market regimes (2024 bull market) to validate
   that current settings are not overfit to a single 6-month bear period
