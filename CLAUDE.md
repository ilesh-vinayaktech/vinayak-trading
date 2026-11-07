# Algo trading platform

Spec: `Algo Trading Platform Developer Spec v1.md`. Plan/progress: `TODO.md` (check items off as done).
Python 3.12 + uv. Rules: see `.claude/skills/algo-testing/SKILL.md` (tests-first, 90% branch gate, 100% on money paths).

- `make check` (lint+types+coverage+floors) must be green before declaring anything done; paste the output.
- Never call the system clock in `src/`; inject a `Clock`. Prices/qty are `Decimal`, never float.
- Strategies only see data via `Context`; no DB/broker/network handles.
- New module under `src/algo/` needs a matching `tests/**/test_<module>.py` (enforced by `tests/test_every_module_has_test.py`).
- Money-path packages (risk, execution, ledger, data/adjust, backtest/costs, platform_state) are floored at 100% branch in `scripts/check_floors.py`.
