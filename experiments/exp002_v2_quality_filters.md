# EXP002-v2 — Quality Filters

## Hypothesis

EXP001 baseline produced ~2000 trades with PF ~1.04 and ~42% drawdown.
The system lacks selectivity: the ±1% pullback tolerance accepts almost any bar near EMA20,
and there is no guard against flat/weak trend phases.

Adding structural quality filters — without changing core logic — should remove low-quality
entries, reduce trade frequency, lower drawdown, and improve per-trade expectancy.

## Rationale

Four filters, each targeting a distinct source of low-quality entries:
1. **Trend strength**: rejects flat/weak EMA50 regimes — reduces entries in non-directional markets
2. **Pullback quality**: requires the 1h bar's intrabar extreme to have structurally touched EMA20 — replaces the loose ±1% proximity check with a real "touch and bounce" condition
3. **Candle quality**: requires the 15m trigger candle body ≥ 60% of range — rejects doji/indecision candles
4. **Range floor**: rejects entries during compression (5-bar avg range < 0.1% of price)

No changes to: trend detection logic, SL/TP (2:1 RR), position sizing, multi-timeframe design.

## Parameters added (4 total)

| Parameter | Value | Purpose |
|---|---|---|
| EMA50_SLOPE_MIN_PCT | 0.05% | EMA50 must move ≥ 0.05% over 5 bars |
| EMA50_DIST_MIN_PCT | 0.5% | Price must be ≥ 0.5% away from EMA50 |
| MIN_BODY_RATIO | 0.60 | 15m candle body ≥ 60% of range |
| MIN_RANGE_PCT | 0.1% | 5-bar avg 15m range ≥ 0.1% of price |

Pullback quality uses structural constants (0.2% touch slack, 0.5% collapse limit) — not tunable parameters.

## Implementation

- `strategy_pullback.py` — added: `is_trend_strong`, `is_pullback_quality`, `is_candle_quality`, `is_range_sufficient`; updated `prepare_1h` (adds EMA50), `prepare_15m` (adds avg_range), `align_1h_to_15m` (exposes 1h OHLC for pullback quality check)
- `backtest_exp002.py` — new runner applying all four filters

## Results

### In-sample (Sep 2025 – Mar 2026)

| Metric | EXP001 | EXP002 | Change |
|---|---|---|---|
| Total trades | 1873 | 442 | -76% |
| Win rate | 34.5% | 36.2% | +1.7pp |
| Total return | +60.1% | +39.7% | -20pp |
| Max drawdown | 42.2% | 17.8% | **-24pp** |
| Profit factor | 1.048 | 1.115 | **+0.07** |
| Expectancy | $3.21 | $8.98 | **+$5.77** |
| Max consec. losses | 21 | 12 | -9 |
| Long PnL | -$1,061 | +$3,656 | Long side now profitable |
| Short PnL | +$7,073 | +$313 | Short edge compressed |

Monthly breakdown:
```
2025-09  trades=  9  win%= 11.1  net=  -588 USD
2025-10  trades= 87  win%= 39.1  net= +1421 USD
2025-11  trades= 77  win%= 40.3  net= +1773 USD
2025-12  trades= 58  win%= 27.6  net= -1260 USD
2026-01  trades= 69  win%= 40.6  net= +1737 USD
2026-02  trades= 78  win%= 35.9  net=  +698 USD
2026-03  trades= 64  win%= 34.4  net=  +188 USD
```

### Out-of-sample (Mar – Sep 2025)

| Metric | EXP001 | EXP002 | Change |
|---|---|---|---|
| Total trades | 2126 | 417 | -80% |
| Win rate | 34.6% | 36.9% | +2.3pp |
| Total return | +83.1% | +48.4% | -35pp |
| Max drawdown | 44.9% | 11.7% | **-33pp** |
| Profit factor | 1.036 | 1.155 | **+0.12** |
| Expectancy | $3.91 | $11.62 | **+$7.71** |
| Max consec. losses | 18 | 11 | -7 |
| Long PnL | +$2,392 | +$1,310 | |
| Short PnL | +$5,916 | +$3,535 | |

Monthly breakdown:
```
2025-03  trades=  9  win%= 33.3  net=    -9 USD
2025-04  trades= 42  win%= 26.2  net=  -894 USD
2025-05  trades= 89  win%= 42.7  net= +2467 USD
2025-06  trades= 79  win%= 31.6  net=  -538 USD
2025-07  trades= 51  win%= 43.1  net= +1710 USD
2025-08  trades= 99  win%= 35.4  net=  +651 USD
2025-09  trades= 48  win%= 41.7  net= +1457 USD
```

### Filter rejection breakdown (IS)

| Filter | Bars rejected |
|---|---|
| Trend strength | 5,070 |
| Pullback quality | 6,277 |
| Candle quality | 712 |
| Range floor | 27 |

The two dominant filters are trend strength and pullback quality. Candle quality adds meaningful
but secondary reduction. Range floor had negligible impact (27 rejections over 180d).

## Decision: KEEP

All four filters improve quality:
- Max drawdown halved in IS (-24pp), cut to a quarter in OOS (-33pp)
- PF improved on both windows
- Expectancy tripled
- IS/OOS consistency: PF 1.115 IS vs 1.155 OOS — OOS is slightly better, no sign of overfitting
- Trade count is now reasonable (~2-3/day)

## Notes

- Total return dropped because we do fewer trades — this is expected and correct
- Long side became profitable in IS after filters removed low-quality noise entries
- Short side still dominates OOS, suggesting regime asymmetry remains present
- Dec 2025 IS (-$1260) and Apr/Jun 2025 OOS are negative — pattern worth investigating
- Range floor filter is nearly inert (27 rejections) — consider removing in EXP003 or raising threshold
- IS Dec weakness coincides with the period where EXP001 also had a rough patch
- Parameters were not optimized; these are first-pass values

## Follow-up candidates

- Investigate Dec 2025 / Apr 2025 negative months — regime issue or signal degradation?
- Consider removing range floor (too weak) and replacing with something more meaningful
- Examine whether long vs short performance gap can be explained by prevailing regime
