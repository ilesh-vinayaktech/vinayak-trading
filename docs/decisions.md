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
| Maximum acceptable drawdown | Decided by the owner 2026-11-15: configured PER TRADE (a per-trade loss limit), not one account-wide number. The validation gates still use the benchmark-relative bar in `config/validation_thresholds.json` (provisional), and the `holdout_drawdown` gate has no account-level figure from the owner; a per-trade stop is not yet a configured limit in the risk engine. | `config/validation_thresholds.json` |
| Hours per week available | Decided by the owner 2026-11-15: most of the time (no tight hour cap). It affects how many strategies can be supervised; the system is built to need a person only for decisions (approving paper orders, verifying corporate actions, registering hypotheses). | |
| Owner-only authorities | Decided by the owner: membership VERIFIED, market-value adjustment for demergers, verification of corporate actions, first hypothesis registration | `TODO.md` D, `docs/stage4/` |
