# BTC Strategy Optimization Protocol

## Objective
Improve the current BTC-only strategy in a controlled, testable, and auditable way.

The goal is NOT to maximize backtest return at any cost.
The goal is to improve robustness and real-world tradability.

## Current scope
- Asset: BTC/USDT only
- Primary timeframe: 15m
- Higher timeframe confirmation: 1h
- Backtest horizon: 180 days
- Strategy currently supports both LONG and SHORT
- Claude API filter is disabled
- Optimization must remain fully local and deterministic

## Current baseline
Use the current dual-side version (v2 baseline) as the reference system unless a newer baseline is explicitly approved.

Track at minimum:
- total trades
- win rate
- cumulative return
- max drawdown
- profit factor
- expectancy
- longest loss streak
- long-side breakdown
- short-side breakdown
- monthly returns

## Optimization targets
Desired long-term target range:
- Profit factor > 1.15
- Positive cumulative return on BTC 180d
- Max drawdown lower than current baseline
- Longest loss streak reduced if possible
- No severe reduction in trade count unless performance improves materially

## Hard constraints
- Do not add randomness
- Do not use external AI APIs
- Do not optimize on short windows only
- Do not delete previous experiments
- Do not modify more than ONE core hypothesis at a time
- Do not change multiple major system components in a single iteration
- Do not declare success based only on win rate
- Do not overfit to one month
- Do not optimize for return alone while worsening drawdown dramatically

## Experiment protocol
For each experiment:
1. State the hypothesis clearly
2. Change only one major variable or rule set
3. Run the BTC 180d backtest
4. Compare against the approved baseline
5. Summarize:
   - what changed
   - why it was changed
   - what improved
   - what worsened
   - whether the change should be kept or reverted

## Approved decision rule
Keep a change only if it improves the strategy meaningfully.

A change is considered meaningful if it improves at least one of:
- profit factor
- cumulative return
- max drawdown
- expectancy

WITHOUT causing unacceptable deterioration in the others.

## Preferred optimization order
Claude should prioritize experiments in this order:
1. scoring logic / weighted scoring
2. long vs short asymmetry
3. exit behavior
4. circuit breaker tuning
5. regime detection only if it is based on directional logic, not naive volatility filters

## Disallowed optimization behavior
- Stacking many filters at once
- Changing thresholds blindly without explanation
- Accepting redundant conditions
- Making lagging confirmations hard requirements unless proven beneficial
- Replacing the strategy with a completely different one without approval

## Logging
Every experiment must be recorded in a structured file, for example:
- experiments/001-weighted-scoring.md
- experiments/002-short-exit-adjustment.md

Each experiment file must include:
- hypothesis
- code changes
- backtest results
- keep/revert decision

## Current research insight
So far:
- 15m is the best native timeframe among 5m / 15m / 1h
- dual-side trading is better than long-only
- many added filters were redundant or harmful
- over-filtering reduced edge
- the current system likely needs better signal weighting rather than more raw conditions

## Claude behavior
Claude acts as a quantitative research assistant and system optimizer.
Claude must be cautious, empirical, and reversible.
Claude should prefer small improvements over dramatic rewrites.