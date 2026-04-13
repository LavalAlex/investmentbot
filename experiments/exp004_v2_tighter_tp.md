# EXP004-v2 — Tighter TP (1.5R vs 2R)

## Hypothesis

The 2:1 R:R ratio may be too demanding for this pullback system.
Lifecycle analysis showed:
- ~96% of TP trades experience an adverse move before recovering to 2R
- A meaningful proportion of SL trades reach 1.5R before reversing to stop out
- Lowering TP to 1.5R should convert some losing trades to winners, increasing win rate
  enough to offset the lower per-trade reward

This is a pure exit parameter change. Entry logic, filters, and sizing are identical to EXP002.

## Simulation (pre-implementation, using EXP002 trade data)

Re-simulated EXP002 trades at TP=1.5R by scanning 15m bars bar-by-bar per trade.

**IS prediction:**
- 41 SL trades converted to TP (gain +82R total)
- 160 TP trades earn 1.5R instead of 2R (cost −80R total)
- Net change: +22.5R — modest improvement expected

**OOS prediction:**
- 24 SL trades converted to TP (gain +48R total)
- 153 TP trades earn 1.5R instead of 2R (cost −76.5R total)
- Net change: −14R — regression expected

The IS/OOS asymmetry in conversion count (41 vs 24) was already a warning sign before
implementation. The cost of reducing existing TP trades is symmetric (~80R both periods),
but the benefit of converting SL trades is period-specific.

## Implementation

Single change from EXP002: `TP_MULT = 1.5` (was `2.0`).

`calculate_sl_tp_exp004` in `backtest_exp004.py` — local override, `trade_logic.py` unchanged.

One new parameter: `TP_MULT = 1.5`

## Results

### In-sample (Sep 2025 – Mar 2026)

| Metric | EXP002 (2R) | EXP004 (1.5R) | Change |
|---|---|---|---|
| Total trades | 442 | 477 | +35 (+8%) |
| Win rate | 36.2% | **45.1%** | +8.9pp |
| Total return | +39.7% | **+76.5%** | +36.8pp |
| Max drawdown | 17.8% | **16.4%** | −1.4pp (better) |
| Profit factor | 1.115 | **1.199** | +0.084 |
| Expectancy | $8.98 | **$16.03** | +$7.05 |

Monthly IS:
```
2025-09  n= 10  WR=50.0%  net=   +245
2025-10  n= 93  WR=46.2%  net= +1,512
2025-11  n= 90  WR=53.3%  net= +3,995
2025-12  n= 60  WR=33.3%  net= -1,559  ← still negative
2026-01  n= 75  WR=45.3%  net= +1,401
2026-02  n= 83  WR=44.6%  net= +1,444
2026-03  n= 66  WR=42.4%  net=   +606
```

### Out-of-sample (Mar – Sep 2025)

| Metric | EXP002 (2R) | EXP004 (1.5R) | Change |
|---|---|---|---|
| Total trades | 417 | 473 | +56 (+13%) |
| Win rate | 36.9% | **41.2%** | +4.3pp |
| Total return | **+48.4%** | +11.6% | **−36.8pp worse** |
| Max drawdown | **11.7%** | 16.9% | **+5.2pp worse** |
| Profit factor | **1.155** | 1.041 | **−0.114 worse** |
| Expectancy | **$11.62** | $2.44 | **−$9.18 worse** |

Monthly OOS:
```
2025-03  n=  9  WR=44.4%  net=    +93
2025-04  n= 76  WR=31.6%  net= -1,538  ← worst month unchanged
2025-05  n= 99  WR=45.5%  net= +1,161  ← was +2,467 in EXP002, now worse
2025-06  n= 85  WR=38.8%  net=   -299  ← slight improvement from -538
2025-07  n= 54  WR=48.1%  net= +1,050
2025-08  n=103  WR=40.8%  net=   +129  ← was +877 in EXP002, now much worse
2025-09  n= 47  WR=44.7%  net=   +558
```

## Decision: REVERT

The 1.5R TP does not improve the system.

**What went wrong:**

The IS improvement is substantial and real: PF 1.115 → 1.199, nearly double the return.
But the OOS regression is catastrophic: PF 1.155 → 1.041, return 48% → 12%.

The IS/OOS asymmetry is the key finding. The tighter TP shifts more profit into winning months
(Nov IS improved most, +53.3% WR vs 35.6%), but the OOS period's winning months pay a steep
cost without gaining proportional conversions:

- May OOS: 99 trades at 1.5R → many TP trades truncated at reduced reward. Was $2,467, now $1,161.
- Aug OOS: 103 trades, 40.8% WR, was $877, now $129. Large batch of truncated TP trades.

**Why the simulation underestimated the regression:**

The trade count increased (+13% OOS) because shorter-duration TP trades free up the system
for new entries. Many of these additional trades in OOS are losers (Apr: 76 trades, 31.6% WR).
The simulation only re-evaluated the original 417 trades; the real backtest picks up 56 additional
trades that were blocked by open positions in the EXP002 run.

**The structural diagnosis:**

The OOS period's best months (May, Aug) were high-frequency, TP-heavy months under EXP002.
Reducing TP from 2R to 1.5R cuts the reward on their best trades by 25% without
commensurate compensation. The IS period's best month (Nov) had more frequent conversions
because its market structure matched the 1.5R exit geometry better.

This is the same IS/OOS asymmetry pattern as EXP003:
- IS shows improvement, OOS shows regression
- The improvement in IS does not generalize
- The parameter is exploiting IS-specific market structure

**EXP002 remains the best baseline.**

## Observations for future experiments

The exit parameter space has now been explored:
- BE stop at 1R: catastrophic (PF 1.135 → 0.840 IS simulation)
- TP at 1.5R: IS improvement but OOS regression
- TP at 2.0R: IS/OOS consistent — this is the correct setting

The losing months (Dec IS, Apr OOS) remain the system's primary problem. Neither:
- Entry-time regime filters (EXP003)
- Exit parameter changes (EXP004)
...can reliably cure them.

Both the entry and exit dimensions have been explored. The evidence points toward these months
representing irreducible losses at the current system stage, or requiring information that
single-timeframe OHLCV data cannot provide.

## What to try next (EXP005 candidates)

Given the dead ends on both entry filters and exit tuning:

1. **Direction selectivity per day** — Use a daily-bar trend signal (e.g., price relative to
   daily EMA50) to trade only longs or only shorts on a given day. This is structurally
   different from an entry-bar filter: it operates at a coarser regime level.

2. **Multi-asset validation** — Run EXP002 unchanged on ETH, SOL, BNB, XRP to test whether
   the system edge is BTC-specific or generalizes. Strong generalization increases confidence
   in the baseline; poor generalization changes what we should optimize.

3. **Accept the baseline and move to robustness** — If EXP002 IS/OOS are already consistent
   (which they are), document it as validated and move to walk-forward / regime sensitivity
   rather than continuing to optimize individual parameters.
