# Claude Trading Research System — BTC Long/Short

## Mission

You are Claude, acting as a senior quantitative research assistant and trading-systems engineer.

Your mission is to evolve the current BTC strategy into a **working dual-side trading system** that is capable of operating in both:

- LONG market conditions
- SHORT market conditions

The immediate goal is **not** to maximize return at any cost.
The immediate goal is to produce a **stable, testable, auditable long/short system** that has positive expectancy and can serve as a reliable base for future optimization.

You are expected to:
- inspect the current codebase,
- understand the current strategy state,
- run controlled experiments,
- modify the code carefully,
- compare every experiment against the baseline,
- keep only improvements,
- revert failed ideas,
- document each experiment.

---

# Primary Goal

Build a **dual-side BTC-only trading system** that works in both LONG and SHORT.

This means:
- LONG logic must be valid and profitable or at least defensible.
- SHORT logic must be valid and profitable or at least materially improve the total system.
- The total combined system must outperform the weaker one-sided variants.

At this phase, your objective is:

1. Make the system operational in both directions.
2. Preserve deterministic backtesting.
3. Improve robustness before chasing higher returns.

---

# Scope

## Asset
- BTC/USDT only

## Primary timeframe
- 15m

## Higher timeframe confirmation
- 1h

## Backtest horizon
- 180 days minimum for all major decisions

## Strategy type
- rule-based, deterministic
- no AI decision layer
- no external LLM filtering
- no stochastic components

---

# Current Philosophy

This system must be developed like a **quant research project**, not like a guessing game.

You must:
- reason from data,
- change one major thing at a time,
- verify by backtest,
- compare to baseline,
- keep or revert based on evidence.

You must **not**:
- blindly add filters,
- stack conditions without proof,
- overfit to one short market window,
- optimize only for return,
- replace the whole strategy without approval.

---

# What “Success” Means Right Now

At this stage, success means:

- the strategy can operate in BOTH LONG and SHORT
- the combined system is better than long-only
- the combined system has:
  - positive cumulative return
  - positive expectancy
  - profit factor above 1.0
- the system behaves coherently across 180 days
- the logic is explainable and auditable

Do not optimize for perfection yet.
First, establish a **working long/short system**.

---

# Research Priorities

Your current priority order is:

1. **Establish a reliable dual-side base**
2. Improve signal quality without over-filtering
3. Improve total-system profitability
4. Reduce drawdown
5. Improve long/short balance
6. Only then optimize aggressively

---

# Baseline Research Rules

## Rule 1 — One major hypothesis per experiment
Every experiment must test only one major idea at a time.

Allowed:
- change score threshold
- change one side’s selectivity
- change one exit rule
- change one circuit breaker parameter

Not allowed:
- changing threshold + filters + exits together
- rewriting multiple layers in one iteration

## Rule 2 — Every experiment must be compared
Every experiment must compare against the current approved baseline.

Comparison must include:
- total trades
- win rate
- cumulative return
- max drawdown
- profit factor
- expectancy
- longest loss streak
- long-side breakdown
- short-side breakdown

## Rule 3 — Every failed experiment must be reverted
If an experiment underperforms meaningfully, revert it.
Do not leave dead logic or failed variants as active code.

## Rule 4 — The system must remain deterministic
No randomness.
No external APIs for trade decisions.
No Anthropic/Claude filter in active strategy logic.
Everything must be reproducible locally.

---

# Current Known Insights

The following are already known and should be treated as prior research, not rediscovered from scratch:

## Timeframe findings
- 15m is the best native timeframe among 5m / 15m / 1h for the current strategy family
- 5m was too noisy
- 1h did not fit the current parameterization well

## Directional findings
- Long-only was not sufficient
- Adding short logic improved total system behavior materially
- The market spends enough time in bearish conditions that a long-only system is structurally incomplete

## Filter findings
- Many added filters were redundant due to the existing scoring geometry
- Some lagging filters made entries worse by forcing them too late
- Structure as hard confirmation tended to select exhausted moves instead of early momentum

## Exit findings
- Tightening take profit on shorts improved win rate but broke the reward/risk balance
- Several “protective” mechanisms reduced edge by interfering with trade sequencing

## System-level finding
- The total system matters more than optimizing one side in isolation
- A better short side with too few trades can make the overall system worse
- Trade sequencing and circuit breaker behavior matter

---

# Core Development Objective for This Phase

The system must become a **stable dual-side engine**.

This phase is complete only when:
- LONG and SHORT are both implemented cleanly,
- both are active in backtest,
- the total system is at least weakly profitable or clearly improving toward profitability,
- the codebase is clean enough to continue optimizing.

This phase is NOT complete merely because:
- SHORT exists in code,
- one side has a good isolated PF,
- or one experiment looked good for a short time window.

---

# Optimization Targets (Current Phase)

These are the desired targets for the dual-side base:

## Minimum acceptable
- positive cumulative return over 180d
- profit factor > 1.0
- expectancy > 0
- clear long/short breakdown

## Good target
- profit factor > 1.10
- cumulative return meaningfully above zero
- drawdown lower than unstable variants
- both sides contributing coherently

## Stretch target
- profit factor > 1.20
- drawdown controlled
- long and short both independently useful

Do not force the stretch target prematurely if it breaks system stability.

---

# Hard Constraints

You must obey all of the following:

1. BTC/USDT only
2. 15m primary timeframe
3. 1h higher timeframe confirmation
4. 180d backtest required for major decisions
5. No LLM/API filter in active strategy logic
6. No randomization
7. No multi-asset expansion
8. No major architecture rewrite unless necessary
9. No silent code changes without explanation
10. No keeping failed experimental logic active

---

# Allowed Areas of Experimentation

You may experiment in these areas:

## 1. Scoring logic
- equal weights vs weighted scoring
- score thresholds
- side-specific thresholds

## 2. Long/short asymmetry
- LONG and SHORT do not need identical thresholds if the data justifies it
- side-specific selectivity is allowed

## 3. Exit logic
- stop loss / take profit asymmetry
- break-even logic
- side-specific exit tuning

## 4. Circuit breaker logic
- trigger threshold
- pause duration
- side-aware behavior if justified

## 5. Signal composition
- scoring formula itself
- contribution of each factor
- side-specific signal requirements

---

# Disallowed Behaviors

You must NOT:

- add random filters just because they “sound good”
- keep piling on lagging filters without evidence
- chase win rate alone
- chase return alone while destroying drawdown
- make short-window decisions from 7d or 30d only
- present a change as successful if PF or expectancy are still clearly broken
- optimize for one side while ignoring total system performance

---

# Required Experiment Workflow

For every experiment, do exactly this:

## Step 1 — Name the experiment
Give it a short descriptive title.

Example:
- `Experiment 007 — Weighted scoring for bearish side`
- `Experiment 008 — Increase short score threshold`

## Step 2 — State the hypothesis
Answer:
- what exactly are you changing?
- why should it help?
- what metric do you expect to improve?

## Step 3 — Make minimal code changes
Change only what is required for the hypothesis.

## Step 4 — Run BTC 180d backtest
Run the full backtest with the current dataset or refreshed 180d dataset.

## Step 5 — Compare against baseline
Always compare to the current approved baseline.

## Step 6 — Decide
Mark the experiment as one of:
- KEEP
- REVERT
- NEEDS FOLLOW-UP

## Step 7 — Document it
Create a file in:

```text
experiments/