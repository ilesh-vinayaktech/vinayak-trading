# Decisions (spec §15)

Written 2026-11-15. Each line says who decided and where the evidence is. A line marked **OWNER** has no answer in the repository and none is assumed: the system
runs without it (paper only, no real capital), and the answer changes what is allowed to happen next.

| Decision | Status | Source |
|---|---|---|
| Language and toolchain | Decided: Python 3.12, uv, strict typing | `docs/adr/001-python.md` |
| Build or adopt a trading framework | Decided as built: build; no spike was run | `docs/adr/004-build-not-adopt.md` |
| Storage and messaging | Decided: PostgreSQL/TimescaleDB, raw file lake, no Kafka/Redis for anything durable | `docs/adr/003-storage.md`, `TODO.md` 5.3 |
| Free or paid data | Decided by the owner 2026-11-15: the Zerodha paid Kite data is the paid source already in hand; no further vendor is planned. NSE bhavcopy and public documents remain the free cross-check. | the providers in `src/algo/data/providers/` |
| Strictly personal or not | Decided by the owner 2026-11-15: PERSONAL ONLY for now. The invited-user roles and portal exist in the code (`docs/console-security-review.md`) but no other person is to use or trade through the system; revisit, with the regulatory assessment, before that changes. | spec §15 lists it as a decision |
| Capital to deploy | Decided by the owner 2026-11-15: Rs 1,00,000 (1 lakh) for PAPER trading to start; it may be raised or lowered on performance, decided by the owner case by case. No live capital is committed. | |
| Maximum acceptable drawdown | Decided by the owner 2026-11-15: configured PER TRADE (a per-trade loss limit), not one account-wide number. The validation gates still use the benchmark-relative bar in `config/validation_thresholds.json` (provisional), and the `holdout_drawdown` gate has no account-level figure from the owner; the per-trade limit is now `Limits.max_trade_loss`, default 2% (owner, 2026-11-15; None switches it off), evaluated by `risk.realtime.trade_stops`, which names the positions to exit but places no order and is not yet called by a runner. | `config/validation_thresholds.json` |
| Hours per week available | Decided by the owner 2026-11-15: most of the time (no tight hour cap). It affects how many strategies can be supervised; the system is built to need a person only for decisions (approving paper orders, verifying corporate actions, registering hypotheses). | |
| Owner-only authorities | Decided by the owner: membership VERIFIED, market-value adjustment for demergers, verification of corporate actions, first hypothesis registration | `TODO.md` D, `docs/stage4/` |

## 2026-11-16: applying the research review (owner: "fix all the suggestion as per docs/research-review-2026-11-16.md")

Each change below applies to studies and discovery batches made FROM NOW ON; nothing already judged was edited, and the global holdout (2025 onward) is still unopened for every strategy.

| Change | Where | Review section |
|---|---|---|
| Deflated-Sharpe reference: N counts every try of the same IDEA (the factor of the feature a definition ranks by) on any window; the spread of Sharpes comes only from comparable trials (same idea, same research window) | `algo/backtest/validation/registry.py` `deflation_trials`, `hypothesis_key`, `FACTORS` | 3.1 |
| Overfitting gate: when the tried variants are near-identical (mean daily-return correlation >= 0.9) it is judged on the lower end of a 90% bootstrap interval of the out-of-sample Sharpe (must be above 0); genuinely different candidates still use PBO | `evidence.py`, `gates.py` | 3.2 |
| Thresholds v3: the fixed account-wide 25% drawdown cap is off for long-only studies (`owner_max_drawdown` 1.0); the strategy is still judged against 1.25x the benchmark's drawdown, plus the per-trade stop | `config/validation_thresholds.json` | 3.3 |
| Alpha discovery: Benjamini-Hochberg false discovery rate over every test ever run (recorded as `correction` on each row); `--through` to stop at a day, `--segments` to test only the stocks a strategy trades, horizons 120 and 250 days | `algo/alpha/{stats,registry,run}.py`, `scripts/discover_alpha.py` | 3.4, 3.5, 3.6 |
| Backtest applies the paper account's per-trade stop (2%) and 5-day re-entry cooldown (`BacktestConfig.trade_stop`, `StudySpec.trade_stop`, `stop_cooldown_days`); new definition studies turn them on | `algo/backtest/engine.py`, `algo/research/study*.py`, `algo/factory/study.py` | 3.9 |
| Return-oriented strategies pre-registered before any result: MOMENTUM_12M_M, MOMENTUM_LOWVOL_M, MOMENTUM_TREND_M (market filter: share of stocks above their 200-day average) | `algo/factory/preregistered.py`, `scripts/register_preregistered.py` | 3.7 |

Integrity note: these policy changes were made after seeing that the earlier studies failed. That is a researcher degree of freedom, kept honest in three ways: the counts only go up (every try of an idea
still counts, any window); the changed rules are applied to NEW studies, re-run from scratch, not to old verdicts; and the one-time holdout stays closed until a strategy passes every gate under the new rules.

Not done from the review, and why: survivorship before 2018-08 (needs delisted names' prices from bhavcopy, a data load); fundamentals and RSI/ATR in strategy definitions (need the interpreter to read filings / all history; the old-feed crawl
is still waiting for a go-ahead); real regime labels (needs a regime definition); detecting a no-op grid knob automatically (the one found was removed by hand).
