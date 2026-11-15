
# Vinayak-Trading Intelligence (VTI)

> **Status 2026-11-14:** the owner's decisions and the corrections found when this document was checked against the platform are in
> `docs/vti-alignment.md`; Phase 1 is specified in `docs/vti-phase1-spec.md`. Where they disagree with this document, they win.
> This document is the long-term target. It does not permit autonomous live trading.
## Autonomous Quantitative Research, Self-Learning & Adaptive Trading System

**Document type:** Technical Architecture & Implementation Specification  
**Project:** Vinayak-Trading  
**Version:** 1.0  
**Status:** Proposed Architecture  
**Primary objective:** Build an autonomous quantitative research and trading intelligence system.

---

# 1. Executive Summary

Vinayak-Trading will evolve from a conventional algorithmic trading platform into an autonomous quantitative research and portfolio management system.

The system will continuously:

1. Study historical and live financial markets.
2. Identify market conditions and emerging patterns.
3. Discover potentially profitable statistical relationships.
4. Generate new trading hypotheses.
5. Automatically create and evaluate strategy variations.
6. Learn from historical experiments and actual trading outcomes.
7. Detect strategy degradation.
8. Adapt strategy selection to changing market conditions.
9. Dynamically allocate capital across validated strategies.
10. Execute approved strategies through Zerodha.
11. Continuously evaluate its own decisions.

The system will maintain a persistent research memory containing:

- Discovered market patterns.
- Tested hypotheses.
- Successful and unsuccessful experiments.
- Strategy versions.
- Market regime observations.
- Trading outcomes.
- Model performance.
- Research conclusions.

The long-term objective is to develop a system that independently conducts quantitative research and improves its trading capabilities over time.

## 1.1 Existing Infrastructure

The architecture will build on the existing Vinayak-Trading platform.

| Infrastructure | Current capability |
|---|---|
| Historical market data | Daily bars from 2016-01 (Kite, vendor-adjusted before 2019-10; NSE bhavcopy from 2019-10) |
| Historical instrument coverage | About 2,600 currently listed equities; delisted names only partly covered. Point-in-time membership exists for the Nifty 200 only (2020-10 to 2026-11 reconstructed, not yet verified or loaded) |
| Historical technical data | One-minute data in `bar_1m` from 2016-01-04 (about 336M rows); no completeness check for minutes yet |
| Fundamental data | About 8 years (periods from 2018-03) with filing dates; restatements and standalone vs consolidated not yet handled |
| Live market data | Available (Kite WebSocket, 1-minute bars, quotes every 2 s) |
| Live streaming persistence | TimescaleDB |
| Database | PostgreSQL / TimescaleDB |
| Historical analytics | Raw lake files plus Postgres; DuckDB and Parquet are not in use |
| Backtesting | Daily, long-only; intraday is not built |
| Trading charges | Dated, verified Zerodha delivery schedules in daily backtesting (intraday schedule still assumed) |
| Broker integration | Zerodha: read-only account reader and `KiteBroker` built, nothing calls it yet; live blocked by the live gate and `regulatory_config` |
| Research interface | Next.js Research Console |
| Backend | Python / FastAPI |

The intelligence system should reuse these components wherever possible.

We should avoid introducing duplicate data pipelines, strategy registries or execution systems.

# 2. Design Principles

The following principles are mandatory.

### 2.1 Deterministic computation first

All financially significant calculations must use deterministic software.

Examples:

- Indicators.
- Returns.
- Position sizing.
- Portfolio allocation.
- Risk calculations.
- Backtesting.
- Transaction costs.
- Performance attribution.
- Statistical validation.

An LLM must never be the authoritative source for these calculations.

### 2.2 AI-assisted research

Generative AI will be used where reasoning and interpretation are valuable:

- Generating research hypotheses.
- Explaining statistical discoveries.
- Suggesting new experiments.
- Reviewing failed strategies.
- Summarizing market conditions.
- Preparing research reports.
- Coordinating specialized research agents.

### 2.3 Bounded autonomy

The system can independently conduct research and experiment.

However:

- Research agents cannot place orders.
- Strategy generation cannot modify production code.
- Risk limits cannot be overridden by AI.
- Live deployment requires predefined promotion criteria.
- Every decision must be auditable.

### 2.4 Cost-efficient intelligence

The system must not depend on continuous LLM API calls.

It should operate using:

1. Precomputed features.
2. Statistical models.
3. Incremental calculations.
4. Scheduled machine-learning inference.
5. Event-driven research triggers.
6. Selective LLM invocation.

The system must remain functional when the LLM provider is unavailable.

---

# 3. Overall Architecture

VTI will consist of nine major subsystems.

```text
                 VINAYAK-TRADING
                        |
                 EXISTING DATA LAYER
                        |
             DATA QUALITY & VALIDATION
                        |
                 FEATURE ENGINE
                        |
             +----------+----------+
             |          |          |
          Market     Fundamental  Technical
        Intelligence Intelligence Intelligence
             |          |          |
             +----------+----------+
                        |
                 ALPHA DISCOVERY
                        |
                 STRATEGY FACTORY
                        |
                EXPERIMENT ENGINE
                        |
                VALIDATION ENGINE
                        |
                STRATEGY REGISTRY
                        |
              PORTFOLIO INTELLIGENCE
                        |
                   RISK ENGINE
                        |
                EXECUTION ENGINE
                        |
                    ZERODHA
                        |
                PERFORMANCE ENGINE
                        |
                  LEARNING ENGINE
                        |
               RESEARCH KNOWLEDGE
                        |
                 AI RESEARCH LAYER
                        |
                 ALPHA DISCOVERY
```

The system should be divided into three execution environments.

| Environment | Responsibility | Live order access |
|---|---|---|
| Production | Signals, risk and execution | Controlled |
| Research | Discovery and experimentation | No |
| Validation | Independent candidate evaluation | No |

These environments should have separate permissions and resource limits.

# 4. Data Intelligence Layer

This is the foundation of the entire system.

We already have substantial historical and live data. The objective is to make it research-ready and consistently accessible.

## 4.1 Data sources

| Dataset | Usage |
|---|---|
| One-minute OHLCV | Intraday and short-term research |
| Daily OHLCV | Swing and positional research |
| Corporate actions | Price and return adjustments |
| Financial statements | Fundamental analysis |
| Results publication dates | Point-in-time fundamental analysis |
| Shareholding patterns | Ownership analysis |
| Institutional holdings | Institutional activity |
| Sector classification | Sector-relative analysis |
| Index constituents | Market and universe construction |
| Benchmark data | Relative performance |
| Live ticks | Real-time market intelligence |
| Live orders and trades | Execution analysis |

## 4.2 Critical data requirements

Before enabling autonomous research, verify:

**A. Survivorship bias**

Historical research must include stocks that were delisted, merged, suspended or removed from indices.

Using today's Nifty 200 or Nifty 500 constituents to test a strategy from 2016 would introduce survivorship bias.

**B. Corporate actions**

Splits, bonuses, dividends, mergers and other relevant events must be handled correctly.

**C. Fundamental point-in-time correctness**

The system must use information only after it became publicly available.

For example:

A company's March quarter results published on May 20 must not be available to a backtest dated May 10.

We should preserve:

- Period end date.
- Original publication date.
- Actual availability timestamp, where available.
- Restatement date.
- Original and revised values.

**D. Missing data**

Missing minute bars must not automatically be interpreted as zero-volume periods.

The system must distinguish:

- Exchange holidays.
- Trading halts.
- No trades.
- Data ingestion failures.
- Suspended instruments.

**E. Instrument identity**

Every historical observation must map to the correct instrument identity across symbol changes, mergers and corporate actions.

## 4.3 Data readiness score

Every dataset should have a readiness status.

| Validation | Status |
|---|---|
| Completeness | PASS / FAIL |
| Timestamp correctness | PASS / FAIL |
| Corporate-action consistency | PASS / FAIL |
| Instrument identity | PASS / FAIL |
| Historical membership | PASS / FAIL |
| Fundamental availability | PASS / FAIL |
| Duplicate detection | PASS / FAIL |
| Missing-data classification | PASS / FAIL |

Only datasets satisfying the relevant validation requirements can enter an experiment.

---

# 5. Feature Intelligence Engine

This subsystem converts raw financial data into reusable research features.

Instead of recalculating indicators independently for every strategy, we maintain a shared feature library.

## 5.1 Technical features

Examples:

- SMA / EMA.
- RSI.
- MACD.
- ATR.
- ADX.
- Bollinger Bands.
- Donchian Channels.
- VWAP.
- Relative strength.
- Historical volatility.
- Volume percentile.
- Volume acceleration.
- Price gaps.
- Breakout strength.
- Drawdown.
- Trend persistence.

## 5.2 Fundamental features

Examples:

- Revenue growth.
- EBITDA growth.
- PAT growth.
- EPS growth.
- ROE.
- ROCE.
- Debt-to-equity.
- Operating margin.
- Free cash flow.
- Earnings acceleration.
- Valuation ratios.
- Promoter holding changes.
- Institutional holding changes.

## 5.3 Market features

Examples:

- Nifty returns.
- Market breadth.
- Advance/decline ratio.
- Sector relative strength.
- Market volatility.
- Cross-sectional dispersion.
- Percentage of stocks above moving averages.
- New highs and lows.
- Correlation between sectors.

## 5.4 Feature storage

Features should be:

- Reusable.
- Versioned.
- Timestamped.
- Reproducible.
- Computed without future information.

Suggested logical structure:

```text
features
    feature_definitions
    feature_versions
    feature_observations
    feature_dependencies
    feature_quality
```

We should not create one enormous feature table containing every possible indicator at every frequency.

Use appropriate partitioning and columnar storage for research-heavy workloads.

## 5.5 Multi-timeframe features

The same instrument can have:

- 1-minute features.
- 5-minute features.
- 15-minute features.
- Hourly features.
- Daily features.
- Weekly features.

Strategies can combine these.

For example:

A 5-minute entry signal can require a positive daily trend and positive sector momentum.

All features must be aligned using their actual availability timestamps.

---

# 6. Alpha Discovery Engine

This is one of the most important components.

Its job is to discover relationships between observable market conditions and future returns.

It does not directly create production trading strategies.

## 6.1 Research questions

The engine should continuously investigate questions such as:

- Which features predict returns over 5, 20, 60 and 120 days?
- Does earnings acceleration improve momentum strategies?
- Does relative sector strength improve stock selection?
- Does volume expansion improve breakout reliability?
- Are there specific market regimes where mean reversion works better?
- Do certain combinations of valuation and earnings growth produce superior returns?
- Does volatility contraction precede large price movements?
- Which features become less predictive over time?

## 6.2 Alpha discovery methods

Use multiple approaches.

| Method | Application |
|---|---|
| Correlation analysis | Initial relationship discovery |
| Rank correlation | Cross-sectional relationships |
| Linear regression | Explainable predictive relationships |
| Logistic regression | Probability of positive returns |
| XGBoost | Nonlinear relationships |
| Random Forest | Feature interaction discovery |
| Clustering | Stock behaviour classification |
| PCA | Feature dimensionality reduction |
| Information coefficient | Predictive feature evaluation |
| Mutual information | Nonlinear dependency discovery |

These are research tools, not automatic proof of an investable edge.

## 6.3 Prediction horizons

We should evaluate multiple horizons independently.

| Horizon | Application |
|---|---|
| 1–5 minutes | Very short-term research |
| 15–60 minutes | Intraday research |
| 1 trading day | Short-term |
| 5 trading days | Short-term momentum |
| 20 trading days | Swing |
| 60 trading days | Positional |
| 120 trading days | Medium-term |
| 252 trading days | Long-term |

Not every feature needs to be tested across every horizon.

The research engine should prioritize relevant combinations to control multiple-testing problems.

## 6.4 Alpha research output

Every discovery should produce a structured record.

Example:

```json
{
  "hypothesis_id": "ALPHA-00182",
  "name": "Earnings Acceleration + Momentum",
  "features": [
    "quarterly_earnings_growth",
    "relative_strength_60d",
    "sector_momentum_20d"
  ],
  "prediction_horizon_days": 60,
  "research_status": "CANDIDATE",
  "validation_status": "PENDING",
  "discovery_method": "GRADIENT_BOOSTING",
  "evidence": {
    "sample_size": 0,
    "information_coefficient": null,
    "out_of_sample_return": null
  }
}
```

Values are populated by the actual experiment engine, not invented by an AI agent.

---

# 7. Strategy Factory

The Strategy Factory converts research findings into executable trading strategies.

It should support both manually designed and automatically generated strategies.

## 7.1 Strategy categories

Initially support:

| Category | Examples |
|---|---|
| Momentum | Relative strength, trend following |
| Mean reversion | RSI, statistical reversals |
| Breakout | Price and volume breakouts |
| Fundamental | Quality, growth, value |
| Hybrid | Fundamental + technical |
| Sector rotation | Sector-relative momentum |
| Volatility | Volatility contraction and expansion |
| Event-driven | Results, corporate actions |
| Intraday | Opening range, VWAP, momentum |

## 7.2 Strategy definition language

Do not allow an LLM to generate arbitrary Python code and execute it.

Instead, introduce a typed Strategy DSL.

Example:

```yaml
strategy_id: HYBRID_MOMENTUM_001
version: 1

universe:
  type: HISTORICAL_ELIGIBLE_EQUITIES
  exchange: NSE

timeframe: DAILY

entry:
  all:
    - feature: relative_strength_60d
      operator: ">"
      value: 0.75

    - feature: earnings_growth_yoy
      operator: ">"
      value: 15

    - feature: close_above_sma_50
      operator: "=="
      value: true

exit:
  any:
    - feature: close_below_sma_50
      operator: "=="
      value: true

    - feature: relative_strength_60d
      operator: "<"
      value: 0.40

position_sizing:
  type: VOLATILITY_ADJUSTED

risk:
  max_position_percent: 5
  max_portfolio_exposure_percent: 100
```

This is an illustrative strategy definition, not a validated recommendation.

The DSL should support:

- Entry conditions.
- Exit conditions.
- Universe filters.
- Position sizing.
- Stop-loss.
- Holding period.
- Rebalancing.
- Execution timing.
- Risk constraints.

The strategy engine interprets the DSL deterministically.

## 7.3 Strategy versioning

Every modification creates a new immutable version.

For example:

```text
MOMENTUM_001
    |
    +-- V1: Original
    |
    +-- V2: Volatility adjusted
    |
    +-- V3: Sector confirmation
    |
    +-- V4: Fundamental confirmation
```

Never overwrite an existing strategy version.

---

# 8. Experiment Engine

This is the automated research laboratory.

It should be capable of running thousands of controlled experiments without requiring LLM involvement in each experiment.

## 8.1 Experiment types

1. Parameter optimization.
2. Feature selection.
3. Feature combination testing.
4. Entry condition testing.
5. Exit condition testing.
6. Position-sizing experiments.
7. Holding-period experiments.
8. Market-regime-specific experiments.
9. Portfolio construction experiments.
10. Alternative execution assumptions.

## 8.2 Experiment workflow

```text
EXPERIMENT REQUEST
       |
       v
VALIDATE INPUT DATA
       |
       v
GENERATE CONFIGURATIONS
       |
       v
EXECUTE BACKTESTS
       |
       v
CALCULATE PERFORMANCE
       |
       v
COMPARE WITH BASELINE
       |
       v
STATISTICAL VALIDATION
       |
       v
STORE RESULTS
       |
       v
GENERATE RESEARCH SUMMARY
```

## 8.3 Experiment optimization

Use:

- Grid search for small parameter spaces.
- Random search for broad parameter exploration.
- Bayesian optimization for expensive experiments.
- Genetic algorithms for strategy evolution.

Avoid exhaustive brute-force searches across thousands of parameters.

The number of experiments itself must be recorded because trying thousands of variations increases the probability of finding apparently profitable results by chance.

## 8.4 Experiment reproducibility

Every experiment must record:

- Strategy version.
- Dataset version.
- Feature versions.
- Instrument universe.
- Date range.
- Transaction-cost configuration.
- Execution assumptions.
- Random seed.
- Model version.
- Parameter configuration.
- Code version.

The same experiment must be reproducible.

---

# 9. Validation Engine

This subsystem is the gatekeeper.

A high historical return does not mean a strategy is good.

## 9.1 Validation methodology

Use chronological separation.

Example:

| Dataset | Period | Usage |
|---|---|---|
| Research / development (training, validation, walk-forward) | 2016-01-04 to 2024-12-31 | Everything the research loop may see |
| Global final holdout | 2025-01-01 to 2026-11-13 | One controlled evaluation per frozen strategy family; no worker or LLM may read it |
| Paper trading | After the engineering gates pass | Observe live behaviour |

Fixed by the owner on 2026-11-14 (see `docs/vti-alignment.md` section 3). The Nifty 200 development window is shorter until its membership is verified.

For intraday experiments, use purged time-series validation and embargoes where overlapping labels or holding periods could leak information.

## 9.2 Performance metrics

Every candidate should be evaluated using:

| Metric | Purpose |
|---|---|
| CAGR | Annualized return |
| Maximum drawdown | Capital loss |
| Sharpe ratio | Risk-adjusted performance |
| Sortino ratio | Downside risk |
| Calmar ratio | Return versus drawdown |
| Profit factor | Gross profit / gross loss |
| Expectancy | Average expected trade outcome |
| Win rate | Percentage of winning trades |
| Average holding period | Capital utilization |
| Turnover | Trading intensity |
| Exposure | Capital deployed |
| Benchmark alpha | Relative performance |
| Capacity | Practical deployment size |

## 9.3 Statistical robustness

Mandatory tests:

- Walk-forward validation.
- Out-of-sample validation.
- Parameter sensitivity.
- Transaction-cost sensitivity.
- Different market regimes.
- Different stock universes.
- Different time periods.
- Multiple-testing correction.
- Probability of backtest overfitting where appropriate.

We should also investigate whether profitability is concentrated in a few stocks, a few trades or a particular year.

A strategy that works only in one historical market environment is not automatically robust.

## 9.4 Strategy promotion statuses

```text
DISCOVERED
    |
    v
RESEARCH
    |
    v
BACKTESTED
    |
    v
VALIDATION
    |
    v
APPROVED_FOR_PAPER
    |
    v
PAPER_TRADING
    |
    v
APPROVED_FOR_LIVE
    |
    v
ACTIVE
    |
    v
MONITORING
    |
    +----> DEGRADED
    |
    +----> SUSPENDED
    |
    +----> RETIRED
```

Promotion must be controlled by explicit criteria.

AI cannot directly change a strategy's status to ACTIVE.

---

# 10. Market Regime Intelligence

The system must understand that markets behave differently over time.

A single strategy rarely performs equally well in every environment.

## 10.1 Regime classification

Initial classifications:

- Strong bullish trend.
- Weak bullish trend.
- Strong bearish trend.
- Weak bearish trend.
- Sideways market.
- High-volatility market.
- Low-volatility market.
- High-dispersion market.
- Sector-rotation environment.

## 10.2 Detection methods

Start with:

- Rule-based classification.
- Clustering.
- Hidden Markov Models.
- Change-point detection.

Later introduce machine-learning models.

## 10.3 Regime output

Example:

```json
{
  "timestamp": "2026-11-14T15:30:00+05:30",
  "regime": "SIDEWAYS_HIGH_VOLATILITY",
  "confidence": 0.78,
  "features": {
    "market_volatility": 0.82,
    "market_breadth": 0.35,
    "trend_strength": 0.29
  },
  "model_version": "REGIME_V3"
}
```

Illustrative output only.

The regime classifier should use information available at the decision timestamp.

A useful improvement is to support uncertainty and transition states rather than forcing every market observation into a single confident category.

---

# 11. Self-Learning Engine

This is the component responsible for learning from experience.

It should maintain three separate learning processes.

## 11.1 Trade-level learning

For every completed trade, capture:

- Original signal.
- Strategy version.
- Market regime.
- Entry conditions.
- Exit conditions.
- Expected risk.
- Actual result.
- Slippage.
- Execution quality.
- Failure classification.

## 11.2 Strategy-level learning

Analyze performance across meaningful samples.

For example:

The system finds that a particular momentum strategy performs well in trending markets but deteriorates significantly when market breadth declines.

It proposes:

- Reduce exposure.
- Tighten entry requirements.
- Add market breadth confirmation.
- Suspend entries under certain conditions.

Each proposal becomes an experiment.

## 11.3 Model-level learning

Monitor:

- Prediction accuracy.
- Feature drift.
- Prediction drift.
- Calibration.
- Out-of-sample performance.
- Model degradation.

Models should be retrained according to defined schedules or drift triggers.

Retraining does not automatically mean replacing the production model.

New versions must pass validation.

## 11.4 Learning memory

Maintain persistent knowledge:

```text
research_memory
    hypotheses
    discoveries
    failed_experiments
    successful_experiments
    strategy_observations
    market_regime_observations
    model_observations
    research_conclusions
```

This is the system's institutional memory.

It should use structured records and searchable summaries, not depend exclusively on LLM conversation history.

# 12. Generative AI Architecture — Token-Efficient Design

This is a particularly important part of the design.

We want Gen AI capabilities, but we don't want an architecture that sends millions of market observations to an LLM.

**LLMs should reason about research results, not process raw financial data continuously.**

## 12.1 Division of responsibilities

| Task | Technology | LLM required? |
|---|---|---|
| Process market ticks | Python / TimescaleDB | No |
| Calculate indicators | Python / NumPy | No |
| Detect price patterns | Statistical models | No |
| Calculate fundamental ratios | Deterministic engine | No |
| Identify regimes | ML / statistical models | No |
| Calculate predictive relationships | ML / statistics | No |
| Generate hypotheses | LLM | Yes |
| Generate strategy configurations | LLM + Strategy DSL | Sometimes |
| Run backtests | Backtesting engine | No |
| Evaluate statistical validity | Statistical engine | No |
| Explain failed experiments | LLM | Yes |
| Review research findings | LLM | Yes |
| Allocate capital | Portfolio optimizer + risk engine | No |
| Execute orders | Trading engine | No |
| Prepare research reports | LLM | Optional |

## 12.2 Five Gen AI capabilities

### A. Research Hypothesis Generator

Input:

A compact research summary generated by the quantitative research engine.

Example:

```json
{
  "research_area": "MOMENTUM",
  "observation": "Momentum performance deteriorates during weak market breadth",
  "evidence": {
    "sample_size": 4200,
    "historical_period": "2016-2025",
    "out_of_sample_consistency": "POSITIVE"
  },
  "existing_strategies": [
    "MOMENTUM_V1",
    "MOMENTUM_V2"
  ]
}
```

LLM task:

Generate three testable hypotheses.

Possible response:

1. Introduce market breadth as an entry filter.
2. Reduce momentum position sizing when breadth deteriorates.
3. Use sector-level breadth instead of market-wide breadth.

The LLM proposes research. The experiment engine verifies it.

### B. Strategy Research Assistant

The LLM can convert a research hypothesis into a Strategy DSL configuration.

It cannot generate arbitrary executable production code.

The configuration is validated against:

- Available features.
- Supported operators.
- Permitted timeframes.
- Risk constraints.
- Strategy DSL schema.

Invalid configurations are rejected.

### C. Experiment Analyst

After experiments complete, the statistical engine produces a compact summary.

The LLM explains:

- What changed.
- Why performance improved or deteriorated.
- Which market conditions mattered.
- Whether the improvement appears robust.
- What should be tested next.

The LLM must distinguish measured results from speculation.

### D. Strategy Failure Investigator

When a strategy underperforms, the LLM receives an aggregated failure report.

For example:

```json
{
  "strategy": "MOMENTUM_V3",
  "evaluation_period": "LAST_90_DAYS",
  "observations": {
    "trades": 84,
    "win_rate_change": -8.5,
    "expectancy_change": -21.0,
    "slippage_change": 12.0
  },
  "regime_distribution": {
    "trending": 0.25,
    "sideways": 0.55,
    "high_volatility": 0.20
  }
}
```

The LLM identifies potential explanations and proposes investigations.

It must not assume that a correlation establishes the cause of failure.

### E. Research Coordinator

This is the highest-level Gen AI capability.

It coordinates research activities.

For example:

- Review new alpha discoveries.
- Check whether similar hypotheses have already been tested.
- Identify gaps in the research library.
- Request additional experiments.
- Review completed experiments.
- Prepare a weekly research summary.

It should operate on structured research records rather than continuously consuming market data.

---

## 12.3 Token management strategy

I recommend a centralized LLM Gateway.

Every Gen AI request must go through it.

```text
              AI RESEARCH REQUEST
                       |
                  LLM GATEWAY
                       |
              CONTEXT RETRIEVAL
                       |
                DEDUPLICATION
                       |
                TOKEN ESTIMATION
                       |
                MODEL SELECTION
                       |
                 LLM PROVIDER
                       |
              STRUCTURED RESPONSE
                       |
                SCHEMA VALIDATION
                       |
                RESULT STORAGE
```

The gateway should implement:

| Mechanism | Purpose |
|---|---|
| Token budgets | Control consumption |
| Prompt templates | Avoid repeated prompt construction |
| Response caching | Avoid duplicate calls |
| Deduplication | Avoid repeated research |
| Model routing | Use cheaper models where possible |
| Batch processing | Combine related research tasks |
| Structured output | Reduce unnecessary text |
| Context limits | Prevent oversized prompts |
| Retry limits | Prevent uncontrolled spending |
| Usage tracking | Measure actual cost |

## 12.4 Suggested LLM invocation policy

| Event | LLM invocation |
|---|---|
| Every market tick | Never |
| Every minute | Never |
| Every indicator calculation | Never |
| Every trading signal | Never |
| Every completed trade | No |
| Significant strategy degradation | Conditional |
| New statistically interesting discovery | Yes |
| Experiment batch completed | Yes |
| Weekly research review | Yes |
| New strategy promotion proposal | Yes, as an independent reviewer |
| Monthly portfolio review | Yes |

We should also avoid invoking the LLM separately for every strategy variation.

One research request can contain aggregated results from hundreds of experiments.

## 12.5 Token budget

The owner set the starting limits on 2026-11-14: a hard monthly budget of 250,000 tokens and a spending cap of Rs 1,000, both enforced by the gateway. The table below is this document's earlier proposal of 1 million tokens, kept for the shape of the split only; scale it to the limit.

This is a proposed engineering budget, not a prediction of actual usage.

Example allocation:

| Activity | Monthly budget |
|---|---:|
| Hypothesis generation | 200,000 |
| Experiment analysis | 250,000 |
| Strategy failure analysis | 150,000 |
| Research coordination | 150,000 |
| Validation review | 150,000 |
| Reserve | 100,000 |
| **Total** | **1,000,000** |

We should track input and output tokens separately.

The system should support configurable daily and monthly limits.

When a budget is exhausted:

- Statistical research continues.
- Backtesting continues.
- Trading continues under existing approved rules.
- New AI research requests are queued.
- No production functionality is disabled merely because an LLM budget is exhausted.

## 12.6 Model selection

Use a tiered model architecture.

| Workload | Model class |
|---|---|
| Hypothesis generation | Low-cost reasoning model |
| Structured strategy generation | Low-cost capable model |
| Complex research investigation | Higher-capability reasoning model |
| Independent strategy review | Different model or independent statistical validator |
| Report summarization | Small, inexpensive model |

We should benchmark models on our actual research tasks before choosing providers.

Do not assume the most expensive model produces the best trading research.

## 12.7 LLM output requirements

Every research agent must return structured output.

Example:

```json
{
  "conclusion": "CANDIDATE_FOR_FURTHER_TESTING",
  "observations": [
    "Momentum performance varies across market regimes"
  ],
  "hypotheses": [
    {
      "description": "Test market breadth as an entry filter",
      "experiment_type": "FEATURE_COMBINATION",
      "priority": "HIGH"
    }
  ],
  "confidence": "MEDIUM",
  "limitations": [
    "Historical relationship does not establish causality"
  ]
}
```

The output must pass schema validation.

The LLM cannot write directly to production strategy configurations.

---

# 13. Strategy Evolution Engine

This component enables the system to improve existing strategies automatically.

It should operate on an immutable strategy population.

## 13.1 Evolution methods

Initially support:

- Parameter optimization.
- Feature addition/removal.
- Entry condition variations.
- Exit condition variations.
- Position-sizing variations.
- Genetic algorithms.
- Bayesian optimization.

## 13.2 Evolution example

```text
MOMENTUM_V1
     |
     +---- V1.1
     |       Different entry threshold
     |
     +---- V1.2
     |       Sector confirmation
     |
     +---- V1.3
     |       Volatility-adjusted sizing
     |
     +---- V1.4
             Fundamental confirmation
                 |
              VALIDATION
                 |
            PAPER TRADING
                 |
           PROMOTION REVIEW
```

## 13.3 Evolution rules

The system must:

1. Preserve the parent strategy.
2. Record the reason for each variation.
3. Limit the number of experiments.
4. Prevent unrestricted parameter exploration.
5. Evaluate candidates on unseen data.
6. Reject unstable improvements.
7. Record failed experiments.
8. Never promote based only on backtest returns.

Evolution should optimize robustness, not just profitability.

---

# 14. Portfolio Intelligence

This component decides how much capital each approved strategy should receive.

The objective is not to find the single best strategy.

It is to build the best combination of strategies.

## 14.1 Strategy allocation inputs

- Expected returns.
- Historical volatility.
- Drawdown.
- Recent performance.
- Strategy correlation.
- Market regime.
- Liquidity.
- Turnover.
- Capacity.
- Risk contribution.

## 14.2 Allocation methods

Start with:

- Equal risk allocation.
- Volatility targeting.
- Risk parity.
- Constrained mean-variance optimization.

Later investigate:

- Hierarchical Risk Parity.
- Robust portfolio optimization.
- Bayesian portfolio allocation.
- Online allocation algorithms.

## 14.3 Portfolio controls

Example configuration:

```yaml
portfolio:
  max_total_exposure: 100
  max_single_strategy_allocation: 35
  max_single_stock_exposure: 5
  max_sector_exposure: 25
  allow_leverage: false
  allow_short_selling: false

risk:
  max_daily_loss: configurable
  max_drawdown: configurable
  max_open_positions: configurable
```

These are illustrative initial limits, not final risk recommendations.

The risk engine must calculate aggregate exposure across all strategies.

Two strategies independently holding the same stock must not bypass portfolio-level limits.

---

# 15. Intraday Intelligence

Since we have 10 years of one-minute data across 2,100+ stocks, intraday research deserves its own subsystem.

However, the current daily backtesting engine cannot simply be reused as an intraday simulator.

## 15.1 Intraday strategy categories

- Opening range breakout.
- VWAP reversion.
- Momentum continuation.
- Volume breakout.
- Volatility expansion.
- Intraday mean reversion.
- Multi-timeframe trend following.
- Relative strength versus sector.

## 15.2 Intraday backtesting requirements

Before intraday strategies can be approved, implement:

- Minute-level order execution.
- Bid/ask spread modelling where data is available.
- Slippage.
- Market impact assumptions.
- Partial fills.
- Liquidity constraints.
- Intraday trading charges.
- Exchange trading sessions.
- Auction and special-session handling where applicable.
- Circuit limits.
- Order rejection handling.
- Intraday square-off rules.
- Next-bar execution rules.

A one-minute OHLCV bar cannot tell us the exact sequence of trades inside that minute.

Therefore, the simulator must use conservative assumptions when the precise execution path is unknown.

## 15.3 Multi-timeframe intelligence

A useful strategy could combine:

```text
DAILY:
Long-term trend is positive
          |
          v
HOURLY:
Sector momentum is positive
          |
          v
15 MIN:
Stock breakout confirmed
          |
          v
5 MIN:
Entry conditions satisfied
          |
          v
RISK ENGINE:
Position size approved
          |
          v
EXECUTION:
Order submitted
```

This is an example of a possible strategy architecture, not a claim of profitability.

---

# 16. Continuous Learning and Monitoring

VTI should operate continuously.

However, different activities should have different execution frequencies.

| Process | Frequency |
|---|---|
| Live data ingestion | Continuous |
| Live feature updates | Event-driven |
| Market regime detection | Every minute / configured interval |
| Trading signal evaluation | Strategy-specific |
| Risk evaluation | Before every order and continuously for active positions |
| Trade outcome recording | On execution events |
| Strategy health monitoring | Daily and rolling windows |
| Model drift detection | Daily / event-driven |
| Alpha discovery | Scheduled research jobs |
| Strategy experiments | Background queue |
| LLM research analysis | Event-triggered |
| Research report | Weekly |
| Model retraining | Drift-triggered or scheduled |
| Portfolio review | Daily / weekly |

The system should use event-driven processing wherever practical.

We should not run expensive full-universe calculations every minute if incremental calculations can produce the same result.

# 17. Risk Management and Autonomous Execution

This is the most sensitive subsystem.

The intelligence system can recommend trades, but the risk engine has final authority.

## 17.1 Risk hierarchy

```text
PORTFOLIO RISK
      |
      v
STRATEGY RISK
      |
      v
INSTRUMENT RISK
      |
      v
ORDER RISK
      |
      v
EXECUTION APPROVAL
```

Each level must independently enforce its limits.

## 17.2 Mandatory safeguards

| Safeguard | Requirement |
|---|---|
| Daily loss limit | Hard limit |
| Maximum drawdown | Hard limit |
| Position size | Risk-adjusted |
| Sector exposure | Restricted |
| Instrument exposure | Restricted |
| Liquidity | Minimum requirement |
| Strategy degradation | Automatic review |
| Data quality failure | Block new orders |
| Broker connectivity failure | Safe execution state |
| Duplicate orders | Prevented |
| Order reconciliation | Mandatory |
| Emergency stop | Independent kill switch |

## 17.3 Autonomous strategy lifecycle

The system can automatically:

- Monitor strategies.
- Identify deterioration.
- Recommend reducing allocation.
- Suspend strategies according to predefined rules.
- Evaluate replacement strategies.
- Recommend promotion of new candidates.

It cannot bypass risk limits to recover losses.

## 17.4 Live deployment stages

| Stage | Description |
|---|---|
| Stage 0 | Historical backtesting |
| Stage 1 | Independent validation |
| Stage 2 | Paper trading |
| Stage 3 | Limited-capital live trading |
| Stage 4 | Controlled capital scaling |
| Stage 5 | Autonomous allocation within approved limits |

Initially, human approval should be mandatory for live strategy promotion and material risk-policy changes.

---

# 18. Research Console

The existing Next.js Research Console should become the control center for VTI.

I would introduce the following sections.

| Section | Purpose |
|---|---|
| Intelligence Dashboard | Overall system health |
| Market Intelligence | Current market conditions |
| Alpha Discovery | Discovered predictive relationships |
| Hypothesis Library | Research ideas |
| Strategy Factory | Generated strategies |
| Experiment Laboratory | Running and completed experiments |
| Validation Center | Statistical evaluation |
| Strategy Registry | All strategy versions |
| Strategy Evolution | Strategy lineage |
| Learning Center | Trading lessons and observations |
| Portfolio Intelligence | Strategy allocation |
| Risk Center | Exposure and limits |
| AI Research Center | Gen AI activity and token consumption |
| Research Reports | Automated findings |
| Audit Center | Complete decision history |

## 18.1 Intelligence Dashboard

It should display:

- Current market regime.
- Active strategies.
- Strategies under evaluation.
- New alpha discoveries.
- Experiments running.
- Experiments completed.
- Strategies rejected.
- Strategies promoted.
- Strategies degrading.
- Current portfolio exposure.
- Live P&L.
- Risk utilization.
- Data quality.
- AI token consumption.

## 18.2 AI Research Center

This deserves a dedicated dashboard.

Display:

- Total tokens used.
- Input versus output tokens.
- Monthly budget utilization.
- Cost by agent.
- Cost by research activity.
- Cache hit rate.
- Failed requests.
- Average response time.
- Research hypotheses generated.
- Hypotheses accepted for experimentation.
- Hypotheses rejected.

We should measure research productivity, not just token consumption.

---

# 19. Technical Architecture and Services

I recommend implementing VTI as a modular subsystem within the existing platform.

Do not immediately create a microservice for every intelligence component.

Start with clear module boundaries and independently scalable background workers.

## 19.1 Logical components

| Component | Responsibility |
|---|---|
| `market-intelligence` | Regime and market analysis |
| `feature-engine` | Feature calculation |
| `alpha-discovery` | Predictive relationship discovery |
| `strategy-factory` | Strategy generation |
| `experiment-engine` | Experiment execution |
| `validation-engine` | Robustness and statistical validation |
| `learning-engine` | Outcome analysis |
| `portfolio-intelligence` | Capital allocation |
| `ai-research-orchestrator` | LLM orchestration |
| `risk-engine` | Independent risk enforcement |

These are logical module names, not a mandate to deploy ten independent services.

## 19.2 Suggested technology stack

| Area | Technology |
|---|---|
| Core backend | Existing Python / FastAPI |
| Market storage | PostgreSQL / TimescaleDB |
| Historical analytics | Postgres and the raw lake today; DuckDB / Parquet only if measured need |
| Numerical computation | NumPy |
| Data processing | Existing code first; Polars only if measured need |
| Statistics | SciPy / Statsmodels (add when a phase needs them) |
| Machine learning | Scikit-learn (Phase 2) |
| Gradient boosting | XGBoost / LightGBM (Phase 2, if needed) |
| Deep learning | Not planned |
| Optimization | Optuna (Phase 3, if needed) |
| Experiment workers | Python |
| Messaging | None (the platform uses Postgres; no Kafka in v1) |
| LLM integration | Centralized, provider-isolated AI Gateway; optional, off by default |
| Frontend | Existing Next.js Research Console |
| Monitoring | Prometheus / Grafana |

Avoid introducing additional infrastructure until there is a measurable need.

## 19.3 Resource isolation

Research jobs must not interfere with live trading.

Use separate worker pools:

```text
LIVE WORKERS
    |
    +-- Market features
    +-- Signals
    +-- Risk
    +-- Execution

RESEARCH WORKERS
    |
    +-- Alpha discovery
    +-- Backtesting
    +-- Optimization
    +-- ML training

AI WORKERS
    |
    +-- Hypothesis generation
    +-- Research analysis
    +-- Reporting
```

Live trading should have reserved CPU, memory and database capacity.

---

# 20. Database Design

The following represents proposed logical tables.

**Superseded (2026-11-14):** no parallel `vti_*` tables. Experiments, runs, metrics, strategy versions, lifecycle, evaluations,
promotion reviews and the audit log extend the existing `experiment`, `study_trial`, `study_run`, `validation_report`,
`study_holdout`, `backtest_run`, `strategy_config`, `strategy_stage_change` and `portal_audit` tables (mapping in
`docs/vti-alignment.md` section 5). Only the feature definition, feature value and feature run records are new, plus later the
research memory and AI usage tables. The list below is the conceptual inventory, not a schema.

| Table | Purpose |
|---|---|
| `vti_feature_definitions` | Feature definitions |
| `vti_feature_versions` | Feature version history |
| `vti_alpha_hypotheses` | Discovered hypotheses |
| `vti_alpha_evaluations` | Alpha evaluation results |
| `vti_research_experiments` | Experiment metadata |
| `vti_experiment_runs` | Individual experiment executions |
| `vti_experiment_metrics` | Experiment performance |
| `vti_strategy_definitions` | Strategy definitions |
| `vti_strategy_versions` | Immutable strategy versions |
| `vti_strategy_lineage` | Parent-child relationships |
| `vti_strategy_evaluations` | Validation results |
| `vti_strategy_allocations` | Portfolio allocations |
| `vti_strategy_observations` | Strategy health observations |
| `vti_trade_learning_records` | Trade outcome analysis |
| `vti_market_regimes` | Market regime history |
| `vti_research_memory` | Structured research knowledge |
| `vti_ai_requests` | LLM request records |
| `vti_ai_usage` | Token consumption |
| `vti_ai_agent_runs` | Agent execution history |
| `vti_promotion_reviews` | Strategy promotion decisions |
| `vti_audit_log` | Decision audit history |

All experiments, strategies and AI-generated proposals must be traceable.

---

# 21. Implementation Roadmap

I recommend six development phases.

These are engineering phases, not fixed delivery estimates.

## Phase 1 — Research Foundation

**Objective:** Make the existing data and research capabilities accessible to VTI.

Deliverables:

- Unified research data access.
- Data quality validation.
- Point-in-time dataset construction.
- Feature registry.
- Feature computation engine.
- Research dataset versioning.
- Historical instrument universe reconstruction.

Prerequisites and specification: `docs/vti-phase1-spec.md` (holdout lock, dataset reference, feature registry for daily features,
point-in-time checks, reproducibility). Nifty 200 first; membership must be verified and loaded before any experiment is called
point-in-time.

Acceptance criteria:

- Features can be reproduced.
- No future data leakage.
- Historical stock membership is respected.
- Corporate actions are correctly handled.
- Every experiment references a dataset version.

## Phase 2 — Alpha Discovery

**Objective:** Enable automated discovery of market relationships.

Deliverables:

- Technical feature research.
- Fundamental feature research.
- Cross-sectional research.
- Multi-horizon return analysis.
- Correlation and information coefficient analysis.
- ML-based feature discovery.
- Alpha hypothesis registry.
- Automated discovery reports.

Acceptance criteria:

- Discoveries are reproducible.
- Every hypothesis has supporting evidence.
- Failed hypotheses are retained.
- Multiple-testing risks are accounted for.

## Phase 3 — Strategy Factory and Experiment Engine

**Objective:** Generate and evaluate strategies automatically.

Deliverables:

- Strategy DSL.
- Strategy factory.
- Experiment orchestrator.
- Parameter optimization.
- Feature combination experiments.
- Strategy versioning.
- Backtesting integration.
- Statistical validation.
- Experiment comparison.

Acceptance criteria:

- Strategies can be generated without manually writing Python.
- Every strategy version is immutable.
- Experiments are reproducible.
- Candidates cannot bypass validation.

## Phase 4 — Self-Learning and Gen AI

**Objective:** Introduce research reasoning and automated improvement.

Deliverables:

- Trade learning engine.
- Strategy degradation detection.
- Research memory.
- Hypothesis generation agent.
- Experiment analyst.
- Strategy failure investigator.
- AI gateway.
- Token budget enforcement.
- Research reports.

Acceptance criteria:

- LLM requests are event-driven.
- All token consumption is tracked.
- LLM failure does not affect production trading.
- AI outputs are schema-validated.
- AI cannot directly deploy strategies.

## Phase 5 — Portfolio Intelligence

**Objective:** Manage multiple strategies dynamically.

Deliverables:

- Market regime detection.
- Strategy correlation analysis.
- Capital allocation.
- Risk contribution.
- Strategy health monitoring.
- Automatic allocation recommendations.
- Portfolio-level safeguards.

Acceptance criteria:

- Portfolio risk is calculated across strategies.
- Capital allocation respects hard limits.
- Degraded strategies can be suspended.
- Allocation changes are auditable.

## Phase 6 — Autonomous Trading

**Gate before this phase:** a regulatory assessment of automated strategy generation, decision-making and order placement, use by
other users and any later advisory or managed offering (`docs/vti-alignment.md` section 8). Personal capital only in v1; the
shared Kite account's hand-bought shares are never touched.

**Objective:** Deploy validated strategies with controlled autonomy.

Deliverables:

- Intraday backtesting.
- Paper trading.
- Broker execution integration.
- Order reconciliation.
- Strategy promotion workflow.
- Automated monitoring.
- Controlled capital scaling.
- Emergency suspension.

Acceptance criteria:

- Paper trading matches expected execution assumptions within defined tolerances.
- Broker positions reconcile with internal positions.
- Risk controls operate independently.
- Failed infrastructure dependencies result in safe behaviour.
- All live decisions are reproducible.

---

# 22. What We Should Explicitly Avoid

There are several tempting approaches that I would reject.

| Approach | Why we should avoid it |
|---|---|
| LLM analyzes every minute of every stock | Expensive and unnecessary |
| LLM directly predicts stock prices | Poor use of LLM capabilities |
| LLM writes and executes arbitrary Python | Security and reproducibility risks |
| Automatically deploy every profitable backtest | Severe overfitting risk |
| Reinforcement learning as the first priority | Difficult to validate reliably |
| One giant AI agent controlling everything | Poor separation of responsibilities |
| Train deep learning models on everything immediately | Complexity without proven benefit |
| Change strategy after every losing trade | Overreaction to noise |
| Use today's stock universe for historical research | Survivorship bias |
| Optimize only for CAGR | Encourages excessive risk |

---

# 23. Measuring Intelligence

We need to measure whether VTI is actually becoming better.

I would introduce the following metrics.

| Metric | What it measures |
|---|---|
| Hypotheses generated | Research productivity |
| Hypothesis acceptance rate | Research relevance |
| Experiment completion rate | Research throughput |
| Experiment reproducibility | Research quality |
| Out-of-sample success rate | Discovery quality |
| Strategy survival rate | Robustness |
| Strategy degradation detection time | Monitoring intelligence |
| False promotion rate | Validation quality |
| Portfolio risk-adjusted returns | Portfolio quality |
| Research cost per validated discovery | Research efficiency |
| AI token cost per accepted hypothesis | AI efficiency |
| Human intervention rate | Autonomy |

One metric deserves particular attention:

**Cost per independently validated trading edge.**

We should optimize the system to discover genuine, repeatable trading advantages at lower research cost.

Generating 10,000 strategies is not an achievement if none survives independent validation.

---

# 24. Final Target Architecture

The long-term system should look like this:

```text
             VINAYAK-TRADING INTELLIGENCE
                           |
             CONTINUOUS MARKET INTELLIGENCE
                           |
             HISTORICAL + LIVE DATA ANALYSIS
                           |
                  ALPHA DISCOVERY
                           |
                 AUTONOMOUS RESEARCH
                           |
                   STRATEGY FACTORY
                           |
                 EXPERIMENT LABORATORY
                           |
                INDEPENDENT VALIDATION
                           |
                 STRATEGY KNOWLEDGE
                           |
                STRATEGY EVOLUTION
                           |
                PORTFOLIO INTELLIGENCE
                           |
                    RISK ENGINE
                           |
                 AUTONOMOUS EXECUTION
                           |
                      ZERODHA
                           |
                  PERFORMANCE ANALYSIS
                           |
                    SELF-LEARNING
                           |
                  RESEARCH FEEDBACK
                           |
                      REPEAT
```

Generative AI operates as an intelligence and research coordination layer across this architecture, not as its computational foundation.

---

# 25. My Implementation Priorities

If I were leading the engineering work, I would make these decisions:

| Priority | Deliverable |
|---|---|
| P0 | Unified point-in-time research dataset |
| P0 | Feature Intelligence Engine |
| P0 | Alpha Discovery Engine |
| P0 | Strategy DSL and Strategy Factory |
| P0 | Experiment Orchestrator |
| P0 | Independent Validation Engine |
| P1 | Market Regime Intelligence |
| P1 | Self-Learning Engine |
| P1 | Gen AI Research Gateway |
| P1 | Strategy Evolution |
| P1 | Portfolio Intelligence |
| P2 | Intraday execution simulator and research |
| P2 | Autonomous research agents |
| P3 | Reinforcement learning |

I would not begin with multi-agent AI.

First, build the quantitative research engine that produces reliable, structured evidence. Then introduce AI agents to reason over that evidence.

This is the most cost-efficient and technically sound approach.

---

## 26. Definition of Done: What Vinayak-Trading Should Eventually Be Able to Do

Imagine the following scenario.

The system detects a change in market behaviour.

It independently:

1. Identifies the change.
2. Investigates which existing strategies are affected.
3. Searches its research memory for related historical observations.
4. Generates new hypotheses.
5. Creates strategy variations.
6. Runs experiments across historical data.
7. Tests candidates on unseen data.
8. Rejects overfitted candidates.
9. Sends promising candidates to paper trading.
10. Evaluates actual execution performance.
11. Recommends strategy promotion.
12. Adjusts capital allocation within approved limits.
13. Monitors the resulting portfolio.
14. Learns from subsequent outcomes.

No developer needs to manually create every experiment.

No LLM needs to analyze every stock or market tick.

No strategy can bypass risk management.

And every discovery, experiment, decision and outcome remains auditable.

**That is the standard I would set for Vinayak-Trading.**

The ultimate goal is not an AI trading bot.

It is an autonomous quantitative research organization with its own market knowledge, experimentation capabilities, strategy development process and controlled capital allocation system.