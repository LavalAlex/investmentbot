# BTC Trading System V2 — Claude Research Protocol

## 1. Objective

Design a **new BTC trading system from scratch** using everything learned from the previous system.

This is **not** a tuning continuation of the prior strategy.
This is a fresh research effort informed by prior evidence.

The goal is to build a system that is more robust across market structures, especially:
- sustained trends
- recovery phases
- oscillating / choppy environments

The prior system had real edge in a bear-market/trending window, but failed out-of-sample in a different market structure. This v2 effort must explicitly account for that.

---

## 2. Core Design Philosophy

### We are NOT doing this:
- blindly reusing EMA20/50 crossover logic
- trying random indicators until something works
- optimizing on one short window
- chasing in-sample performance only
- assuming a system must trade all market regimes

### We ARE doing this:
- building a new system family from first principles
- using prior findings as hard constraints
- testing one meaningful hypothesis at a time
- validating on multiple market structures
- preferring robustness over flashy backtest returns

---

## 3. Prior Research — What We Know

## 3.1 What the previous system was

The prior BTC system was fundamentally:
- multi-timeframe trend following
- confluence-based
- strongly dependent on bearish/trending conditions
- heavily driven by SHORT profitability

It worked well in a sustained bearish trend window.
It failed out-of-sample in a post-crash recovery / oscillating structure.

This means the prior system was not “wrong,” but it was **regime-specific**.

---

## 3.2 What was proven

### Confirmed findings from v1
- The prior system had real in-sample edge in BTC during a strong directional period.
- SHORT-side payoff asymmetry mattered.
- Break-even, circuit breaker, and cooldown were not random; they were near a local optimum for that system.
- Many obvious tweaks made things worse, not better.
- Entry filtering and risk logic interacted in non-trivial ways.
- The prior system did NOT generalize across market structures.

### Structural lesson
The main failure was not “bad parameters.”
The main failure was:
- signal logic that worked in one regime
- but did not transfer to another regime

---

## 3.3 What was disproven

The following ideas were tested in the prior system family and should NOT be reused blindly as “easy fixes”:

- ADX hard gate as generic fix
- naive body-quality filter applied symmetrically
- hard displacement entry gate
- time-exit-near-TP
- naive dynamic circuit breaker
- simple EMA200 mirror filter as full solution
- further parameter tweaking on the old architecture

These either:
- reduced in-sample performance,
- broke system interactions,
- or failed to solve out-of-sample weakness.

This does NOT mean these concepts are universally bad.
It means they are **not automatic solutions** and must not be reintroduced without a new causal reason.

---

## 4. Design Constraints for V2

Any new system must be designed under these constraints:

### 4.1 Regime robustness
The system must be evaluated across more than one market structure.
It cannot be judged on one directional 180d window only.

### 4.2 Simplicity
Avoid over-complex logic.
Prefer:
- simple signals
- explainable rules
- low interaction complexity

### 4.3 No blind confluence stacking
The old system stacked many correlated filters.
New filters must add genuinely new information, not duplicate existing signal dimensions.

### 4.4 Clear family identity
The new system must belong to a clearly identified strategy family, for example:
- breakout / volatility expansion
- trend continuation after pullback
- mean reversion
- reversal / exhaustion
- regime-switch hybrid

Do not mix incompatible families without a clear architecture.

### 4.5 Deterministic research
No external AI/API should drive the live signal itself.
Claude may assist research, code, and evaluation — not replace trading logic with black-box decisions.

---

## 5. V2 Research Goal

Build a BTC trading system that is more robust across:
- trend continuation phases
- post-crash recoveries
- oscillating / choppy conditions

This does NOT require trading every market equally well.
It is acceptable to:
- trade only in specific regimes,
- or explicitly stay flat in non-ideal conditions,

as long as this is intentional and validated.

---

## 6. Suggested V2 Research Directions

Claude should NOT try to pursue all of these at once.
These are candidate directions to consider and rank.

### Direction A — Breakout / volatility expansion system
Core idea:
- detect compression
- enter on expansion / breakout
- confirm with volume and range expansion

Why interesting:
- clearly different from prior EMA-confluence logic
- may generalize better to both trend starts and recoveries

### Direction B — Pullback continuation system
Core idea:
- trend identified first
- enter only on structured retracement with continuation signal

Why interesting:
- more precise than plain EMA crossover
- can reduce late entries

### Direction C — Regime-switch architecture
Core idea:
- explicit ON/OFF layer for market state
- one system active only in certain market conditions

Why interesting:
- aligns with the lesson that the old edge was context-specific

### Direction D — Mean-reversion or reversal system
Core idea:
- intentionally trade the regimes the prior system failed in

Why interesting:
- if the prior system was trend-only, a second family could complement it

This should be considered carefully; do not assume it is the best path without evidence.

---

## 7. Required Research Workflow

Claude must follow this workflow strictly.

### Step 1 — Define the system family
Before coding, identify:
- what family the new system belongs to
- why that family is worth testing
- why it is meaningfully different from v1

### Step 2 — Write the hypothesis
Each experiment must start with:
- hypothesis
- reason
- expected benefit
- expected failure mode

### Step 3 — Implement minimally
Only implement what is needed for that hypothesis.
Do not stack multiple independent ideas in one experiment.

### Step 4 — Run evaluation
At minimum:
- in-sample test
- out-of-sample test
- directional breakdown
- monthly breakdown
- drawdown
- PF
- expectancy

### Step 5 — Decide
Each experiment must conclude:
- KEEP
- REVERT
- NEEDS FOLLOW-UP

### Step 6 — Document
Each experiment must be saved in `experiments/` with:
- hypothesis
- exact code change
- metrics
- decision
- notes

---

## 8. Evaluation Standards

The system should not be judged only by cumulative return.

Track at minimum:
- total trades
- win rate
- cumulative return
- max drawdown
- profit factor
- expectancy
- longest loss streak
- long contribution
- short contribution
- monthly consistency

Special priority:
- out-of-sample PF
- out-of-sample drawdown
- regime sensitivity

---

## 9. Anti-Overfitting Rules

Claude must not:
- optimize on a single window repeatedly
- run large parameter sweeps without strong justification
- keep tiny improvements that come from collapsing trade count
- keep changes that only improve one exceptional month
- claim robustness without multi-regime evidence

When in doubt:
- prefer fewer parameters
- prefer fewer rules
- prefer systems that remain understandable

---

## 10. What “Success” Means

A successful v2 system is one that satisfies most of the following:

- profitable in-sample
- at least acceptable out-of-sample
- PF above 1.0 in both
- drawdown controlled
- not dependent on one single month
- explainable
- clearly better structured than v1

Stretch goal:
- a system that is less regime-fragile than v1

---

## 11. First Task for Claude

Claude’s first task is NOT to code immediately.

First:
1. inspect the existing repo
2. summarize the prior system and the lessons learned
3. propose 2–3 distinct v2 system families
4. rank them by expected value, robustness, and implementation risk
5. recommend ONE family to prototype first
6. only then start experiment 001 for v2

---

## 12. Final Instruction

You are not here to rescue the old system.

You are here to design a better one from scratch using accumulated evidence.

Be rigorous.
Be conservative.
Be honest.
Prefer truth over optimism.