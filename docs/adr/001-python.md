# ADR-001: Python 3.12, managed with uv

**Context.** One owner, personal capital, research-heavy work (backtests, studies, data cleaning) plus a small live path. The broker SDK (Kite Connect)
and the data ecosystem are Python-first.

**Decision.** Python 3.12, dependencies and environments through `uv`, strict typing (`mypy --strict` on `src`), `ruff` for lint and format.
Prices, quantities and money are `Decimal`, never float; time comes from an injected `Clock` (enforced by `tests/unit/test_no_system_clock_in_src.py`).

**Consequences.** Fast iteration and one language end to end. Python is slow for tick-level work, which this system does not do (daily and minute bars).
Correctness is bought with tests instead of the compiler: tests-first, a 90% branch gate overall and 100% on the money paths (`scripts/check_floors.py`).

**Revisit when** a measured latency or throughput need cannot be met by process-level parallelism or a small native extension.
