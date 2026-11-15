# Decisions (spec §15)

Written 2026-11-15. Each line says who decided and where the evidence is. A line marked **OWNER** has no answer in the repository and none is assumed: the system
runs without it (paper only, no real capital), and the answer changes what is allowed to happen next.

| Decision | Status | Source |
|---|---|---|
| Language and toolchain | Decided: Python 3.12, uv, strict typing | `docs/adr/001-python.md` |
| Build or adopt a trading framework | Decided as built: build; no spike was run | `docs/adr/004-build-not-adopt.md` |
| Storage and messaging | Decided: PostgreSQL/TimescaleDB, raw file lake, no Kafka/Redis for anything durable | `docs/adr/003-storage.md`, `TODO.md` 5.3 |
| Free or paid data | In practice FREE so far: NSE bhavcopy and public documents, Zerodha Kite Connect for candles. No paid vendor is wired. Whether to buy a vendor feed: **OWNER** | the providers in `src/algo/data/providers/` |
| Strictly personal or not | **OWNER.** Not stated in the repository. The code has invited-user roles and a portal (`docs/console-security-review.md`), which a personal-only system would not need; whether other people may ever use it, or trade through it, is not decided here. | spec §15 lists it as a decision |
| Capital to deploy | **OWNER.** Not recorded anywhere. Paper accounts use whatever starting cash the account is created with. | |
| Maximum acceptable drawdown | **OWNER.** The validation gates use the benchmark-relative bar in `config/validation_thresholds.json` (provisional); the spec also requires the owner's own tolerance on top (`holdout_drawdown` gate). | `config/validation_thresholds.json` |
| Hours per week available | **OWNER.** Affects how many strategies can be supervised; the system is built to need a person only for decisions (approving paper orders, verifying corporate actions, registering hypotheses). | |
| Owner-only authorities | Decided by the owner: membership VERIFIED, market-value adjustment for demergers, verification of corporate actions, first hypothesis registration | `TODO.md` D, `docs/stage4/` |
