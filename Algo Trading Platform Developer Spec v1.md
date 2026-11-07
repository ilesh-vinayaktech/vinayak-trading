# Algo Trading Platform: Developer Spec v1

Nov 6, 2026 · @IP

## 1. Goals, non-goals, principles

Build one platform that takes data from source to live order and back to a dashboard, where adding a new strategy, broker, or asset class means writing one adapter, not changing the core.

**Goals (v1)**

- End-to-end pipeline: ingest, store, research and backtest, paper trade, live trade, monitor.
- Asset-agnostic: Indian equities and futures first, then US equities and crypto without schema changes.
- Strategy-pluggable: any algorithm implemen ts one interface and runs unchanged in backtest, paper, and live.
- Reproducible: any backtest can be re-run from (code version, data snapshot, config) and give the same result.

**Non-goals (v1)**

- High-frequency or sub-second trading, and options market-making.
- News or NLP signals (add after quantitative layers prove their worth).
- Multi-user SaaS, billing, or tenant isolation. Single owner, single deployment.
- A general ML platform. Models are plugged in as strategy components.

**Design principles**

1. **Raw is immutable, derived is rebuildable.** Store source files untouched. Every clean table can be regenerated from them.
2. **Point-in-time everywhere.** Every record carries `event_time` (when it happened) and `knowledge_time` (when we could have known it). Backtests only see data with `knowledge_time` before the simulated clock.
3. **One strategy interface, three runtimes.** Backtest, paper, and live differ only in the clock, the data feed, and the execution adapter.
4. **Everything external sits behind an adapter:** data provider, broker, exchange calendar.
5. **Costs and risk are first-class.** The cost model and risk limits are part of the engine, not strategy code.
6. **Store UTC, reason in exchange-local time.** Each exchange has its own calendar, sessions, and holidays.

**Scale assumptions (v1)**

Universe of about 500 Indian equities plus index futures, 1-minute bars with 5 to 10 years of history, about 20 global and macro series, and one VM. This is roughly 470 million 1-minute rows at full depth, which a compressed Postgres-based store handles comfortably.

## 2. Technology decisions

Use PostgreSQL with TimescaleDB as the single system of record, Parquet files as the raw lake, and Dagster to orchestrate. This keeps one database for both time series and transactional data (orders, positions), which avoids syncing two systems at this scale.

| Concern | Choice | Why | Revisit when |
| --- | --- | --- | --- |
| Time-series + relational store | PostgreSQL 16 + TimescaleDB | SQL, ACID for orders and positions, hypertables, native compression, continuous aggregates for 1m to 15m to 1d bars | Tick data or crypto order books exceed about 5 TB, then add ClickHouse as an analytical replica |
| Raw lake | Parquet on S3-compatible storage (MinIO locally, S3 in cloud), partitioned by `source/dataset/date` | Immutable, cheap, replayable, readable by any tool | Never; this is the permanent layer |
| Research queries | DuckDB and Polars over Parquet, pandas at the edges | Fast columnar scans without loading the DB; notebooks stay lightweight | Datasets stop fitting one machine |
| Orchestration | Dagster (asset-based, partitioned backfills) | Daily partitions, lineage, retries, alerts, and one-click backfill of a missed day match this workload | Team grows or you already run Airflow |
| Live event bus | Redis Streams | Simple, durable enough for single-node live bars and signals | Multiple consumers across hosts, then NATS JetStream; Kafka only at much larger scale |
| Language | Python 3.12, typed (pydantic, mypy), packaged with uv | Research and production share one codebase | A strategy needs microsecond latency |
| API | FastAPI | Typed, async, auto-generated OpenAPI | n/a |
| Dashboards | Grafana on Postgres for data health and P&L first; custom React UI later for strategy control | Fastest path to useful visibility without building a frontend | You need order entry or strategy toggles in the UI |
| Experiment tracking | MLflow, or plain `backtest_runs` tables | Every run stores code hash, data snapshot, params, metrics | n/a |
| Deployment | Docker Compose on one VM in AWS ap-south-1 (Mumbai) with an Elastic IP | Static IP is required for broker API whitelisting; Kubernetes adds cost without benefit at this size | More than one live runner or HA requirement |
| Secrets | Cloud secrets manager or SOPS-encrypted files; never in git or images | Broker keys can place real orders | n/a |

**Why not the alternatives**

- **InfluxDB:** weak joins and a query language that has changed across versions. Our queries join prices, corporate actions, and fundamentals constantly.
- **kdb+:** excellent, but licensing and talent cost are unjustified here.
- **QuestDB:** fast ingestion and SQL, but a smaller ecosystem and weaker support for the relational side.
- **ClickHouse as the primary store:** faster scans, but poor fit for updates and transactional order state. Kept as a later analytical replica.
- **A pure file lake (Parquet only):** fine for research, but live trading needs transactional order and position state.

## 3. System architecture

&#91;embedded content: system architecture · 6 layers, 1 broker gateway\]

Data moves down from sources into storage, strategies read it only through the `Context` object, and every order passes the risk engine and the single OMS. The dashboard reads every table, and its controls go through the OMS.

**Deployable services (Docker Compose)**

- `dagster-daemon` and `dagster-webserver`: schedules, sensors, backfills, run history.
- `timescaledb`: the system of record. `minio`: the raw lake in dev (S3 in prod). `redis`: live streams.
- `marketdata`: Kite WebSocket to bars on the exchange calendar.
- `runner`: loads strategy plugins and feeds them bars. One process per live strategy group.
- `portfolio-risk` and `oms`: the only path to a broker. `reconciler`: independent watchdog.
- `api` (FastAPI), `grafana`, `prometheus`, `alertmanager`.

**Data flow in one sentence per mode**

- **Research:** query Parquet and Timescale through the data API, run the backtest engine, store the run and its tear sheet.
- **Paper and live:** `marketdata` builds bars, `runner` calls the strategy, `portfolio-risk` approves targets, `oms` places orders through the chosen broker adapter, fills flow back to Timescale and the dashboard.

## 4. Instrument master and multi-asset model

Every tradable or observable thing gets a surrogate `instrument_id`, and nothing downstream ever keys on a ticker string. This is what lets US stocks and crypto be added later as data, not as code changes.

| Table | Purpose | Key fields |
| --- | --- | --- |
| `exchange` | One row per venue | `exchange_id`, `mic`, `country`, `timezone` (IANA), `currency`, `calendar_id` |
| `instrument` | Everything we trade or track | `instrument_id`, `asset_class`, `exchange_id`, `symbol`, `isin`, `name`, `quote_currency`, `lot_size`, `tick_size`, `qty_step`, `listed_on`, `delisted_on`, `status`, `meta` (jsonb) |
| `instrument_derivative` | Futures and options detail | `instrument_id`, `underlying_id`, `expiry`, `strike`, `option_type`, `multiplier` |
| `instrument_alias` | Maps our ID to each provider's identifier, with validity dates | `instrument_id`, `source` (kite, nse, binance), `source_symbol`, `source_token`, `valid_from`, `valid_to` |
| `index_membership` | Historical index constituents | `index_id`, `instrument_id`, `valid_from`, `valid_to` |
| `trading_calendar` and `trading_session` | Holidays, session open and close per exchange per day | `calendar_id`, `date`, `open_utc`, `close_utc`, `is_open` |
| `fx_rate` | Currency conversion series | `base`, `quote`, `ts`, `rate` |

**Asset classes supported by the enum:** `equity`, `etf`, `index`, `future`, `option`, `fx`, `crypto_spot`, `crypto_perp`, `macro_series`. Adding one is an enum value plus a provider adapter.

**Rules that make multi-asset work**

- **Quantities and prices use `NUMERIC`, not floats**, so fractional crypto quantities and tick-size rounding are exact. Order sizing always snaps to `lot_size`, `qty_step`, and `tick_size` from this table.
- **Symbol changes, mergers, and ISIN changes are handled through `instrument_alias` and `valid_from/valid_to`.** The `instrument_id` never changes, so history stays linked across renames.
- **Delisted instruments are never deleted.** They get a `delisted_on` date. This is what keeps the dataset survivorship-bias-free.
- **Calendars are per exchange.** NSE has fixed sessions and holidays, US markets follow DST and have extended hours, and crypto is 24/7 with no session. The engine asks the calendar for "next bar boundary" and never hard-codes 09:15 to 15:30.
- **Expired futures and options are separate `instrument_id` rows** with their own expiry. Continuous contracts (for example NIFTY near-month) are a derived view, built with a documented roll rule.
- **Base currency is INR.** P&L and risk are reported in INR, and foreign instruments convert through `fx_rate` at the bar timestamp.
- **Daily refresh job** downloads the Zerodha instrument dump and the NSE security master, diffs against `instrument`, and writes changes with a timestamp. It raises an alert when a held instrument changes status.

## 5. Storage layer

Data lives in three tiers: an immutable raw lake, a normalized TimescaleDB layer, and derived tables. Everything above the raw tier can be dropped and rebuilt.

| Tier | Where | Contents | Mutability |
| --- | --- | --- | --- |
| Raw | Parquet or original files in object storage, path `raw/{source}/{dataset}/dt=YYYY-MM-DD/` plus a manifest with checksum, fetch time, and source URL | Bhavcopy, Kite candles, XBRL filings, FRED responses, crypto trades | Append-only, never edited |
| Core | TimescaleDB hypertables and normal tables | Normalized bars, corporate actions, fundamentals, orders, positions | Written only by pipeline jobs |
| Derived | Continuous aggregates and materialized tables | 15m and 1d bars, adjusted prices, features, signals | Rebuildable at any time |

**Core tables**

| Table | Type | Key and partitioning | Notes |
| --- | --- | --- | --- |
| `bar_1m` | Hypertable | (`instrument_id`, `ts`), chunk 7 days, space-partition on `instrument_id` | Columns `open, high, low, close, volume, oi, source, ingested_at`. Compress chunks older than 14 days, segment by `instrument_id` |
| `bar_15m`, `bar_1d` | Continuous aggregates over `bar_1m`; `bar_1d` is also loaded from bhavcopy | Same key | Aggregation uses exchange sessions, so the first 15m bar starts at 09:15 IST |
| `tick` (phase 3) | Hypertable | (`instrument_id`, `ts`, `seq`) | Only for live capture and crypto; short retention, roll up to bars |
| `corporate_action` | Table | (`instrument_id`, `ex_date`, `action_type`) | Split, bonus, dividend, rights, merger, with `ratio`, `amount`, `announced_at` |
| `adj_factor` | Derived table | (`instrument_id`, `ts`) | Cumulative adjustment factor; adjusted price = raw price times factor, computed at read time, so raw bars are never modified |
| `fundamental` | Table | (`instrument_id`, `metric`, `period_end`, `knowledge_time`) | Point-in-time: a restated value is a new row with a later `knowledge_time`, never an update |
| `macro_series` | Hypertable | (`series_id`, `ts`) | Global indices, yields, VIX, USDINR, FII/DII flows. Carries `event_time` and `available_at` |
| `feature_value` | Hypertable | (`feature_id`, `instrument_id`, `ts`) | Computed features with `feature_version`, so a change in definition never overwrites old values |
| `signal` | Hypertable | (`strategy_run_id`, `instrument_id`, `ts`) | Target weights or positions emitted by strategies |
| `backtest_run`, `backtest_trade`, `backtest_equity` | Tables | `run_id` | Config, code hash, data snapshot id, metrics, trades, equity curve |
| `order`, `fill`, `position`, `portfolio_snapshot` | Tables | `order_id`, etc. | ACID; one row per state change in `order_event` for a full audit trail |
| `job_run`, `dq_result` | Tables | `run_id` | Pipeline run history and data-quality check results |

**Conventions**

- All timestamps are `TIMESTAMPTZ` in UTC. Bar `ts` means bar-open time. This must be documented once and tested everywhere.
- Every ingested row carries `source` and `ingested_at`, so you can trace any number back to a raw file.
- Raw bars from different providers coexist with a `source` column, and a `bar_canonical` view picks the preferred source per instrument and day. This enables cross-provider reconciliation.
- **Snapshots:** a `data_snapshot` row (id, as-of time, table watermarks) is created before each backtest. Because rows are append-only with `ingested_at`, a run can be reproduced by filtering to that snapshot.
- **Retention:** keep 1m bars forever (compressed), ticks for 30 to 90 days, raw files forever.
- **Backups:** daily `pg_dump` or WAL archiving to object storage, and a monthly restore test. An untested backup does not count.

## 6. Ingestion pipeline

Every data source is a `DataProvider` adapter that returns raw payloads. A fixed pipeline then runs fetch, store raw, parse, validate, load, and publish. Adding a source means writing one adapter and registering its datasets.

**Provider interface**

```python
class DataProvider(Protocol):
    name: str

    def datasets(
        self,
    ) -> list[DatasetSpec]: ...  # what it can supply, with cadence and history depth
    def fetch(self, dataset: str, partition: Partition) -> RawPayload: ...
    def parse(
        self, raw: RawPayload
    ) -> Iterable[Record]: ...  # pure function, unit-testable offline
    def rate_limit(self) -> RateLimit: ...
```

**Pipeline stages (per dataset, per daily partition)**

1. **Fetch** with retries, exponential backoff, and the provider's rate limit. Write the raw file and its manifest (checksum, URL, fetch time) to the lake.
2. **Parse** raw into typed records. Parsing is deterministic and never touches the network, so it can be re-run on old raw files after a bug fix.
3. **Validate** with data-quality checks (below). Failed checks quarantine the partition instead of loading it.
4. **Load** idempotently with `INSERT ... ON CONFLICT DO NOTHING` (or an upsert keyed on the natural key), so re-running a day never duplicates data.
5. **Publish** the Dagster asset as materialized, which triggers downstream aggregates and features.

**Datasets and schedules (all times IST, trading days only unless noted)**

| Dataset | Source | Schedule | Notes |
| --- | --- | --- | --- |
| NSE and BSE bhavcopy (EOD prices, delivery) | NSE and BSE archives | 18:30 daily, retry hourly until 23:30 | Source of truth for daily OHLCV and for reconciliation |
| 1-minute bars | Kite Connect historical API | 17:00 daily for the day just ended; one-time backfill by symbol and date range | Chunk requests to the API's per-call limit; respect rate limits |
| Instrument master | Kite instrument dump and NSE security master | 08:00 daily | Diffed against `instrument` |
| Corporate actions | NSE announcements | 20:00 daily | Triggers adjustment-factor rebuild for affected symbols |
| Financial results (XBRL) | NSE and BSE filings | Every 2 hours during results season, otherwise daily | Stored with filing timestamp as `knowledge_time` |
| Index levels, India VIX, FII and DII flows | NSE | 19:00 daily |  |
| Global indices, commodities, USDINR | Stooq or yfinance, with FRED as the primary for rates | 07:30 daily (covers the prior US and Asia closes) | Aligned per the timing rules in section 8 |
| FRED series (US yields, DXY proxy, Fed funds) | FRED API | 07:30 daily | Official API |
| US equities (phase 4) | Alpaca or Polygon | 06:30 daily | Market calendar in ET |
| Crypto (phase 4) | Binance public data and WebSocket | Continuous plus a daily REST reconciliation | UTC, 24/7 |

**Data-quality checks (run on every load, results stored in `dq_result`)**

- **Completeness:** expected bar count per instrument per session (375 one-minute bars for an NSE equity day), missing symbols versus the instrument master, and a file-size sanity check.
- **Validity:** high is at least max(open, close), low is at most min(open, close), no negative prices or volume, and prices inside the daily circuit limits.
- **Continuity:** daily return beyond a threshold with no matching corporate action is flagged as a probable unadjusted split.
- **Reconciliation:** aggregate 1-minute bars to a daily bar and compare with bhavcopy on open, high, low, close, and volume. A tolerance breach opens an alert.
- **Freshness:** each dataset has an SLA, and a missed SLA pages the owner.
- **Cross-provider:** sample symbols are compared between Kite and a second broker each week.

**Backfills and failure handling**

- Backfills are Dagster partition runs, one partition per day per dataset, resumable and rate-limited.
- A holiday calendar suppresses expected non-trading days. A trading day with no file is an incident.
- NSE endpoints change without notice: put all NSE access behind one client with header and cookie handling, record the raw HTTP status, and alert on any non-200 or schema change.
- Provider credentials and session tokens (Kite access tokens expire daily) are refreshed by a dedicated login job, and failure to refresh pages the owner before market open.

## 7. Corporate actions, adjustments, and point-in-time fundamentals

Raw prices are stored exactly as traded and never edited. Adjustment is applied at read time from a factor table, and fundamentals are stored by when they became public. These two rules prevent the two biggest silent backtest errors: unadjusted splits and look-ahead bias.

**Adjustment factors**

- Each action becomes a row in `corporate_action` with `ex_date`, type, and ratio or amount.
- `adj_factor(instrument_id, ts)` is the product of all later actions. Split and bonus: factor = 1 / ratio. Cash dividend: factor = 1 - dividend / previous close (total-return series only).
- Two series are exposed: **split-adjusted** (default for signals and charts) and **total-return adjusted** (for performance measurement and long-term strategies).
- Intraday bars use the same factor as their date, applied when read. Strategies request `adjusted=True` through the data API and never see the factor.
- Any new corporate action triggers a rebuild of that instrument's factors only, and a cache invalidation for backtests that used it.
- **Validation:** if the close-to-close move exceeds 20% with no matching action, flag it. If an action exists but no price discontinuity appears at its ex-date, flag it.

**Point-in-time fundamentals**

- Each filing is stored with `period_end`, `filed_at` (the exchange's acceptance timestamp), and `knowledge_time = filed_at`. Restatements are new rows, never edits.
- A query for "ROE of X as of date D" returns the latest row with `knowledge_time <= D`. This function (`fundamentals.as_of(instrument, metric, D)`) is the only way strategies read fundamentals.
- Add a configurable reporting lag (default: result usable from the next trading session after `filed_at`) so signals never trade on a number published after the close.
- Raw XBRL is kept in the lake. A mapping layer converts XBRL tags to a standard metric set (revenue, EBITDA, PAT, net debt, ROE, ROCE, operating cash flow, shares outstanding). Mapping versions are stored, so a mapping fix can be replayed.
- Standalone versus consolidated results are stored separately and a config chooses which one a factor uses.
- Derived factors (quality score, value ratios) are computed into `feature_value` with a `feature_version`.

**Historical index membership**

Rebuild constituents of Nifty 50, 100, 200, and 500 from NSE rebalancing circulars into `index_membership`. A backtest universe at date D is `index_membership` filtered to D. Without this, every universe-based backtest is survivorship-biased.

## 8. Global and macro data, and the feature layer

Global series are used as regime and risk inputs, not as stock-level predictors, and every one is aligned by availability timestamp, never by calendar date. This avoids the most common cross-market look-ahead error.

**Timestamp alignment rule**

Each macro record stores `event_time` (the market close or release time, in UTC) and `available_at` (the earliest moment we could have used it). A feature at India time T may only use records with `available_at <= T`. For example, the US close on day D (about 02:30 IST on D+1) is usable for India's D+1 session. Asian opens that precede the NSE open are usable intraday on the same date. The join is an as-of join on `available_at`, implemented once in the feature library.

**Initial macro universe**

- **Global equity:** S&P 500, Nasdaq 100, Nikkei 225, Hang Seng, DAX, FTSE, Shanghai Composite.
- **Rates and dollar:** US 10-year yield, US 2-year yield, Fed funds, dollar index proxy, USDINR.
- **Commodities:** Brent crude, gold.
- **Volatility:** US VIX, India VIX.
- **India flows:** FII and DII net buy/sell (cash and derivatives), NSE advance/decline.

**Feature layer**

- Features are pure functions: `f(data as of T) -> value`, registered with a `feature_id`, version, inputs, and warm-up length.
- Computed in batch by Dagster for research and incrementally by the live runner. **Both use the same function**, which removes training/serving skew.
- Stored in `feature_value`, keyed by feature version, so changing a definition creates a new version rather than overwriting.
- Feature families in v1: price (returns, momentum windows, volatility, ATR, distance from moving averages), liquidity (average traded value, spread proxy), fundamentals (quality, value, growth from `as_of`), cross-sectional ranks and z-scores, and macro regime inputs (VIX level and change, yield change, flow z-score).
- **Regime detector (optional plugin):** rule-based (VIX and trend thresholds) first. Statistical models such as HMM come after the rules prove their worth.

**Guardrail against feature sprawl:** every new feature must show an out-of-sample improvement in risk-adjusted return in the validation protocol (section 10) before it is allowed into a production strategy. The number of features and variants tested is logged for the deflated Sharpe calculation.

## 9. Strategy plugin interface

A strategy only decides what it wants to hold. It returns target positions, and the engine handles sizing limits, risk checks, cost modelling, order creation, and execution. This signal, portfolio, risk, execution split is the standard institutional layout and is what lets one strategy run unchanged in backtest, paper, and live.

**Contract**

```python
class Strategy(ABC):
    id: str; version: str
    Params: type[BaseModel]                      # validated config schema

    def universe(self, ctx: Context) -> list[InstrumentId]: ...   # point-in-time universe
    def requirements(self) -> Requirements: ...   # bar freq, lookback/warm-up, features, fundamentals, macro series
    def on_start(self, ctx: Context) -> None: ...
    def on_bar(self, ctx: Context, bars: BarBatch) -> Targets | None: ...      # event-driven (intraday, short-term)
    def on_schedule(self, ctx: Context) -> Targets | None: ...                 # rebalance-driven (daily, monthly, factor)
    def get_state(self) -> dict: ...  def set_state(self, s: dict) -> None: ...  # restart safety
```

`Targets` is a mapping of instrument to target weight or target quantity, plus optional metadata such as stop level, reason code, and confidence. Returning `None` means no change.

**The `Context` object is the only door to the outside world**

| Capability | Access | Guarantee |
| --- | --- | --- |
| `ctx.now()` | Simulated or real clock | Strategy never calls the system clock |
| `ctx.data.history(ids, fields, lookback, freq, adjusted)` | Bars | Cannot return anything after `ctx.now()`; bar is visible only after it closes |
| `ctx.features.get(feature_id, ids)` | Feature store | Same function in backtest and live |
| `ctx.fundamentals.as_of(id, metric)` | Point-in-time fundamentals | Uses `knowledge_time` and the reporting lag |
| `ctx.macro.get(series_id)` | Macro series | Uses `available_at` |
| `ctx.portfolio` | Cash, positions, equity, exposure | Read-only snapshot |
| `ctx.calendar` | Sessions, next bar boundary | Per exchange |
| `ctx.log`, `ctx.metrics` | Structured logging and custom metrics | Shown on the dashboard |

Strategies have no database handle, no broker handle, and no network access. This is what makes look-ahead bias structurally impossible rather than a matter of discipline.

**Pipeline between strategy and market**

1. **Signal:** `Targets` from one or more strategies.
2. **Portfolio construction:** combines strategies by capital allocation, applies position caps, turnover limits, and optional volatility targeting or risk parity.
3. **Risk engine:** pre-trade checks (section 11). A breach scales down or blocks.
4. **Execution:** converts target-versus-current into orders, snapped to lot and tick size, with the chosen execution style (market, limit with timeout, TWAP slicing).

**Packaging and registration**

- A strategy is a Python package exposing the entry-point group `algo.strategies`, plus a `strategy.yaml` manifest: `id`, `version`, class path, parameter defaults, supported asset classes, bar frequency, data requirements, default risk limits.
- The engine discovers strategies at start-up, validates the manifest, and refuses to run a strategy whose required data is not available.
- `strategy_version` is the git commit plus a hash of its parameters. It is stored on every run, order, and fill.

**Lifecycle and promotion gates**

| Stage | Gate to enter |
| --- | --- |
| Research | Manifest validates; unit tests pass |
| Backtest-approved | Passes the validation protocol in section 10 (walk-forward, costs, deflated Sharpe, robustness) |
| Paper | Runs on live data with simulated fills for at least 8 weeks; live-versus-backtest tracking error within agreed bounds |
| Live-small | Capital cap at 10% of target size for at least 4 weeks; no risk-limit breaches |
| Live-full | Manual approval recorded in the database |
| Retired | Drawdown or decay trigger fires, or manual decision. History is kept |

Stage changes are database records with an approver and a timestamp. The live runner refuses to start a strategy that is not in a live stage.

## 10. Research and backtesting engine

The canonical backtester is event-driven and uses the same `Context`, risk engine, and execution interface as live trading. A vectorized fast path is allowed for quick screening only, and any result must be confirmed in the event-driven engine before it counts.

**Build or adopt: decide with a time-boxed spike.** Spend one week evaluating NautilusTrader (open source, Python API, backtest and live parity, multi-asset). Adopt it if it handles NSE calendars, lot sizes, point-in-time fundamentals access, and a custom Kite adapter without fighting the framework. Otherwise build a lean engine (about 2,000 lines): the hard parts here are data, calendars, costs, and adapters either way. Do not use unmaintained libraries such as backtrader as a foundation.

**Simulation fidelity rules**

| Area | Rule |
| --- | --- |
| Signal timing | A decision made on the close of bar t executes no earlier than the open of bar t+1 |
| Order types | Market fills at next open plus slippage; limit fills only if price trades through the limit; stop orders fill at the worse of stop and next available price |
| Liquidity | Fill size capped at a configurable share of bar volume (default 5%); the remainder carries over or cancels |
| Price limits | No fills outside circuit limits; halted or suspended instruments cannot trade |
| Contract rules | Lot sizes, tick sizes, and fractional rules from the instrument master |
| Product type | Intraday positions are force-closed before session end; delivery versus intraday determines the charge schedule |
| Futures | Margin, mark-to-market, expiry, and roll handled explicitly |
| Cash | Cash, margin, and leverage are tracked; orders that exceed buying power are rejected as in live |

**Cost model (versioned)**

- A `cost_schedule` table holds every charge with an effective-from date: brokerage, STT or CTT by segment and side, exchange transaction charges, SEBI turnover fee, GST, stamp duty. The engine picks the schedule in force on each trade date. Rates change over time, so none are hard-coded; load current values from the exchange and broker published schedules and have a person verify them.
- **Slippage:** half the spread (or a proxy from bar range) plus a market-impact term proportional to volatility times the square root of order size over average daily volume. Calibrate against paper-trading fills as they accumulate.
- Every backtest reports results at 1x and 2x costs. A strategy that fails at 2x is fragile.

**Validation protocol (a strategy cannot be promoted without all of these)**

1. **Pre-register:** record the hypothesis, universe, and parameter ranges before running. Every run increments the trial counter for that idea.
2. **Freeze the data snapshot** and reserve the most recent 20 to 30% of history as an untouched holdout, opened once at the end.
3. **Walk-forward analysis:** rolling or anchored windows, with parameters chosen only on the in-sample portion. For ML components, use purged and embargoed cross-validation so labels never overlap training data.
4. **Parameter robustness:** the performance surface around the chosen parameters must be a plateau. Perturb each parameter by plus and minus 20% and require smooth degradation.
5. **Regime and period breakdown:** report by year and by market regime (bull, bear, high volatility, rate shock), and show that no single period produces most of the return.
6. **Significance and overfitting controls:** Deflated Sharpe Ratio using the logged trial count, probability of backtest overfitting (combinatorially symmetric cross-validation) when many variants were tested, and bootstrap resampling of trades for confidence intervals on Sharpe and max drawdown.
7. **Capacity:** simulate at target capital and at 3x; report participation rate and the cost drag growth.
8. **Benchmarks:** must beat buy-and-hold of the relevant index and a naive baseline (for example 12-1 month momentum) after costs.

**Provisional acceptance thresholds (calibrate after the first two or three strategies)**

| Metric | Starting bar |
| --- | --- |
| Out-of-sample net Sharpe | 0.8 or higher for long-only equity, 1.0 or higher for market-neutral or intraday |
| Deflated Sharpe probability | Above 0.95 |
| Max drawdown | No worse than 1.5x the benchmark's, and inside the owner's stated tolerance |
| Net result at 2x costs | Still positive |
| Parameter plateau | Result within 30% of best across the plus and minus 20% neighbourhood |

These are starting points to be tuned, not industry-fixed numbers.

**Reporting and reproducibility**

- Standard tear sheet: CAGR, volatility, Sharpe, Sortino, max drawdown and duration, Calmar, turnover, exposure, hit rate, average win and loss, beta to benchmark, cost drag, per-year returns, rolling Sharpe, drawdown chart.
- Each `backtest_run` stores code commit, parameter hash, data snapshot id, cost schedule version, random seed, and an `experiment_id` that groups related trials.
- Parameter sweeps run in parallel (Dagster dynamic partitions or a process pool), and every sweep member is a logged trial.

## 11. Execution: paper, OMS, risk, brokers

Only one service, the Order Management System (OMS), may talk to a broker. Strategies produce targets, the risk engine approves them, and the OMS turns them into orders. Paper and live trading are the same code path with a different broker adapter.

**Broker adapter interface**

```python
class Broker(Protocol):
    def place_order(
        self, o: OrderRequest
    ) -> BrokerOrderId: ...  # carries a client_order_id for idempotency
    def modify_order(self, id, changes) -> None: ...
    def cancel_order(self, id) -> None: ...
    def orders(self) -> list[BrokerOrder]: ...
    def positions(self) -> list[BrokerPosition]: ...
    def holdings(self) -> list[BrokerHolding]: ...
    def margins(self) -> Margins: ...
    def stream_updates(self) -> AsyncIterator[OrderUpdate]: ...  # postbacks or WebSocket
```

| Adapter | Phase | Notes |
| --- | --- | --- |
| `PaperBroker` | 1 | Matches against live quotes with the same slippage and cost models as the backtester; writes to the same tables with `mode = paper` |
| `KiteBroker` | 2 | Zerodha Kite Connect REST plus WebSocket. The access token expires daily, so a login job must refresh it before market open. Check Zerodha's current terms before automating the login step |
| `AlpacaBroker` or `IBKRBroker` | 4 | US equities |
| `BinanceBroker` (or another crypto venue) | 4 | Spot and perpetuals; 24/7, so the OMS must run without a daily session reset |

**Order lifecycle (event-sourced)**

`NEW` to `SUBMITTED` to `ACKED` to `PARTIALLY_FILLED` to `FILLED`, with `CANCELLED`, `REJECTED`, and `EXPIRED` as terminal states. Every transition is an immutable row in `order_event`, and the `order` table is a projection of those events. The full history of any order can be replayed.

**Correctness rules**

- **Idempotency:** every order carries a unique `client_order_id` (also sent as the broker tag). A retry after a timeout first looks up that ID, so a network blip cannot create a duplicate order.
- **Reconciliation:** every minute during market hours, and once after close, compare OMS orders, positions, and cash with the broker's. The broker is the source of truth. Any mismatch raises an alert and, above a threshold, halts trading.
- **Single writer:** only the OMS places orders. Strategy runners and the dashboard talk to the OMS, not to the broker.
- **Mode safety:** `live` requires an explicit environment flag, a strategy in a live lifecycle stage, and a valid broker session. Anything else forces paper.

**Risk engine**

| Layer | Checks | On breach |
| --- | --- | --- |
| Pre-trade (every order) | Allowed instrument list; order value and quantity caps; quantity versus average daily volume; price within a band of last traded price (fat-finger guard); per-instrument, per-sector, and gross and net exposure limits; margin sufficiency; open-order count; order-rate limit; trading-hours check | Reject or scale down, and log the reason |
| Real-time | Daily loss limit; strategy and portfolio drawdown limits; stale-data guard (no fresh bar or quote within N seconds); broker connectivity | Halt the strategy, optionally flatten, and alert |
| Post-trade | Slippage versus model; fill rate; tracking error versus backtest | Alert, and flag the strategy for review |

**Kill switch:** a global and a per-strategy switch, reachable from the CLI, the API, and the dashboard. It cancels open orders and optionally flattens positions. A heartbeat from each live service is monitored, and a missed heartbeat during market hours alerts immediately.

**Live process model**

1. **Market-data service:** WebSocket to Redis Streams, builds bars on the exchange calendar, and writes them to `bar_1m`.
2. **Strategy runner(s):** consume bars, call `on_bar` or `on_schedule`, and publish `Targets`.
3. **Portfolio and risk service:** combines targets, applies limits.
4. **OMS and execution service:** the only component with broker credentials.
5. **Reconciler and monitor:** independent process, so a bug in the OMS cannot hide its own mistakes.

**Live versus backtest tracking:** weekly, re-run the backtest for the live period using actual data and compare trades and P&L. Persistent divergence means the simulator, costs, or data are wrong, and it is investigated before any capital increase.

## 12. API and dashboard

All reads and controls go through one FastAPI service. Grafana ships first for visibility, and a custom React UI follows only when you need to control the system from the screen.

**API groups**

| Group | Examples | Access |
| --- | --- | --- |
| Data | Instruments, bars (`freq`, `adjusted`), features, fundamentals as-of, macro series | Read |
| Pipeline | Job status, dataset freshness, data-quality results, trigger or backfill a partition | Read, plus operator for triggers |
| Strategies | List, manifest, parameters, lifecycle stage, promote or demote | Read, plus approver for stage changes |
| Backtests | Submit run, status, tear sheet, compare runs, trial counts | Read and submit |
| Trading | Orders, fills, positions, portfolio snapshots, risk utilisation | Read |
| Control | Kill switch (global or per strategy), pause, flatten | Operator only |

**Security:** single owner, no public exposure. Put the API and dashboards behind a private network (Tailscale or WireGuard) or an identity-aware proxy (Cloudflare Access), with OIDC login and two roles: viewer and operator. Every mutating call is written to an `audit_log` table with user, time, and payload.

**Dashboard pages**

| Page | Question it answers | Main sources |
| --- | --- | --- |
| Data health | Is today's data complete and fresh? | `job_run`, `dq_result`, freshness per dataset |
| Portfolio | What do I hold, and how am I doing? | Equity curve, P&L by strategy and instrument, exposure, drawdown |
| Execution | Are fills as modelled? | Orders, fills, slippage versus model, rejections |
| Risk | How close am I to my limits, and is anything halted? | Limit utilisation, kill-switch state, heartbeats |
| Research | Which experiments exist and how do they compare? | `backtest_run` metrics, tear sheets, trial counts |
| Strategy control (phase 3) | Promote, pause, or edit a strategy safely | Lifecycle table, parameter forms validated by the manifest schema |

**Phasing:** Grafana covers the first four pages directly on Postgres within the first weeks. The Research and Strategy control pages need a custom UI (React with a charting library) and come later.

**Alerting (Prometheus Alertmanager or Grafana alerts, to Telegram or Slack, with email as backup)**

- **Page immediately (P1):** reconciliation mismatch, kill switch triggered, risk halt, broker token not refreshed before market open, no fresh data during market hours, OMS heartbeat lost.
- **Same day (P2):** data-quality failure, job retries exhausted, tracking error above threshold, disk above 80%.
- **Daily digest (P3), 19:30 IST:** day P&L, open positions, jobs run, data-quality summary, anything quarantined.

## 13. Observability, security, deployment

Because real money moves through this system, a silent failure is worse than a loud one. Every service emits logs, metrics, and heartbeats, and every deploy is reproducible.

**Observability**

- **Logs:** structured JSON with `run_id`, `strategy_id`, `instrument_id`, and `order_id` on every line, shipped to Loki or CloudWatch.
- **Metrics (Prometheus):** pipeline freshness per dataset, DQ failures, bar-build latency, order latency, rejection rate, slippage versus model, reconciliation diffs, risk-limit utilisation, and service heartbeats.
- **Tracing:** OpenTelemetry is optional in v1. A correlation ID that follows signal, order, and fill through the logs is enough.
- **Audit trail:** `order_event`, `audit_log`, `stage_change`, and `job_run` are append-only and never deleted.

**Security**

| Area | Requirement |
| --- | --- |
| Secrets | Broker API key, secret, TOTP seed, and DB passwords live in a secrets manager (AWS Secrets Manager or SOPS with age keys). Never in git, images, or logs |
| Credential scope | Only the OMS container receives broker trading credentials. Data jobs use a read-only data key where the provider allows one |
| Network | VM in a private subnet where possible; only the VPN or identity-aware proxy exposes the dashboard and API. Database ports are never public |
| Access | MFA on cloud and broker accounts; two roles (viewer, operator); every control action audited |
| Dependencies | Pinned versions (uv lock file), automated vulnerability scanning in CI, and container images built from a minimal base |
| Backups | Daily database backup plus WAL archiving to object storage in a second region; quarterly restore drill; raw lake versioned |

**Environments**

- **dev:** local Docker Compose with a small sample dataset and the `PaperBroker`.
- **staging:** same images as production, broker in paper mode, real data feeds. A strategy must run here for the paper-trading period.
- **prod:** one VM in AWS ap-south-1 with an Elastic IP registered with Zerodha. Infrastructure is defined in Terraform, and services run under Docker Compose with restart policies and health checks.

**CI/CD**

1. On every pull request: lint (ruff), types (mypy), unit tests, and a fast backtest on a fixed sample dataset whose result must match a stored golden value, which catches accidental look-ahead or cost-model changes.
2. On merge to main: build images, run integration tests against a throwaway Postgres with Timescale, push images tagged with the commit hash.
3. Production deploys are manual, outside market hours, and never while a live strategy holds open positions that the new version could mishandle. Rollback is redeploying the previous image tag.

**Testing standard**

- **Unit tests** for parsers (using saved raw files), adjustment math, fee calculation, order state machine, and every risk check.
- **Property tests** (Hypothesis) for invariants: positions equal the sum of fills, cash balances reconcile, adjusted prices are continuous across splits.
- **Look-ahead test:** a harness that truncates data at time T and verifies a strategy's output at T is unchanged. Every strategy must pass it.
- **Replay test:** recorded live sessions can be replayed through the engine and must give identical orders.

**Cost estimate (indicative, verify with current pricing):** one mid-size VM with 8 vCPU and 32 GB RAM, 1 TB of SSD, and object storage for the lake, plus the Kite Connect subscription. Check current AWS ap-south-1 and Zerodha pricing before committing; the stack deliberately avoids managed services whose bills scale with data volume.

## 14. Compliance and constraints

Automated order placement through Kite Connect is allowed for your own account inside SEBI's retail algo framework, and the framework changes three things in the design: a whitelisted static IP, an order-rate ceiling, and daily session expiry. This section is an engineering summary as of November 2026, not legal or tax advice.

| Rule | What it means for the platform | Source |
| --- | --- | --- |
| Static IP mandatory for API order placement since 1 April 2026; orders from other IPs are rejected | The OMS must egress from one registered IPv4 address. Use a cloud VM with an Elastic IP in Mumbai | [Zerodha support: static IP](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip) |
| The registered IP can be changed at most once per calendar week | Treat the IP as permanent infrastructure. Never run the OMS from a laptop or a rotating address | [Zerodha support: static IP](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip) |
| Data and read-only endpoints are not tied to the order IP, according to a Zerodha reply on the Kite forum | Research and ingestion jobs can run elsewhere, but verify this before relying on it | [Kite Connect forum](https://kite.trade/forum/discussion/comment/50522/) |
| Threshold of 10 orders per second per exchange; strategies above it need exchange registration, and requests above 10 per second get a 429 | Client-side token-bucket limiter set well below 10 (start at 5 per second), and handling of 429 responses. A retail strategy in this spec never needs more | [FinSec Law summary of the NSE implementation standards](https://www.finseclaw.com/article/nse-releases-implementation-standards-for-retail-participation-in-algorithmic-trading), [Kite Connect forum](https://kite.trade/forum/discussion/comment/50522/) |
| All API sessions are logged out daily | A scheduled login job before market open, plus an alert if it fails | [FinSec Law summary](https://www.finseclaw.com/article/nse-releases-implementation-standards-for-retail-participation-in-algorithmic-trading) |
| Market orders through the API get market protection, and are not allowed in commodities | Prefer limit orders with a timeout and price band; the execution layer must handle protected market orders | [Kite Connect forum](https://kite.trade/forum/discussion/comment/51995/) |
| Orders carry a strategy identifier under the 2026 framework | Tag every order with `client_order_id` and the strategy ID; confirm Zerodha's exact tagging requirement with their support | [Liquide overview](https://blog.liquide.life/sebi-algo-trading-regulations-2026/) (secondary source) |

**Constraints that follow from these rules**

- **Personal use only.** Running your own strategy on your own account (and, per one secondary source, immediate family) fits the retail framework. Running other people's money, selling signals, or offering the platform to others falls into different regulated categories (advisory, portfolio management, algo provider) and needs separate registration and legal advice. Keep this in mind before turning this into a MyVendor-style product.
- **Order-to-trade ratio and other exchange rules** change over time. One secondary source mentions revised order-to-trade ratio rules from April 2026. The risk engine therefore keeps exchange limits in a config table, and a person reviews NSE circulars quarterly.
- **Taxes and records:** trading income is taxable (intraday and F&O are generally treated as business income, delivery as capital gains). The OMS keeps a complete, exportable ledger of every order, fill, charge, and corporate action for your chartered accountant.
- **Foreign markets (phase 4):** funding a foreign broker for US stocks goes through RBI's Liberalised Remittance Scheme, which has limits and tax collection at source. Crypto has its own Indian tax treatment, and venue availability for Indian residents varies. Verify both before building those adapters.
- **Data licensing:** exchange data and vendor data have redistribution limits. This platform is for internal use only.
- **Verification:** read the primary SEBI circular (SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013) and the current Zerodha Kite Connect terms before going live, because several of the sources above are broker forums and blogs.

**Sources:** [Zerodha support: static IP](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip), [FinSec Law: NSE implementation standards](https://www.finseclaw.com/article/nse-releases-implementation-standards-for-retail-participation-in-algorithmic-trading), [Kite Connect forum: rules thread](https://kite.trade/forum/discussion/comment/50522/), [Kite Connect forum: market protection](https://kite.trade/forum/discussion/comment/51995/), [Liquide: SEBI framework 2026](https://blog.liquide.life/sebi-algo-trading-regulations-2026/).

## 15. Roadmap, repo structure, and risks

&#91;embedded content: roadmap · 5 phases, 4 gates\]

Each gate is a written pass or fail, not a feeling. Week counts are estimates for one engineer working full time; part-time roughly doubles them. The first strategy is price-only (trend-filtered momentum on Nifty 200), so fundamentals can wait until phase 5.

**Repository layout**

```text
algo-platform/
  pyproject.toml, uv.lock
  infra/              terraform, docker-compose, grafana dashboards, alert rules
  src/algo/
    core/             types, clock, calendars, instruments, config
    data/
      providers/      nse, kite, fred, xbrl (later: alpaca, binance)
      adjust/         corporate actions, adjustment factors
      store/          timescale access, parquet lake, snapshots
      quality/        data-quality checks, reconciliation
    pipeline/         dagster assets, schedules, sensors
    features/         feature library and registry
    strategy/         base interface, Context, manifest loader
    backtest/         engine, fills, costs, metrics, validation
    portfolio/        construction, sizing
    risk/             pre-trade, real-time, kill switch
    execution/        OMS, order state machine, brokers (paper, kite, ...)
    live/             market-data service, runner, reconciler
    api/              FastAPI app
  strategies/         one package per strategy, each with strategy.yaml
  tests/              unit, property, integration, lookahead, replay
  notebooks/          research only; never imported by src
```

**Main risks**

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Bad or unadjusted data silently corrupts results | High | Immutable raw files, data-quality checks, bhavcopy reconciliation, golden backtest in CI |
| Backtest overfitting leads to real losses | High | Validation protocol, trial counting, untouched holdout, mandatory paper stage |
| Operator or software error in live trading (wrong mode, runaway orders) | High | Mode safety, pre-trade limits, capital cap in the first live phase, kill-switch drills |
| NSE endpoints change or block scrapers | Frequent, medium | One NSE client, monitoring, vendor data as a fallback |
| Broker or regulatory rule changes | Medium | Adapter isolation, limits in config tables, quarterly circular review |
| Kite login or token refresh fails before the open | Medium | Login job with alert, written manual runbook |
| Single VM failure | Medium | Backups, Terraform rebuild, reconciler restores state from the broker |
| Scope creep into crypto, US stocks, or ML before the core is proven | Medium | Phase 5 only, after gate 4 |

**Decisions needed from you before phase 1 ends**

1. Capital you intend to deploy and the maximum drawdown you accept. These set the risk limits and thresholds.
2. Build the engine or adopt NautilusTrader after the one-week spike.
3. Free data first, or buy a vendor feed for delisted names and fundamentals.
4. Hours per week you can spend, which decides whether the timeline is 6 months or 12.
5. Whether this stays strictly personal. If you later want to run others' money or offer signals, the regulatory path changes (section 14).
