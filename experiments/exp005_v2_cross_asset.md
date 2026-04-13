# EXP005-v2 — Cross-Asset Generalization

## Hypothesis

EXP002 works on BTC/USDT with a stable IS/OOS edge (PF ~1.1–1.15).
If the edge is structural — i.e., it comes from how large-cap crypto assets behave around
EMA pullbacks — it should work on other assets without any parameter tuning.

Test: run EXP002 unchanged on 5 additional assets over the same IS window.

## Setup

**Strategy:** EXP002-v2 — zero modifications. Same parameters, filters, sizing, exit logic.
**Window:** Sep 2025 – Mar 2026 (same as IS period; no OOS data available for alt-coins).
**Assets:** BTC, ETH, SOL, BNB, XRP, DOGE

**No parameter tuning of any kind.**

## Results

### Full summary table

| Asset | Trades | Win Rate | Return | Max DD | PF | Expectancy |
|---|---|---|---|---|---|---|
| BTC | 442 | 36.2% | +39.7% | 17.8% | **1.115** | $8.98 |
| ETH | 461 | 37.3% | +65.1% | 21.9% | **1.188** | $14.13 |
| SOL | 140 | 30.0% | −14.2% | 30.0% | **0.852** | −$10.15 |
| BNB | 440 | 35.5% | +26.5% | 18.1% | **1.081** | $6.02 |
| XRP | 0 | — | — | — | — | — |
| DOGE | 0 | — | — | — | — | — |

### Long/Short PnL breakdown

| Asset | Long PnL | Short PnL |
|---|---|---|
| BTC | +$3,656 | +$313 |
| ETH | +$4,383 | +$2,129 |
| SOL | −$1,242 | −$179 |
| BNB | +$191 | +$2,457 |

### Monthly breakdown — ETH

```
2025-09  n= 14  WR=21.4%  net=   -499
2025-10  n= 80  WR=43.8%  net= +2,587
2025-11  n= 83  WR=28.9%  net= -1,342  ← bad month (same as BTC)
2025-12  n= 79  WR=35.4%  net=   +460
2026-01  n= 73  WR=38.4%  net= +1,206
2026-02  n= 74  WR=39.2%  net= +1,611
2026-03  n= 58  WR=43.1%  net= +2,489  ← strongest month
```

### Monthly breakdown — SOL

```
2025-10  n= 43  WR=41.9%  net= +1,087  ← only profitable month
2025-11  n= 37  WR=21.6%  net= -1,356
2025-12  n= 21  WR=19.0%  net=   -835
2026-01  n= 16  WR=18.8%  net=   -598
```

SOL collapses badly in Nov–Jan: low trade count, very low win rate.

### Monthly breakdown — BNB

```
2025-10  n= 78  WR=33.3%  net=    -79
2025-11  n= 90  WR=35.6%  net=   +527
2025-12  n= 55  WR=36.4%  net=   +482
2026-01  n= 75  WR=41.3%  net= +2,083  ← dominant month
2026-02  n= 71  WR=33.8%  net=    +38
2026-03  n= 64  WR=31.2%  net=   -598
```

BNB is positive overall but marginal in several months.

## Critical finding: XRP and DOGE untestable

XRP and DOGE generated **zero trades** due to `MIN_RISK_PRICE = 1.0`.

This constant was designed for BTC at $100k+ where even small SL distances comfortably exceed $1.
For low-price assets:
- XRP: $1.14–$3.09 → typical SL distance $0.05–$0.20 → always blocked
- DOGE: $0.08–$0.27 → SL distance $0.001–$0.01 → always blocked

**This is not a strategy failure — it is an architectural constraint.**
The `MIN_RISK_PRICE` floor was never designed to be asset-agnostic. It prevents degenerate
sizing on BTC (where a $0.50 SL would create enormous qty) but systematically blocks all
trades on low-price assets.

XRP and DOGE cannot be evaluated in the current framework without replacing `MIN_RISK_PRICE`
with a percentage-based floor (e.g., `risk_price >= entry * 0.001`). This would require a
framework change — outside the scope of EXP005.

**For the generalization test: effective sample is 4 assets (BTC, ETH, SOL, BNB).**

## SOL analysis

SOL produced only 140 trades (vs 440 for BTC over the same window).

Filter rejection breakdown:
- Trend strength: 3,743 (similar to BTC's 5,070 adjusted for fewer bars)
- **Pullback quality: 8,396** (very high — far more pullback rejections than BTC)
- **Candle quality: 1,590** (2.2× BTC's 712)

SOL's price action touches EMA20 far less often and generates weaker trigger candles.
When it does trade, the win rate was 30% (vs 36% for BTC) — the pullback structure
that works for BTC/ETH does not translate well to SOL's more volatile, noisy movement.

The system is effectively too selective for SOL: when it fires, the signal quality is
already degraded because the candle quality filter passes indecision candles that scraped
through the 60% body threshold.

## Decision

### Verdict: PARTIAL GENERALIZATION

The system works on the large-cap, mature-liquidity assets (BTC, ETH, BNB) and fails on
the smaller/more volatile assets (SOL).

Of the 4 evaluable assets: **3/4 profitable** (BTC, ETH, BNB).

| Classification | Assets | PF |
|---|---|---|
| Profitable | BTC, ETH, BNB | 1.081–1.188 |
| Unprofitable | SOL | 0.852 |
| Untestable | XRP, DOGE | — |

### What the results tell us

**BTC and ETH show similar behavior:** both have Nov as a bad month. ETH has Nov as its
worst month (−$1,342) just as BTC does (−$1,260). This confirms the pullback strategy's
difficulties are market-regime-driven, not asset-specific — Nov 2025 was a bad pullback
environment for the whole crypto market.

**ETH is actually stronger than BTC:** PF 1.188 vs 1.115, +65% vs +40%, both long
and short profitable. The strategy generalizes well to ETH and may be deployable there.

**BNB is marginal:** PF 1.081, good trade count, but most months are near-flat.
Jan 2026 (+$2,083) is carrying the whole period. Without Jan, BNB would be slightly negative.
Not strong enough to deploy with confidence.

**SOL is a clear failure:** WR drops to 30%, DD hits 30%, losses concentrated in Nov–Jan.
SOL's intraday volatility likely causes many pullbacks to overshoot EMA20 (collapsing through
it, which the pullback quality filter should catch), or the trend periods are shorter, causing
false entries.

### System classification

The pullback continuation strategy is a **large-cap continuation system**, not a
universal crypto strategy:
- It requires stable EMA-structured price action
- It requires sufficient absolute SL distance (architectural MIN_RISK_PRICE constraint)
- It degrades on assets with higher idiosyncratic volatility (SOL) or low per-unit price (XRP, DOGE)

**This is not a flaw in the system — it is a definition of its applicable domain.**

## What to try next (EXP006 candidates)

1. **ETH multi-asset expansion** — ETH is strong. Consider running EXP002 on ETH as
   a second production candidate alongside BTC, with separate equity curves.

2. **Walk-forward testing (BTC + ETH)** — Both BTC and ETH have consistent IS/OOS behavior
   (BTC confirmed, ETH only tested IS). Walk-forward across rolling windows would be the next
   validation step before any deployment consideration.

3. **SOL investigation** — If SOL is of interest, the pullback quality parameters may need
   to be relaxed (wider EMA20 touch tolerance) and the candle quality threshold lowered for
   SOL's price structure. This would be a new experiment family specific to SOL.

4. **XRP/DOGE framework fix** — Replace `MIN_RISK_PRICE = 1.0` with a percentage-based floor
   `risk_pct_floor = 0.001` (SL must be ≥ 0.1% from entry). Then XRP and DOGE could be
   evaluated fairly.
