# Algo Trading Platform: Implementation TODO (v1.1)

Base: `Algo Trading Platform Developer Spec v1.md` + accepted review additions (all P0 + P1).
Language: **Python 3.12**, uv, pytest. Scope: Stage 0 → paper trading (Stage 5). Live / US / crypto are outlined at the end only.
Legend: `[ ]` todo · **(P0)** critical review addition · **(P1)** high review addition · `T:` tests required for the item.

---

## 0. Testing standard (applies to EVERY item below, from day 1)

**Rule: no task is done until its tests exist, pass, and the coverage gate is green. Tests are written first (red → green).**

- [x] T0.1 `pyproject.toml`: pytest, pytest-cov, pytest-asyncio, hypothesis, pytest-randomly, pytest-xdist, mutmut (or cosmic-ray), freezegun/time-machine, testcontainers, ruff, mypy `--strict`.
- [x] T0.2 Coverage gate: `--cov=src/algo --cov-branch --cov-fail-under=90` (line + branch). Fails CI and pre-push hook.
- [x] T0.3 Per-package floors via `coverage.py` config + a check script: `risk/`, `execution/`, `ledger/`, `data/adjust/`, `backtest/costs`, `platform_state/` = **100% branch**; everything else ≥ 90%.
- [ ] T0.4 Mutation testing on money paths (risk, OMS state machine, ledger, adjustment, cost model, fill simulator). Gate: mutation score ≥ 85%; surviving mutants reviewed in PR. Nightly job, not per-PR.
- [ ] T0.5 Test pyramid dirs: `tests/unit`, `tests/property`, `tests/integration` (real Timescale/Redis/MinIO via testcontainers, **no mocking the component under test**), `tests/e2e`, `tests/lookahead`, `tests/replay`, `tests/fault` (fault injection), `tests/golden`, `tests/contract` (provider/broker adapters vs recorded fixtures).
- [ ] T0.6 Test markers: `unit` (<1s each, no I/O), `integration`, `e2e`, `slow`, `fault`. PR runs all except `slow`; nightly runs all + mutation.
- [ ] T0.7 Deterministic by default: injected `Clock`, seeded RNG, `pytest-randomly` on, ban `datetime.now()`/`time.time()` in `src/` via ruff rule (DTZ) + custom lint test.
- [ ] T0.8 Fixtures: small sample dataset (10 instruments, 20 days, 1m bars, one split, one bonus, one dividend, one halt, one delisting, one holiday) committed under `tests/data/` with raw files + manifest. Used by unit, integration, golden and e2e.
- [ ] T0.9 Bug policy: every defect gets a failing regression test first, then the fix.
- [ ] T0.10 Coverage report published per PR (html artifact + summary comment); trend tracked.
- [ ] T0.11 Pre-commit: ruff, ruff-format, mypy, fast unit subset. CI is the source of truth.
- [x] T0.12 Test-the-tests: a meta-test that fails if any module in `src/algo` has no test file (import-graph check).

---

## Stage 0: Foundations and technical spikes

### 0.1 Repo + CI skeleton
- [ ] Create layout per spec §15 (`src/algo/{core,data,pipeline,features,strategy,backtest,portfolio,risk,execution,live,api}`, `strategies/`, `tests/`, `infra/`). Add new packages: `ledger/`, `platform_state/`, `readiness/`, `sandbox/`.
- [x] `uv` project, lockfile, Python 3.12 pin, `Makefile`/`justfile`: `test`, `cov`, `mut`, `lint`, `type`, `e2e`, `up`, `down`.
- [ ] GitHub Actions: lint → types → unit → integration (testcontainers) → coverage gate → golden backtest → build image. Nightly: mutation, fault, slow, replay.
- [x] (file written, CI smoke test pending) `docker-compose.dev.yml`: timescaledb, redis, minio. Healthchecks. T: compose-up smoke test in CI.
- [ ] Secrets policy: SOPS/age config, `.gitignore`, pre-commit secret scan (gitleaks). T: CI fails on seeded fake secret.
- [ ] Structured JSON logging + correlation-id helper (`run_id, strategy_id, instrument_id, order_id`). T: log schema test.
- [ ] ADR folder; write ADR-001 (Python), ADR-002 (modular monolith + isolated OMS/reconciler/sandbox processes), ADR-003 (Timescale + Parquet + DuckDB, no ClickHouse/Kafka v1).

### 0.2 Spikes (time-boxed, each ends with a written pass/fail ADR)
- [ ] **S1 TimescaleDB benchmark:** load ≥ 100M synthetic 1m rows; measure ingest rate, compression ratio, 1-instrument/1-year query, 500-instrument/1-day query, continuous aggregate refresh. Pass criteria written beforehand. T: benchmark script is reproducible and checked in.
- [ ] **S2 NautilusTrader vs build:** one week. Checklist: NSE calendar, lot sizes via `instrument_terms`, PIT fundamentals through Context, custom Kite adapter, determinism, ability to enforce our Context boundary. Output: ADR-004 build/adopt. Decide before Stage 3.
- [ ] **S3 Kite Connect feasibility:** auth + daily token login flow, historical candle limits, order lifecycle in sandbox/small order, postbacks vs WebSocket, 429 behaviour, recovery after disconnect, **market-order permissibility (get written clarification from Zerodha)**, tagging requirement. Record fixtures for contract tests.
- [ ] **S4 Execution-parity spike:** same toy strategy through backtest engine and paper path yields identical decisions on the same bars.
- [ ] **S5 Sandbox spike (P0):** prove process isolation (no network, no env vars, no FS, CPU/mem/time limits) for a strategy worker; measure per-bar IPC latency.
- [ ] Decisions needed (spec §15): capital + max drawdown, build/adopt, free vs paid data, hours/week, strictly personal. Record in `docs/decisions.md`.

**Exit gate 0:** ADRs 001–004 signed, CI green with ≥ 90% on the (small) skeleton, spikes S1–S5 have written outcomes.

---

## Stage 1: Core types, instrument master, calendars

### 1.1 Core types (`core/`)
- [ ] Money/price/qty as `Decimal` (NUMERIC) value objects; rounding helpers snapping to tick/lot/qty_step. T: property tests (snap idempotent, never crosses limit, round-trip).
- [x] (SystemClock + SimClock done; ReplayClock pending) `Clock` protocol: `SystemClock`, `SimClock`, `ReplayClock`. T: monotonicity, tz-awareness enforced (naive datetime rejected).
- [ ] UTC timestamp convention: `ts` = bar-open; bar visible only after close. Documented in one module + tested everywhere. T: boundary tests at session open/close, DST (US), 24/7.
- [ ] Config via pydantic-settings; env flag model for `live`. T: invalid configs rejected.

### 1.2 Platform state machine **(P0)**
- [x] States: INITIALIZING, DATA_VALIDATION, READY, PAPER, LIVE, DEGRADED, HALTED, RECOVERY. Explicit transition table + guards; persisted as append-only `platform_state_event`.
- [x] Hard invariant: runner cannot emit targets unless state ∈ {PAPER, LIVE} and recovery checks passed (market data fresh, broker session valid, open orders / positions / cash reconciled, internal portfolio loaded).
- [ ] Restart path: any boot → RECOVERY → READY only after reconciliation passes; stale Redis events discarded by epoch/sequence check.
- [ ] T: exhaustive transition matrix (every illegal transition raises); property test: no event sequence reaches LIVE without passing READY; restart-at-10:30 scenario with stale Redis + unreconciled position → no orders emitted; DEGRADED restricts to reduce-only; HALTED needs explicit operator action.

### 1.3 Instrument master (spec §4 + `instrument_terms` **P1**)
- [ ] (done so far: exchange, instrument, instrument_terms, instrument_alias via plain SQL runner; pending: instrument_derivative, index_membership, trading_calendar/session, fx_rate) Alembic migrations: `exchange`, `instrument`, `instrument_derivative`, `instrument_alias`, `index_membership`, `trading_calendar`, `trading_session`, `fx_rate`, **`instrument_terms`** (valid_from/to, lot_size, tick_size, qty_step, multiplier, margin_rule_version). Remove lot/tick from `instrument` or keep as "current" view.
- [x] Repository layer + `terms_as_of(instrument, ts)`. T: lot-size change mid-history resolves correctly; overlapping validity ranges rejected by DB exclusion constraint.
- [x] Alias resolution with validity dates; delisted never deleted. T: rename keeps history linked; lookup by symbol as-of date.
- [ ] Daily instrument refresh job: diff vs DB, write changes with timestamp, alert on held-instrument status change. T: golden diff fixtures (new listing, rename, delist, lot-size change).
- [ ] Expired futures = separate rows; continuous contract view with documented roll rule. T: roll on expiry day, back-adjust option off by default.
- [x] Asset-class enum + exchange table seeded for NSE/BSE; US/crypto rows added as data in a test to prove no schema change needed.

### 1.4 Calendars
- [x] (NSE + special sessions done; fake US/crypto calendars pending) `ExchangeCalendar` adapter: NSE (holidays, 09:15–15:30 IST, special sessions e.g. Muhurat), a fake US (DST) and 24/7 crypto calendar for tests. API: `is_open`, `next_bar_boundary`, `session_bars(date)`, `prev_session`.
- [ ] T: 375 bars per NSE day; half-day sessions; holiday suppression; DST spring/fall transitions; crypto no gaps; property test: `next_bar_boundary` always > t and aligned.

**Exit gate 1:** Instrument + calendar correct for sample data; DB constraints tested; 100% branch on `platform_state` and `core` money types; coverage ≥ 90%.

---

## Stage 2: Data ingestion, storage, quality

### 2.1 Raw lake
- [x] (local fs only; S3/MinIO backend pending) Object-store abstraction (MinIO/S3/local fs for tests). Path `raw/{source}/{dataset}/dt=YYYY-MM-DD/` + manifest (checksum, URL, fetch time, status, **ingest_kind: initial | provider_correction | parser_reprocess | manual_correction**).
- [x] Append-only enforcement: writing to existing path fails; corrections write a new versioned object. T: overwrite attempt rejected; checksum verified on read.

### 2.2 Provider framework (daily path is timeframe-agnostic: `data/bars.py` registry; Kite 1m = new provider + `bar_1m` migration only) (spec §6, + `supports_corrections` **P1**)
- [x] (fetch/parse/validate/load done; retries+rate limiter pending) `DataProvider` protocol incl. `supports_corrections()`; pipeline runner: fetch → store raw → parse → validate → load → publish. Retries w/ exponential backoff + rate limiter.
- [x] Quarantine table + state for failed DQ partitions. T: quarantined partition never loads.
- [x] Idempotent load; **versioned ingestion** (replaces bare `ON CONFLICT DO NOTHING`): rows carry `dataset_version`, `ingested_at`, `supersedes`; corrections create a new version, never overwrite. T: re-run is no-op; correction yields new version and old one still queryable; crash mid-load leaves no partial partition (single transaction).
- [ ] (done: NSE bhavcopy + security master, verified on real Nov-2026 files, real HTTP client w/ retries; pending: ETF master (~355 EQ-series ETFs/index funds/day are unknown), Kite 1m, instrument dump, corp actions, index/VIX/FII, FRED, Stooq) Adapters (each with recorded raw fixtures + pure `parse` unit tests): NSE bhavcopy, Kite 1m candles, instrument dump, NSE corporate actions, index levels/VIX/FII-DII, FRED, Stooq/yfinance. NSE behind one client (headers, cookies, status recording, schema-change alert).
- [ ] T: parsers run offline on saved raw; malformed/truncated file → typed error + quarantine; non-200 recorded; schema drift detected.

### 2.3 Storage (spec §5)
- [ ] Migrations: `bar_1m` hypertable (+compression policy), `bar_15m`/`bar_1d` continuous aggregates on exchange sessions, `corporate_action` (with explicit `announced_at` + **`knowledge_time`** **P1**), `adj_factor`, `fundamental` (PIT), `macro_series` (event_time + available_at), `feature_value`, `signal`, `job_run`, `dq_result`, `audit_log`.
- [ ] `bar_canonical` view (preferred source per instrument/day). T: source precedence, fallback when preferred missing.
- [ ] Timestamp-convention rules: late-arriving bar handling, missing bar representation (explicit gap row/flag, **never zero-return**), duplicate multi-provider reconciliation, provider revision of a published bar. T: one test per rule.
- [ ] Backups: `pg_dump`/WAL script + **restore test in CI** (restore into throwaway DB, row counts + checksums match).

### 2.4 Immutable data snapshots **(P0)**
- [ ] Tables `data_snapshot` (id, created_at, cutoff_time, status, snapshot_hash) and `snapshot_partition` (snapshot_id, dataset_id, partition_date, raw_manifest_id, checksum, record_count, source_version).
- [ ] Snapshot also pins: instrument master version, corporate-action version, calendar version, feature definition versions, cost schedule version, strategy config, code commit.
- [ ] Reader API: `DataAPI(snapshot_id)` serves only data referenced by the snapshot's immutable dataset versions (not "ingested_at <= x").
- [ ] T: **provider-correction scenario**: backtest → provider corrects history → reingest → rerun with same snapshot = byte-identical result; new snapshot differs; snapshot_hash stable & changes when any pinned input changes.

### 2.5 Data-quality checks (spec §6) + readiness service **(P1)**
- [ ] Checks: completeness (375/day), validity (OHLC bounds, negative, circuit), continuity (unadjusted split flag), reconciliation (1m→daily vs bhavcopy), freshness SLA, cross-provider. Results → `dq_result`.
- [ ] `ReadinessService`: given strategy `requirements` (timeframe, warmup_bars, max_data_age_seconds, datasets, features) returns pass/fail + reasons: instrument valid, session open, latest completed bar present, expected provider, no gaps, features computed, freshness SLA.
- [ ] Runner refuses to call strategy when not ready. T: each failing condition individually blocks; missing bar never becomes zero-return; staleness boundary (exactly N sec).
- [ ] T: each DQ check with pass/fail/edge fixtures; reconciliation tolerance breach opens alert.

### 2.6 Corporate actions, adjustments, PIT fundamentals, macro (spec §7–8)
- [x] **Findings from real NSE data (Nov 2026):** `corporates-corporateActions` API needs a homepage session cookie; `caBroadcastDate` is NULL for every row (no announcement date), so `knowledge_time` cannot come from this feed; `subject` is free text (e.g. `Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share`, `Bonus 1:1`, `Rights 3:8 @ Premium Re 0.50/-`, `Demerger`, `Buy Back`, `Interim Dividend - Rs 8 Per Share`, plus MF/InvIT `Distribution - ...` lines) and needs a tested parser; demerger / rights / buy-back carry no ratio or price in the subject and need explicit handling (manual-review queue, never silently adjusted).
- [x] (owner approved) Corporate-action `knowledge_time` rule:  conservative default = start of ex-date, stored with `knowledge_time_source` so a real announcement feed can later replace it.
- [ ] Three separate price series, never one `adjusted_close`: raw OHLC (execution/audit, never adjusted), split/bonus-adjusted (signals/charts), total-return (performance). Adjusted prices are never used to simulate execution. NSE's F&O adjustment rules are NOT reused for equity history; our adjustment engine is versioned and documented.
- [ ] (verified live; adapter pending) Add NSE CM-UDiFF common bhavcopy (`BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`, verified live, includes ISIN) as a second source for cross-provider reconciliation and ISIN-based mapping; keep `sec_bhavdata_full` for delivery qty. Legacy `cmDDMONYYYYbhav.csv.zip` is gone (404).
- [x] (split/bonus/dividend done, PIT-aware, 100% branch; rights/demerger/buy-back go to review) Factor builder: split/bonus `1/ratio`, dividend total-return series; split-adjusted vs total-return vs **point-in-time adjusted** (a later action must not alter an earlier backtest's information set).
- [x] (`data/reader.py` BarReader: none/split/total_return, PIT via as_of, volume scaled, strict mode; verified on real BAJFINANCE/RELIANCE/TMPV. Still to wire into `Context.data.history` and a DuckDB/Polars research path) Adjustment applied at read time via data API (`adjusted=True`). T: property tests: adjusted series continuous across splits; position value preserved across split/bonus; factor rebuild only for affected instrument; action with no price discontinuity flagged; >20% move without action flagged.
- [ ] `fundamentals.as_of()` with `knowledge_time` + configurable reporting lag; restatement = new row; standalone vs consolidated. T: restatement not visible before its knowledge_time; lag boundary at next session.
- [ ] Historical `index_membership` loader + `universe_at(date)`. T: delisted names present in past universes (survivorship).
- [ ] Macro as-of join on `available_at`, implemented once. T: US close D usable D+1 India session; Asian open same-day usable; property: never returns record with available_at > T.

- [ ] Open from real-data work: (a) DONE for current Nifty 200 (4,823 actions, 2005-2026; 529 in review queue: 393 pre-2010 percent dividends, 63 buy-backs, 34 rights, 27 demerger/arrangement, ~12 other) - history for delisted / past Nifty 200 members still missing; (b) rights issues need historic face value / subscription price (feed `faceVal` is today's value); (c) percent-of-face-value dividends (`Dividend-500%`) have no rupee amount -> total-return series incomplete until resolved; (d) demerger/scheme-of-arrangement/buy-back manual-treatment workflow; (e) renamed symbols (TATAMOTORS returns [] after demerger: query by current symbol, map via alias); (f) historic holidays: feed has current year only, derive older trading days from bhavcopy availability; (g) Muhurat session times (08-Nov-2026) must be entered by hand; (h) `PREV_CLOSE` in sec_bhavdata_full is NOT adjusted (equals raw prior close).

### 2.7 Dagster pipeline
- [ ] Assets, daily partitions, schedules per spec §6 table, sensors, retries, holiday suppression, alerts on freshness miss, backfill job. T: `dagster` in-process materialization tests for each asset on sample data; missing-file-on-trading-day raises incident; holiday does not.
- [ ] Kite login job (token refresh before open) with alert on failure. T: contract test vs recorded fixtures; failure path pages.

**Exit gate 2:** Sample + (when available) real history loaded; DQ + reconciliation pass; snapshot reproducibility test green; backup restore test green; coverage ≥ 90%, `data/adjust` 100% branch.

---

## Stage 3: Strategy interface, sandbox, backtest engine

### 3.1 Strategy contract + Context (spec §9)
- [ ] `Strategy` ABC, `Params` (pydantic), `Requirements`, `Targets`, `BarBatch`, manifest (`strategy.yaml`) loader + entry-point discovery; refuse to run if data requirements unmet.
- [ ] `Context`: `now`, `data.history`, `features.get`, `fundamentals.as_of`, `macro.get`, `portfolio` (read-only), `calendar`, `log`, `metrics`. All reads bounded by `ctx.now()`.
- [ ] T: `history` never returns bar with close > now; bar visible only after close; read-only portfolio mutation attempts raise; manifest validation (bad/missing fields); entry-point discovery.

### 3.2 Strategy sandbox **(P0)**
- [ ] Strategy Worker process: receives serialized Context/bar events over IPC (pipes/msgpack), returns Targets only. No broker/DB credentials, scrubbed env, restricted FS, network egress disabled (namespaces / seccomp / container), CPU+mem limits, per-call timeout, crash isolation.
- [ ] Same worker used in backtest, paper, live.
- [ ] T (adversarial strategies as fixtures): tries `requests.get`, opens socket, connects to DB, reads env/secrets, reads/writes files, fork bombs, infinite loop, memory blowup, `time.time()` use → each blocked/killed, platform stays healthy, runner marks strategy failed and halts it. IPC determinism test.
- [ ] State: `get_state/set_state` restart safety. T: kill worker mid-run, restore, identical subsequent decisions.

### 3.3 Feature library
- [ ] Registry (`feature_id`, version, inputs, warm-up); same function for batch + live; stored with `feature_version`. First features: returns, momentum windows, vol, ATR, MA distance, liquidity.
- [ ] T: batch == incremental (property test), warm-up respected (NaN/None, not zero), version bump creates new rows, cross-sectional ranks stable, **look-ahead harness** (truncate data at T, output at T unchanged).

### 3.4 Backtest engine (or Nautilus adapter per ADR-004)
- [ ] Event-driven loop on `SimClock`; signal timing (decision at close t → exec ≥ open t+1); order types (market+slippage, limit through-price, stop at worse); liquidity cap (5% bar volume, carry/cancel); circuit/halt rules; lot/tick via `instrument_terms`; product type (intraday force-close); futures margin/MTM/expiry/roll; cash + buying power rejection.
- [ ] Cost model: versioned `cost_schedule` (brokerage, STT/CTT, exchange, SEBI, GST, stamp) effective-dated, values loaded from published schedules + human-verified flag; slippage (half-spread + sqrt impact); 1x and 2x reports.
- [ ] Portfolio construction (capital allocation, caps, turnover, vol-target) and **same risk engine and execution interface** as live.
- [ ] Persist `backtest_run/trade/equity` with code commit, param hash, snapshot id, cost version, seed, `experiment_id`; trial counter.
- [ ] Metrics/tear sheet: CAGR, vol, Sharpe, Sortino, MDD+duration, Calmar, turnover, exposure, hit rate, beta, cost drag, yearly, rolling Sharpe.
- [ ] T: hand-computed tiny scenarios per rule (each row of §10 fidelity table is a test); cost fixtures computed by hand; determinism (same inputs → identical hash of trades, 5 runs, varied xdist ordering); golden backtest on sample data (stored values; CI fails on drift); expired futures can't trade; halted instrument can't fill; fill never outside circuit; 2x cost ≥ 1x cost drag.

### 3.5 Validation protocol (spec §10)
- [ ] Pre-registration record + trial counter; frozen holdout opened once (enforced, audited); walk-forward (rolling/anchored, purged+embargoed CV for ML); ±20% robustness grid; regime/period breakdown; Deflated Sharpe, PBO (CSCV), bootstrap CIs; capacity at 1x/3x; benchmark comparison; acceptance thresholds in config.
- [ ] T: each statistic against known reference values (published DSR examples, synthetic series with known Sharpe); holdout second-open attempt rejected; promotion blocked when any gate missing.

### 3.6 Financial ledger **(P0)** (used by backtest, paper, live)
- [ ] Tables: `cash_ledger`, `position_ledger`, `fee_ledger`, `realized_pnl`, `unrealized_pnl`, `margin_ledger`; every row references source event (fill id / charge id / corporate action id). Double-entry style, append-only; broker-reported vs internal stored separately + reconciliation diff table.
- [ ] Single canonical P&L source; dashboards query ledger views only.
- [ ] T (mandatory invariants): position = Σ fills; opening cash + movements = closing; duplicate execution cannot be booked twice (unique exec id); partial fills compose; cancelled order can't become filled without broker event; split/bonus preserve economic value; property tests with Hypothesis random fill sequences; backtest P&L == ledger P&L.

**Exit gate 3:** Look-ahead harness passes for reference strategy; adversarial sandbox suite green; golden backtest stable; ledger invariants 100% branch; coverage ≥ 90%.

---

## Stage 4: First strategy (trend-filtered momentum, Nifty 200)

- [ ] Package `strategies/nifty200_momentum/` with `strategy.yaml`, params, tests (unit + look-ahead + replay).
- [ ] Pre-register hypothesis/universe/params; run validation protocol; store tear sheet; write pass/fail report.
- [ ] Benchmarks: buy-and-hold Nifty, 12-1 momentum baseline; 2x cost result positive.
- [ ] Lifecycle table + `stage_change` (approver, timestamp); promotion gates enforced in code. T: cannot enter Paper without Backtest-approved record; runner refuses non-live-stage strategy for live.
- [ ] Platform-correctness / strategy-validity / operational-reliability reported as three separate scorecards.

**Exit gate 4:** Written pass/fail on strategy; if fail, iterate or choose another; **platform proceeds regardless** (platform correctness is independent of edge).

---

## Stage 5: Risk, OMS, paper trading, dashboard (first end-to-end journey)

### 5.1 Risk engine (spec §11 + kill-switch protocol **P0**)
- [ ] Pre-trade: instrument allow-list, order value/qty caps, qty vs ADV, fat-finger band, per-instrument/sector/gross/net limits, margin, open-order count, order-rate (token bucket, start 5/s), trading hours, expired contract, **per-instrument restriction**, **max daily order count / turnover / loss**, **max consecutive execution failures**.
- [ ] Real-time: daily loss, drawdown, stale-data guard, broker connectivity. Post-trade: slippage vs model, fill rate, tracking error.
- [ ] Kill-switch with three distinct operations: **PAUSE** (no new orders), **CANCEL** (cancel open orders), **FLATTEN** (cancel + close). Global + per-strategy; CLI/API. FLATTEN requires explicit policy per failure type + emergency override; never automatic by default (e.g., data failure → PAUSE).
- [ ] Exchange limits in config table; `regulatory_config` table **(P1)** (effective date, exchange, segment, order types, OPS limit, tagging, static-IP, source circular, last_verified). Live blocked if `last_verified` older than N days.
- [ ] T: every check has accept / reject / boundary-exact test; breached order **never reaches broker** (integration with fake broker asserting zero calls); PAUSE/CANCEL/FLATTEN each behave as specified and are not interchangeable; auto-flatten off by default test; config-driven limits change behaviour without code change.

### 5.2 OMS **(P0)**
- [ ] Event-sourced order lifecycle: `order_intent` → `order` → `submission_attempt` → `broker_response` → `order_event` → `reconciliation_event`. States NEW, SUBMITTING, SUBMITTED, ACKED, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED, **UNKNOWN** (+RECONCILED).
- [ ] **Ambiguous-submission recovery:** on timeout/ambiguity → UNKNOWN; never blind resubmit; lookup by `client_order_id` / tag / broker order list/history; if unresolved, pause that strategy and escalate (P1 alert).
- [ ] **Transactional outbox** for order commands (DB state + command in one txn; dispatcher is at-least-once, consumer idempotent).
- [ ] `client_order_id` generation, strategy tagging; idempotent duplicate callbacks; out-of-order update handling.
- [ ] `Broker` protocol; `PaperBroker` (live quotes, same slippage + cost models, `mode=paper`); `FakeBroker` with scriptable faults for tests. (`KiteBroker` implemented in Stage 6.)
- [ ] Reconciler as independent process: minute-level compare orders/positions/cash vs broker; threshold halt; post-close pass.
- [ ] T: full state-machine transition matrix; property tests (event replay rebuilds identical `order` projection; fills never exceed qty); ambiguous timeout → UNKNOWN → resolves to FILLED / not-found paths without double order; outbox crash-between-commit-and-dispatch; duplicate and out-of-order broker callbacks; reconciler detects injected mismatch and halts.

### 5.3 Live process model (paper)
- [ ] `marketdata` (replayable feed for tests, Redis Streams, bars on exchange calendar → `bar_1m`), `runner` (loads sandboxed strategy workers), `portfolio-risk`, `oms`, `reconciler`, `api`. Heartbeats + missed-heartbeat alert.
- [ ] T: consumer-group restart doesn't reprocess or skip bars; duplicate bar idempotent; stale data blocks targets; replay test: recorded session → identical orders.

### 5.4 Fault-injection suite **(P1)** (`tests/fault`, nightly + pre-release)
- [ ] Kill OMS mid-submission · disconnect broker WebSocket · stop Redis · Postgres unavailable then back · duplicate broker callbacks · out-of-order updates · restart with pending orders · clock skew · disk full on lake.
- [ ] Assertion per scenario: no duplicate orders, ledger consistent, platform state goes DEGRADED/HALTED/RECOVERY as designed, recovery reaches READY only after reconciliation.

### 5.5 API + dashboard + alerting
- [ ] FastAPI groups (data, pipeline, strategies, backtests, trading, control); OIDC viewer/operator roles; `audit_log` on every mutation. T: OpenAPI contract tests, authz matrix, audit row for each mutating call, control endpoints refuse viewer.
- [ ] Grafana dashboards as code: data health, portfolio (from ledger views), execution, risk. T: dashboard JSON lint + SQL queries run against sample DB in CI.
- [ ] Prometheus metrics + Alertmanager rules P1/P2/P3; digest at 19:30 IST. T: `promtool test rules` for each alert.

### 5.6 End-to-end acceptance (the single journey)
```
Historical data → validation → Timescale → strategy (sandboxed) → backtest → risk → paper OMS → ledger → dashboard
```
- [ ] `tests/e2e/test_full_journey.py`: from raw sample files through ingest, DQ, snapshot, backtest, then replay same bars through paper runner; assert (a) decisions identical to backtest, (b) ledger P&L == backtest P&L within modelled-slippage tolerance, (c) dashboard SQL returns expected numbers, (d) rerun is byte-identical.
- [ ] `tests/e2e/test_restart_recovery.py` and `test_killswitch.py` through the real compose stack.
- [ ] Weekly live-vs-backtest tracking job (paper period) + report.
- [ ] Runbooks: token-refresh failure, reconciliation mismatch, kill-switch drill, restore from backup. Drill each once; record in `docs/drills/`.

### 5.7 Paper period
- [ ] ≥ 8 weeks on staging with real data; weekly tracking error report; zero unreconciled diffs at close; kill-switch drill monthly.

**Exit gate 5:** E2E journey green in CI; fault suite green; coverage ≥ 90% overall and floors met; mutation scores met; 8-week paper results within agreed tracking-error bounds.

---

## Outline only (not scheduled; each needs its own detailed TODO after Gate 5)

- **Stage 6 Live execution:** `KiteBroker` (contract tests from S3 fixtures), static-IP Elastic IP + Terraform, token login job, market-protection/limit-order policy, **regulatory sign-off before first live order** (primary SEBI circular + Zerodha terms + written order-type clarification), live-small (10% cap, 4 weeks), manual approval for live-full, mode-safety triple check.
- **Stage 7 Monitoring/optimization:** custom React UI (control + research pages, with its own test track), capacity re-tests, cost-schedule review cadence, quarterly circular review.
- **Later (not v1):** US equities, crypto, options, ML components, news/NLP, ClickHouse replica, HMM regimes.

---

## Open items to confirm during Stage 0
1. Real vs synthetic data source for Stage 2 (free first, per spec; paid feed decision after S1/S3).
2. Mutation tool choice (mutmut vs cosmic-ray) after a trial on `core` money types.
3. Sandbox mechanism (bubblewrap/nsjail vs Docker per worker) from spike S5.


## Backfill status (real NSE data, persistent dev DB `algo-dev` :5433, lake `data/lake`)
- [x] Universe: 2,630 equities, 448 symbol renames applied (chains like TELCO->TATAMOTORS->TMPV), Nifty 200 snapshot (current constituents only, NOT historical membership).
- [x] Corporate actions: Nifty 200 full history; parser hardened on real subjects (dash bonuses, abbreviations, "Spl" = special dividend vs split, meeting noise); `reparse` stage rebuilds from raw lake without network.
- [x] Daily bars 2019-10-01 -> 2026-11-06 from sec_bhavdata_full: 1,752 trading days, ~3.9M rows incl. non-Nifty names. Continuity check on all 200 Nifty stocks (321k bars): 70 splits/bonuses in window, 0 mismatches vs actual price moves; 84 flagged jumps are real market events (COVID Mar-2020, Hindenburg Feb-2023, 4-Jun-2024 results) plus 3 demergers (SIEMENS 2025-04-07, TMPV 2025-10-14, VEDL 2026-04-30) that sit in the review queue as expected. Holidays are detected from missing files; NSE re-serves the previous day's file on holidays (treated as not_published).
- [ ] Bars before 2019-10: legacy `cm<DD><MON><YYYY>bhav.csv.zip` (verified live for 2015, 2019, 2024; different columns, has ISIN, no delivery qty) -> new provider.
- [ ] Bars July 2024+: UDiFF second source for cross-check.
- [ ] Unknown symbols in bhavcopy: ETFs/index funds (~355/day) and delisted names are dropped (survivorship bias) until ETF master + delisted universe exist.
- [ ] Known bar gaps: 2022-08-08 (NSE served an .xlsx under the .csv URL; raw kept, fill from legacy cm bhavcopy); 5 special sessions whose bars sit inside the NEXT weekday's file and are not loaded (Muhurat 2019-10-27, 2020-11-14, 2021-11-04; Saturday sessions 2024-01-20, 2024-05-18) -> needs special-session handling in the calendar + pipeline.
- [ ] Continuity check (`data/quality/continuity.py`) exists and is validated on real data; still to wire into the pipeline/Dagster and `dq_result`.
- [x] Corporate-action resolution workflow (`data/review.py`, `action_resolution`, `scripts/review_actions.py`): statuses provisional / verified / no_adjustment_verified / ignored_with_reason / rejected; `verified` needs source_type + source_url + verifier (DB CHECK enforces); `gap` estimates can NEVER be verified; methods ignore / direct / demerger / rights / cost_allocation / gap. Reader: strict = verified only (refuses provisional + unpriced); research = also applies provisional but lists them in `History.provisional`; every read carries an `adjustment_version` hash. Decisions survive corporate_action rebuilds; verify appends an audit row.
- [x] Current dispositions (Nifty 200, split-adjusted, 2019-10 -> today): 167/200 strict-clean. Blocking the other 33: 10 demergers (PROVISIONAL via `gap`: ABB, GMRAIRPORT, MOTHERSON, NMDC, RELIANCE, ITC, SIEMENS, TMPV, HINDUNILVR, VEDL), 10 rights, 24 buy-backs. BRITANNIA 2021 + TVSMOTOR 2025 schemes = IGNORED_WITH_REASON (bonus debentures / NCRPS).
- [ ] TO DO BY OWNER/FILINGS: replace each `gap` estimate with the filing's terms (`cost_allocation` parent_share per the company's cost-of-acquisition split, or `demerger` ratio+price) and `verify` with source; get rights ratio + issue price from the offer document (historic face value is NOT in the feed) before resolving; classify the 24 buy-backs (tender / open-market -> no price adjustment) and record as no_adjustment_verified/ignored_with_reason; fetch amount + ex-date for the 1 pending dividend.
- [ ] CORRECTION: the 79 continuity-check jumps with no recorded action are UNEXPLAINED OBSERVATIONS, not "real market moves"; only a handful were matched to known events by hand. Each needs independent validation (e.g. against a second price source) before being trusted.
- [ ] Not modelled: total-return for demergers / rights (shareholders also receive child shares / entitlements - an adjusted PARENT price series is price-continuous, not wealth-continuous); `known_from` (a demerger's child price is only known after listing); dataset pinning: store `adjustment_version` (+ data_snapshot id) on every backtest_run and make changing a factor create a new version.
- [ ] Reader limits to resolve: rights issues + demergers are surfaced in `History.unapplied` but not priced (e.g. RELIANCE pre-2023 adjusted prices are ~9% off from the Jul-2023 Jio demerger, ~1% from the May-2020 rights); daily-bar visibility uses a fixed 6h15 session + 3h publish lag (not per-day calendar); reads all bars of an instrument then slices (fine for daily, revisit for 1m); no data_snapshot pinning yet (latest dataset_version wins).


## Stage 3 slice 1 (research-mode backtesting) - status
- [x] Strategy contract (`strategy/base.py`: Strategy ABC, StrategyParams, Requirements, Targets, Mode) and `Context` (`strategy/context.py`): history bounded by `ctx.now()`, bar visible only after close + publish lag, no DB/broker handle. NOT yet: manifest / entry-point discovery, process sandbox (3.2), feature library (3.3).
- [x] Daily long-only backtest engine (`backtest/engine.py`): decide at close t, fill at OPEN t+1 on RAW prices, 5%-of-volume cap (remainder cancels), bonus/split share counts and cash dividends followed, held positions through unmodellable actions listed in `unmodelled`. Costs are a flagged PLACEHOLDER (flat bps) until the versioned cost_schedule exists. Not yet: futures/margin, stops/limits, product types, circuit limits, risk engine, per-day calendar.
- [x] Owner controls: reader mode explicit per run (`research`/`strict`); strict BLOCKS instruments with unresolved or provisional actions and records why; every run persists reader mode, per-instrument `adjustment_version`, provisional events (with factors), unapplied events (reported separately), blocked instruments, unmodelled events, accounting_complete, cost model, result hash (`backtest_run/trade/equity`, migration 007). `strategy/lifecycle.promotion_blockers`: a research-mode run can never support promotion; strict + clean + non-placeholder costs + accounting complete + validation protocol passed are ALL required.
- [x] Look-ahead harness (prefix-invariance: a run to T equals the prefix of a longer run) and determinism (same inputs -> same result hash).
- [ ] NOT built, needed before any strategy validation: validation protocol (walk-forward, deflated Sharpe, ...), financial ledger tables (accounting currently lives in the engine), `stage_change` table with approver, pin `data_snapshot` id on runs, `known_from`/`known_until` + announcement/record/effective/first-tradable dates on corporate actions, child-share / rights-entitlement portfolio accounting, versioned cost schedule.

## Mutation testing (mutmut 3, `make mut`)
- Scope today: pure modules with unit tests only (factors, continuity, NSE action parser, metrics, lifecycle gate, platform state machine, calendar, money, clock, lake): **946/992 killed = 95.4%**, every module >= 86%. It found real gaps that 100% coverage hid (sub-rupee dividends rejected, wrong prev-close date, `break` vs `continue` dropping later actions, UTC-vs-local conversion, unasserted event fields, a metrics crash on zero/wiped-out equity, an `assert` that should route to review).
- NOT yet mutation-tested: DB-backed modules (reader, review, engine, store, pipeline, instruments, corporate_actions). Needs a shared test database so a mutant run does not start a container each time.
- Known equivalent survivors are not worth killing (e.g. `sum(x, Decimal(0))` vs `sum(x)`).
- CI has NOT been run: there is no git remote. `make check` is the local equivalent and passes.

## Owner research on demergers (received 2026-11-07, NOT yet used)
ABB India 78.19/21.81 (1:5), Reliance 95.32/4.68 (1:1), Siemens 76.18/23.82 (1:1), HUL 98.09/1.91 (broker source only), Vedanta 52.34 + four others; ITC, Tata Motors, GMR, NMDC documents located but numbers not extracted; Motherson none found. These are TAX cost allocations, not price factors. Open decision: which price-adjustment basis to adopt per policy (docs/adjustment-policy.md: COST_ALLOCATION vs PRICE_ADJUSTMENT vs TOTAL_RETURN_ENTITLEMENT). Until decided and each figure read from the primary filing, all 10 stay PROVISIONAL.


## Owner priorities for the next stage (2026-11-07) - do not let these slip
1. **Financial ledger**: backtest positions, cash, dividends, fees and corporate-action entitlements must reconcile (cash_ledger / position_ledger / fee_ledger, every row traceable to its event; backtest P&L == ledger P&L).
2. **Realistic costs**: brokerage, STT, exchange transaction charges, GST, SEBI charges, stamp duty and slippage from a versioned `cost_schedule` with historically applicable rates (replaces the flagged placeholder).
3. **Validation protocol**: walk-forward, out-of-sample, parameter sensitivity, multiple-testing controls (deflated Sharpe, PBO) before ANY strategy promotion. Research-mode results never authorize paper/live.
4. **Mutation-test the DB-backed modules first** (reader, review, engine, store, pipeline) before trusting strict-mode correctness - needs a shared test database harness so a mutant run does not start a container.
5. Demergers: price-adjust per the evidence hierarchy in `docs/adjustment-policy.md` (exchange-determined base price first); read each primary filing; unresolved ones stay PROVISIONAL / unresolved. Never fall back to `gap` for a verified factor.
6. Add a git remote and run CI before merging / deploying (CI has never run).

## Repo hygiene lesson
An unanchored `.gitignore` entry (`data/`) silently excluded `src/algo/data/`, its tests and the fixtures from the first commit AND from ruff. Caught only by verifying from a clean clone. Keep that verification (fresh clone -> `uv sync --frozen` -> `make check`) as a pre-merge step.
