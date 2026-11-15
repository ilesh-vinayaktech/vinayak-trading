# ADR-002: Modular monolith; strategy workers, the OMS log and reconciliation are kept apart

**Context.** Strategy code is the least trusted code in the system and must never reach the broker, the database or the network. Order state must
survive a crash and be reconstructible.

**Decision.** One repository and one package (`src/algo/...`) split into packages with narrow interfaces (data, backtest, execution, risk, ledger,
platform_state, research, ...). Strategy workers run in sandboxed processes (`algo.sandbox`: no network, no environment, no filesystem, CPU/memory/time
limits; strategies see data only through `Context`). Order state is an append-only, event-sourced log, reconciled against the broker. Scheduled work runs
as systemd user timers (`algo.jobs.registry`); research work serialises through one slot (`algo.research.slot`).

**Consequences.** Simple to run and test on one machine; the isolation that matters is enforced by process boundaries and adversarial tests, not by
network hops. A strategy bug cannot place an order. The cost is an IPC hop per decision.

**Revisit when** a second machine or a second operator is needed; the package boundaries are where a service split would go.
