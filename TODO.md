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
- [x] BUILT (2026-11-07): pre-registration + trial counter + holdout opened once (`validation/registry.py`, migration 010); walk-forward rolling/anchored with embargo (`walkforward.py`); ±20% grid, plateau, by-year, concentration (`robustness.py`); PSR/DSR/expected-max-SR/PBO(CSCV)/stationary-bootstrap CIs (`stats.py`); `ScaledCosts` for 2x costs; pass/fail gates, missing evidence fails (`gates.py`, `config/validation_thresholds.json`). See `docs/validation.md`.
- [ ] Evidence assembler built (`validation/evidence.py`, reports store `refs`); still to build: the runner that executes a real strategy through the walk-forward and feeds it (needs the first strategy, Stage 4); regime labels beyond calendar year; benchmark series loader; capacity run at 3x capital; purged CV for ML.
- [ ] **OWNER: confirm or change `config/validation_thresholds.json` (status `provisional`) BEFORE the first strategy is validated.** A pass against provisional thresholds does not lift the promotion blocker.
- [x] T: statistics pinned to independently computed reference values; holdout second-open rejected; promotion blocked when any gate evidence is missing. Mutation 88-93% on the pure validation modules.

### 3.6 Financial ledger **(P0)** (used by backtest, paper, live)
- [ ] Tables: `cash_ledger`, `position_ledger`, `fee_ledger`, `realized_pnl`, `unrealized_pnl`, `margin_ledger`; every row references source event (fill id / charge id / corporate action id). Double-entry style, append-only; broker-reported vs internal stored separately + reconciliation diff table.
- [ ] Single canonical P&L source; dashboards query ledger views only.
- [ ] T (mandatory invariants): position = Σ fills; opening cash + movements = closing; duplicate execution cannot be booked twice (unique exec id); partial fills compose; cancelled order can't become filled without broker event; split/bonus preserve economic value; property tests with Hypothesis random fill sequences; backtest P&L == ledger P&L.

**Exit gate 3:** Look-ahead harness passes for reference strategy; adversarial sandbox suite green; golden backtest stable; ledger invariants 100% branch; coverage ≥ 90%.

---

## Stage 4: First strategy (trend-filtered momentum, Nifty 200)
- [x] Step 1-2 (2026-11-08): draft pre-registration `docs/stage4/preregistration-draft.md` (NOT registered; owner to confirm) and `scripts/stage4_readiness.py` -> `docs/stage4/readiness.json`: strict run NOT possible; blocking U1 (no point-in-time Nifty 200 membership), U2 (76+ unmapped delisted symbols), C1 (non-dividend corporate actions in review), K1 (no verified cost schedule), V1 (thresholds provisional), R1 (nothing registered).

- [x] (2026-11-08) Track A: `src/algo/strategies/nifty200_momentum.py` (Nifty200TrendMomentum, PlainMomentum baseline, IntervalMembership, explicit DataNotReady), `src/algo/research/run.py` (Purpose labels, manifest; only ENGINEERING_TEST_ONLY runs exist), unit tests incl. look-ahead/membership-leak/breadth/ties/missing-bar, engine integration tests incl. split-not-a-crash with control and byte-identical replay. Synthetic data only; nothing registered.
- [x] (2026-11-09) Apply step, PROPOSAL-ONLY (`scripts/propose_review_application.py` -> `docs/stage4/apply_proposals/`): 28 decisions -> proposals + dry run (GSPL and PEL x2 would clear; JIOFIN pre-listing stays a non-tradable placeholder). Nothing applied; needs a person's review and a schema decision for successor/continuity records.
- [x] (2026-11-09) Membership revision 3 adopted (see `docs/stage4/membership/README.md`, `DIFF_v2_to_v3.md`): all independent monthly checkpoints agree (N50 73/73, Next 50 49/49, Midcap 100 / N100 / N200 18/18); 13 exceptions (4 need instrument resolution: GSPL, JIOFIN pre-listing, PEL x2; 9 non-tradable placeholders). Point-in-time limit: listing-date handovers rest on later releases (known_at = announcement date).
- [x] (2026-11-09) Membership revision 2 (`docs/stage4/membership/`, change list `DIFF_v1_to_v2.md`): 28 review items decided (append-only `review_decision`, none applied), parser v7, row-level revocations (migration 021), reviewed placeholder replacements (022, 023), one reviewed entity equivalence; exceptions 21 -> 12, Midcap 100 / Nifty 200 agree with 18/18 monthly checkpoints. Still open: the DUMMYABFRL/DUMMYSIEMS removal releases, Next 50 vs 4 checkpoints, the apply-decisions step (aliases, instruments for GSPL/PEL, coverage), 136 corporate actions, verified cost schedule, thresholds, older universe pipeline ignores revocations.
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


## Financial ledger (priority 1) - DONE for backtests (2026-11-07)
- [x] `ledger/ledger.py`: event-sourced, append-only, triple-entry, average-cost; duplicate-booking guard; unmodelled actions flagged; `reconcile()` re-derives all balances from entries (+ price-free accounting identity + valuation check). Engine now has NO balances of its own - cash/positions/equity/P&L all come from the ledger.
- [x] Every run persists the full ledger (`backtest_ledger`, migration 008), the canonical P&L view `backtest_ledger_pnl`, `ledger_reconciled`, `reconciliation`, `pnl`; a run whose ledger does not reconcile cannot support promotion.
- [x] Tests: hand-computed postings, exact entry contents, tamper detection for every check, Hypothesis random sequences, 12 seeded engine fuzz runs (random walks + random targets + costs). Mutation score on the ledger 98.8% (668/676); suite-wide 96.8% (1618/1672).
- [ ] Still to build: broker-reported vs internal ledger + reconciliation diffs (needs live/paper OMS), margin ledger, slippage cost reporting, per-fee-type entries (arrives with the versioned cost schedule - priority 2), persisting unrealized P&L marks per day.


## Realistic costs (priority 2) - engine DONE, rates UNVERIFIED (2026-11-07)
- [x] Cost schedules are effective-dated DATA (`config/cost_schedules/`), every component citing url + sha256 + a literal quote verified against the stored document; documents captured in the raw lake (`capture_cost_sources.py`, `build_cost_schedules.py`). No rate in code.
- [x] `backtest/costs/`: validated schedule model (+ `ScheduleBook`: refuses unverified/uncovered dates), per-order itemised calculator (brokerage incl. Rs 20 cap, STT, NSE transaction, SEBI, stamp duty, DP charge, GST, contract-note minimum), slippage model (base + participation + volatility + illiquidity, capped), engine-facing `CostPolicy` (flat placeholder or schedule-based), contract-note reconciliation tool.
- [x] Engine: fills and charges from the policy, all-in affordability by bisection, itemised charges in the ledger (fee entry + cash entry per type), per-trade explanation persisted (`backtest_trade.charges`), `backtest_ledger_fees` view; promotion blocked by placeholder costs, unverified/assumed schedules, zero slippage.
- [x] Tests: hand-computed orders (delivery buy 118.74, sell 129.46, intraday buy 30.34, sell 52.63), end-to-end 99-share delivery buy and round trip with DP charge reconciling to the paisa; mutation 95%+ on the cost modules.
- [ ] **A PERSON must verify every quote** against its document, then set status `verified` (until then research-only).
- [ ] Zerodha page has no effective dates: brokerage, DP charge, GST, SEBI fee history is NOT evidenced. Need archived schedules or contract notes. The `assumed_backfill` schedule (2020-07-01 .. 2026-02-28) extends today's rates and is approximate (exchange member tariff was slab-based before Oct 2024).
- [ ] Acceptance test: reconcile to REAL contract notes (`reconcile_note` is ready) and to Zerodha's brokerage calculator. Needs sample contract notes from the owner.
- [ ] Open questions from the published page: the footnote "SEBI charges will be reduced to Rs 15 per crore" (recorded verbatim, wording unexplained, not applied); IPFT listed separately by Zerodha although NSE's 306.99 + 0.01 = 307 suggests it is inside 0.00307%.
- [ ] Not yet: intraday product in the engine, equity futures (STT history 0.01/0.0125/0.02/0.05% is in the fetched circulars), intraday/quote data for stronger execution simulation.


## Validation protocol (priority 3) - toolkit DONE, no strategy validated yet (2026-11-07)
- [x] Statistics, walk-forward, robustness, cost stress, gates, registry (details in `docs/validation.md`). 765 tests, 100% line+branch, validation package floored at 100%.
- [x] `summary()` now looks up a stored report: only a PASSING report made against CONFIRMED thresholds clears `validation_protocol_passed`.
- [ ] Owner confirms thresholds; the first strategy (Stage 4) is the first real user of the toolkit.


## Benchmark loader (2026-11-07) - storage DONE, official TRI data NOT YET LOADED
- [x] `data/benchmark.py` + migration 012: benchmark / benchmark_observation, immutable (DB trigger), PRICE / TOTAL_RETURN / NET_TOTAL_RETURN never mixed, conflicting re-ingest rejected, exact-date alignment (a gap is an error), `dataset_hash` + `references()` for report refs, `gate_returns()` refuses non-TOTAL_RETURN series.
- [ ] **Acquire official historical TRI levels** (primary: Nifty 200 TRI gross; secondary: Nifty 50 TRI gross; diagnostic: Nifty 200 price) from NSE Indices, store the raw files in the lake, ingest. Do NOT approximate a TRI from a dividend yield. Until then benchmark gates fail for missing evidence.
- [ ] **Point-in-time universe**: Nifty 200 membership must reflect additions/removals over time (we only hold the current snapshot) - required before any strategy result is trusted (survivorship bias).
- [ ] Not yet: information ratio / beta reporting, lag/`methodology_version` handling across index methodology changes.


- [x] (2026-11-08) Symbol classification (read-only) `docs/stage4/symbol_classification/`: of 839 unmapped/placeholder symbols only 11 belong to the Nifty 200 family (151 rows); 0 mapped rows point at a different issuer. Open: effective dates for DHANI/MINDTREE rows, NESTLEIND ISIN history, placeholders, PEL/GSPL/ABIRLANUVO/DALMIABHA successors, HEXAWARE/BHARATFIN. Person review required before any mapping is written.

## Stage 4A: point-in-time universe (2026-11-07) - model DONE, NO history loaded yet
- [x] `data/universe.py` + migration 013: append-only `index_membership_event` (ADD/REMOVE, announcement vs effective date kept apart, source url + document hash, VERIFIED/PROVISIONAL/REJECTED), declared `index_membership_coverage`, derived intervals, `members_on(day, known_on=)` (no announcement leakage), `coverage_report`. Outside verified coverage membership is UNKNOWN (`UniverseGap`), never today's list; inconsistent histories (double ADD, REMOVE of a non-member) raise instead of being guessed away.
- [ ] **Load the history**: collect NSE Nifty 200 reconstitution circulars (semi-annual, from ~2015), extract ADD/REMOVE with announcement + effective dates, store raw documents in the lake (hash), walk back from the verified current snapshot (`index_snapshot`), cross-check any official historical snapshots, resolve symbol changes to permanent instrument ids, then have a PERSON verify events and coverage. Do not infer missing changes from "there must be 200 members". The community nse-index-history project is a cross-check only. Report anything before the defensible start (~2015) as unavailable.
- [ ] Separate later: `strategy_eligibility` (liquidity, history length, suspension) computed point-in-time on top of membership; the engine/Context must take its universe from `members_on`.
- [ ] Not yet: wiring the universe into `Context`/engine; delisted-security price retention check; ETF/other indices.

### Stage 4A data acquisition - circulars CAPTURED, not yet parsed (2026-11-07)
- [x] `scripts/capture_index_circulars.py`: stored the niftyindices.com press-release index page and 212 index-change press releases (2015-01 .. 2026-10) untouched in the lake (`data/lake/raw/niftyindices/`, sha256 manifests). Sequential, resumable, stops on any refusal; no refusals occurred. The title filter is heuristic - a person must check no relevant release was missed.
- Findings that shape the parser (not yet handled):
  * **Nifty 200 is defined as Nifty 100 + Nifty Midcap 100.** Releases list changes per component index; an explicit "NIFTY 200" section exists in only 27 documents. Membership must be derived from Nifty 50 / Next 50 / Midcap 100 sections (moves between Next 50 and Midcap 100 net out) AND cross-checked against explicit Nifty 200 sections.
  * **The definition changed**: from the Feb 2018 review (effective 2 Apr 2018) "Full Midcap 100" became "Free float Midcap 100", renamed "Nifty Midcap 100". Events before and after are not the same index.
  * Release shapes vary: periodic semi-annual reviews, mid-cycle replacements (delistings/mergers), corporate-action adjustments, demerger placeholder ("dummy") symbols and later exclusions, renamings, criteria revisions. Structured numbered sections ("1) NIFTY 200" with excluded/included tables) appear from 2017; 2015-2016 releases use a different (CNX-era) format and have no such sections.
  * Sections per year suggest gaps: 2024 and 2025 show one explicit Nifty 200 section each though two reviews occur per year - the second is in a layout the survey did not match. Defensible coverage may start in 2017, not 2015.
- [ ] Next: parser producing PROVISIONAL candidate events (index, ADD/REMOVE, symbol, announcement date from the release, effective date from "effective from X (close of Y)"), mapped to permanent instrument ids via `instrument_alias`; unmapped symbols reported, never dropped; reconcile the derived Nifty 200 against the current official snapshot (`index_snapshot`) walking backwards - any disagreement = a gap, not a guess. Then a PERSON verifies events and coverage.

### Stage 4A parser, stages 1-2 (2026-11-07) - extraction + classification DONE; derivation NOT built
- [x] `providers/nse_index_releases.py` (parser v1) + `data/index_releases.py` + migration 014 + `scripts/parse_index_releases.py`: 189 releases from 2017 parsed into PROVISIONAL `index_release_row` evidence (page, section, raw text, effective date, mapping status). Result: 137 REPLACEMENT_TABLES, 13 COMPANY_NOTICE (single corporate action, one index table), 39 MANUAL_REVIEW. Component rows stored: Nifty 50 / Next 50 / Nifty 100 / Midcap 100 (pre-2018 variants kept separate) / Nifty 200.
- Deliberately strict: notices that name several companies, several dummy symbols or several index tables are NOT parsed (e.g. Tata Motors/TMCV, ITC Hotels, Siemens Energy, Vedanta x4, Kwality Wall's) - they stay in the manual queue (`scripts/parse_index_releases.py` prints it). Scanned PDFs (2018-09-24) have no text layer: manual. The 2020-05-13 reconstitution narrative (Yes Bank acceleration, March 2020) is manual.
- **BLOCKER FOUND: 76 component rows reference symbols with no instrument** (JETAIRWAYS, DHFL, HDFC, MINDTREE, RELCAPITAL, SYNDIBANK, ALBK, ORIENTBANK, PEL, ... - delisted / merged names). The instrument master does not contain the delisted universe, so removed stocks cannot be tied to permanent ids or prices. Also NESTLEIND has an alias that is not valid at the 2019 effective date (alias validity vs symbol history to be checked). Building the delisted universe is now a prerequisite for a survivorship-free universe AND for backtests.
- [ ] Stage 3 (not built): derive Nifty 200 = (Nifty 50 + Next 50 + Midcap 100) membership as a UNION (transfers between components net out), versioned methodology boundary at 2018-04-02 (Full -> Free-float Midcap 100), forward AND backward reconstruction compared, the 27 explicit Nifty 200 sections as independent checkpoints, discrepancies preserved (never forced to 200), output as PROVISIONAL `index_membership_event`. Then a person verifies.
- [ ] Record, unresolved: calendar page says Nifty 200 rebalances annually in June; factsheet and releases say semi-annual. Releases' actual effective dates rule; no June/December changes are manufactured.

### Delisted universe (2026-11-07) - first slice APPLIED to dev DB, UNVERIFIED
- [x] `data/delisted.py` + `scripts/build_delisted.py` (+ migration 015 `supplement` status): instruments are created ONLY from evidence we hold - a former Nifty 50/100/200 component symbol that traded in the bhavcopy we hold, is absent from the master, and stopped appearing before the end of the data. delisted_on = day after the last trade seen; `meta.verified=false` and the basis are recorded. Bars come from the stored raw files into the day's existing dataset version (no network, no new versions).
- Applied: 18 instruments (ALBK, DHANI, DHFL, FCONSUMER, FRETAIL, GRUH, GSKCONS, HDFC, IDFC, ISEC, JETAIRWAYS, MINDTREE, ORIENTBANK, RELCAPITAL, SINTEX, SYNDIBANK, TATAMTRDVR, TV18BRDCST), 13,894 bars, 319 press-release rows re-mapped. Release component rows now 1054 MAPPED / 25 UNMAPPED / 5 PLACEHOLDER.
- **Needs a person (not auto-created):**
  * SUCCESSOR_SUSPECTED: PEL (-> PIRAMALFIN?), GSPL (-> GNRL / GUJENERGY?), IBVENTURES (see next point).
  * **IBVENTURES / DHANI look like ONE company**: IBVENTURES' last trade is 2020-10-27 and DHANI's first is 2020-10-28, adjacent in the data. DHANI was created as its own instrument; if confirmed, IBVENTURES' alias must be attached to that instrument (otherwise its history is split).
  * ALIAS_VALIDITY_GAP: NESTLEIND (alias starts 2023-08-01; same company, history before is unmapped).
  * NEEDS_EVIDENCE (no bhavcopy trading evidence; traded before 2019-10 or renamed): BHARATFIN, DALMIABHA. 25 release rows overall remain unmapped; names that left before 2019-10 have no price data at all.
- **Source finding: NSE's symbol-change file is incomplete** (e.g. DALMIABHA->DALBHARAT, PEL->PIRAMALFIN are absent), so renames/mergers cannot be told from delistings by the master alone. Delisting dates here are INFERRED from trading disappearing, not from exchange delisting notices - verify before relying on them.
- [ ] Not done: pre-2019-10 prices (legacy bhavcopy) for names that left earlier; ETF master; delisting notices / mergers as corporate actions (a merged-out company's last price is not a return to zero); `instrument_terms` for the new instruments; the reader/engine have not been exercised on delisted instruments (positions in a delisted name need a terminal-value rule).

### Stage 3 derivation (2026-11-07) - BUILT, evidence does NOT reconcile; nothing stored
- [x] IBVENTURES -> DHANI confirmed same company (owner-asserted: company intimation 2020-10-06, NSE circular NSE/CML/46118 of 2020-10-22, symbol change effective 2020-10-28). One instrument, both symbols kept as aliases, recorded as COMPANY_NAME_CHANGE (not a delisting); history 2019-10-01..2025-10-27 is continuous. Status `asserted_pending_isin_check`; the circular/intimation are not yet in the lake and ISIN continuity is unchecked. DHANI's later (2025) merger is separate and its inferred delisting date remains unverified.
- [x] Parser v2: NSE wraps long dates across lines ("March\n31, 2022"); v1 silently left 1,363 rows undated (incl. the whole Feb 2022 and Jun 2025 reviews). Now 0 undated; unparsed documents 36.
- [x] `data/universe_derive.py` (pure) + `data/universe_build.py` + `scripts/derive_universe.py`: Nifty 200 = Nifty 50 + Next 50 + Midcap 100 as a UNION (transfers net out); two series split at 2018-04-02 (`NIFTY200_M1` Full Midcap, `NIFTY200` Midcap 100 incl. its Free-float label); checks = component alternation, final state vs the current official snapshot, explicit "NIFTY 200" rows as checkpoints, backward counts from the snapshot. Announcement and effective dates kept separate on every derived event. Persist (`--apply`) writes only reconciling instruments as PROVISIONAL events and declares NO coverage.
- **Result on real data (not forced):** 246 + 36 derived changes; discrepancies: 42 NON_ALTERNATING, 22 SNAPSHOT_MISMATCH, 42 CHECKPOINT_MISSING, 14 CHECKPOINT_EXTRA, 36 MANUAL_DOCUMENT, 19 UNMAPPED_EVENT, 5 PLACEHOLDER_EVENT; backward member counts differ from 200 at 22 of 24 change dates (198..211). Problems cluster on specific dates (2018-04-02, 2020-06-26, 2017-09-29, 2022-09-30, 2024-03-28), i.e. specific missing/unparsed releases.
- **Known evidence gaps:** the 2018-02-21 release (effective 2018-04-02) lists Nifty 50 / Next 50 / Nifty 500 but NO Midcap 100 or Nifty 200 section - those changes were published elsewhere (not captured) or only in other documents. The March 2020 changes (and the 2020-05-13 narrative: Yes Bank acceleration) are not parsed, which breaks alternation at 2020-06-26. HUDCO shows two exclusions (2021, 2026) with no inclusion between: a release is missing.
- [ ] Next: find the missing releases (title filter / other NSE sources such as the Nifty 200 / Midcap 100 factsheet archive and per-review "Nifty indices constituent change" circulars), parse the 36 manual documents, then re-run; only then verify and declare coverage. Mutation testing of the new modules and the DB-backed glue is still pending.

### Stage 3 evidence work (2026-11-07) - see docs/universe-evidence-review.md
- [x] Captured 15 more releases (deferment notices, methodology changes, exclusions) via `capture_index_circulars.py --also`; every one stored untouched with sha256.
- [x] March 2020 explained and encoded (`index_release_override`, `scripts/record_overrides.py`); 2018-04-02 modelled as a definition change; parser v4: sub-headed sections, wrapped dates, explicit classification of all 204 documents (160 PARSED / 20 NOT_RELEVANT / 21 MANUAL_REVIEW_REQUIRED / 3 UNSUPPORTED_FORMAT).
- [x] Exclusions resolve on their last member day; inferred aliases extend back to earlier evidence (`extend_inferred_aliases`).
- [x] Mutation: universe_derive 90.6%, nse_index_releases 90.3% (gate 85%).
- [ ] Remaining before any membership is stored: read the 24 documents; component-level reconstruction (before the union); find the releases/files outside the press-release index (Midcap 100 / Nifty 200 constituent lists, factsheet archive); resolve HUDCO and the other NON_ALTERNATING cases; ISIN/circular evidence for IBVENTURES->DHANI; person verifies.

### Archive search + component check (2026-11-07)
- [x] niftyindices.com has no public historical constituent archive (only current lists/factsheets). Captured today's Nifty 50 / Next 50 / Midcap 100 / Nifty 200 lists (ISINs included) + methodology PDF (`capture_current_lists.py`, `load_current_lists.py`); union of the three components == Nifty 200 list exactly.
- [x] Component-level check (`check_component_snapshots`): 57 mismatches (Midcap 100 35, Next 50 19, Nifty 50 3), clustered on review dates - these are where a component's own history is wrong even if the union looks plausible. Next: inspect those dates' releases (2022-09-30 first); check Nifty 100 sections as a Next50+Nifty50 cross-check; the methodology PDF's rules (Next 50 methodology changed 2023) may explain moves between components.
- [ ] Historical constituent data would need the NSE index data subscription (owner decision) - it would replace most of this reconstruction.

### Source found: NSE Indices monthly constituent archive (2026-11-07) - NOT yet downloaded
- niftyindices.com "Archives of Daily/Monthly Reports": POST `/reports/historical-data/Index/` {SelectedReportType: "4" (Indices - Market Capitalisation & Weightage) or "2" (Nifty 50 & Next 50 incl. beta), SelectedDate: "", MonthYear: "Mar 2020"} returns `/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMar2020.zip`.
- Verified: the Mar 2020 zip (5.3 MB, 40 PDFs) has one PDF per index incl. NIFTY_50, NIFTY_Next_50, NIFTY_Midcap_100, NIFTY_100, NIFTY_200, NIFTY_500 with month-end constituents (symbol, name, industry, price, index mcap, weight %). Availability: Jan 2014 .. Oct 2026 present; Jan 2005 / Jan 2010 absent.
- Use: month-end snapshots as INDEPENDENT checkpoints for forward/backward reconstruction (resolution = month-end; intra-month effective dates still come from releases). ~150 zips x ~5 MB. Owner OK needed for the bulk download (slow, sequential, stop on refusal).
- Same site: Total Returns Index / Net TRI / historical index levels are served by the form on /reports/historical-data (endpoint not yet identified); NSE "Price and Volume Data Per Security" may give pre-2019 prices. Neither tested.

### Monthly constituent archive (2026-11-07) - DOWNLOADED, parsed, reconciled
- [x] 118 archives (2017-01..2026-10, 321 MB) stored untouched + verified; parser (coordinate-based) 0 problems on 410 snapshots; storage with identity resolution; month-to-month reconciliation vs press-release events (`scripts/reconcile_monthly.py`).
- [x] Parser fix found via the reconciliation: lettered section headings (`a) NIFTY 50`) - explained the whole Sep 2020 cluster. Parser v5 for releases.
- Result: transitions that reconcile exactly - Nifty 50 105/117, Next 50 89/93, Nifty 100 59/62, Midcap 100 55/62, Nifty 200 54/62. Remaining findings cluster at 2018-04 (definition change), **2021-09 (scanned release pr_ind_prs23082021)**, 2018-02, 2017-09, 2018-06.
- **Limit:** the archive has Midcap 100 / Nifty 200 only through 2022-03 (afterwards only Nifty 50, and Next 50 from 2024-04). 2022-04..2026-10 Midcap 100 / Nifty 200 still rest on press releases + the current lists.
- [ ] Next: OCR/read the scanned 2021-08-23 release (or accept the snapshot delta as an UNDATED change); look at 2018-02 / 2017-09 / 2018-06 findings; decide how to use month-end snapshots as primary membership evidence with press-release events only for exact dates; then the TRI endpoint (separate step); mutation of DB-backed modules.

### Evidence recovery round 3 (2026-11-07)
- [x] Parser v6 ("... Index" headings) + v5 (lettered sections) explained Feb 2018, Jun 2018, Sep 2020 and most of Sep 2017.
- [x] Scanned Sep 2021 release: re-fetched (same bytes); date documented on page 1 and in pr_ind_prs15092021; local OCR (rapidocr, throwaway env - NOT a project dependency) transcribed to `config/transcriptions/pr_ind_prs23082021.json`; EXACT match with the Aug->Sep 2021 official snapshots on all 5 indices + visual check; loaded PROVISIONAL via `scripts/apply_transcriptions.py` (hash-checked, idempotent). The SNAPSHOT_INFERRED_UNDATED fallback was not needed.
- Reconcile exactly now: Nifty 50 107/117, Next 50 90/93, Nifty 100 60/62, Midcap 100 58/62, Nifty 200 58/62. Remaining: 2018-04 (definition change), 2017-09 (8), 2017-12 (6), 2017-05 (4), 2023-08 / 2026-04 / 2026-06 (4 each).
- [ ] Other scanned releases still UNSUPPORTED: pr_ind_prs24092018, pr_ind_prs19062023 (Next 50 methodology) - same OCR route if needed. Strict-mode rule stands: undated/unverified intervals must block, never be filled.

### Constituent-history round 4 (2026-11-07) - evidence FROZEN (not verified)
- [x] All findings categorised (`categorize`); identity fix (one symbol = one key) removed the Sep/Dec/May 2017 and Nestle clusters; per-index coverage report (`coverage`); 3 scanned releases read (2 not relevant, 1 constituent changes) with OCR + visual check; zero-row transcriptions supported.
- [x] Evidence manifest `docs/evidence-manifest.json` (`scripts/freeze_evidence.py`).
- Stopping condition status: all discrepancies classified; strict-mode blocks listed in docs/universe-evidence-review.md; forward (month-to-month) and backward (from current lists) reconstructions both exist; fresh-clone + mutation to be re-run after this commit.
- [ ] Still open (bounded, optional): hand-transcribe the 11 placeholder/demerger notices (Jio 2023-07, ITC Hotels, Siemens, Tata Motors, HUL spin-off, Vedanta) so their effective dates enter the database.
- [ ] NEXT: TRI ingestion (Nifty 200 TRI primary, Nifty 50 TRI secondary, Nifty 200 price diagnostic only; gross and net kept separate).

### TRI endpoint investigation (2026-11-07) - see docs/tri-endpoint-report.md
- [x] Contract identified (POST /BackPage/getTotalReturnIndexString, cinfo string, dd-Mon-yyyy, JSON in text/html, no cookies needed); series verified as Nifty 200 TOTAL RETURN to the basis point vs the 30 Oct 2026 factsheet (QTD, YTD, 1y, 5y, since inception); history from 2004-01-01 = 1000; Net TRI NOT published for Nifty 200; server does not enforce the UI's 1-year limit (we comply anyway).
- **Finding about OUR data:** the TRI has a value for Sunday 2026-02-01 (Budget special session); our bhavcopy/calendar has no such day. Daily bars miss special weekend/muhurat sessions - fix before relying on session calendars (backtest dates, benchmark alignment).
- [ ] Next: capture Nifty 200 TRI 2004..today (<=365-day windows, raw to lake), parse, validate, ingest via data/benchmark.py, re-verify; then Nifty 50 (+NTR), then Nifty 200 price index (diagnostic).

### Nifty 200 Gross TRI captured, validated, ingested (2026-11-07) - see docs/tri-endpoint-report.md
- [x] 23 raw windows in the lake; 5,673 observations (2004-01-01..2026-11-06) via the benchmark loader; validation + factsheet reconciliation stored separately (`benchmark_validation`); `validated()` ties a report to the exact data. Gate NOT enabled.
- [x] Special sessions: SessionCalendar session types + `config/exchange_sessions.json` (28 sessions with evidence); official bhavcopy loaded for the 10 sessions inside our bars (incl. recovered Muhurat 2021-11-04); benchmark/bars agree on all ten.
- [ ] Revisit: re-fetch TRI later and compare (revision behaviour); Nifty 50 TRI (+NTR), Nifty 200 price index (diagnostic); 2022-08-08 bhavcopy (quarantined xlsx); special-session kinds/hours (official notices); weekday special sessions before 2019-10.
