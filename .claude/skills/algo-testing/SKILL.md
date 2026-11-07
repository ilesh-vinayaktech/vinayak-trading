---
name: algo-testing
description: Testing workflow for the algo trading platform. Use whenever writing or changing code under src/algo, to enforce tests-first, coverage gates, determinism and no-lookahead rules.
---

1. Write the failing test first (unit; add a Hypothesis property test for any invariant: rounding, ledger sums, adjustment continuity, state transitions). Bug fix = failing regression test first.
2. Implement minimally. Inject `Clock`; use `Decimal`; tz-aware UTC only.
3. Integration tests use real Postgres/Redis/MinIO via testcontainers; never mock the component under test.
4. Strategy/feature code additionally needs a look-ahead test (truncate data at T, output at T unchanged) and a determinism test (same inputs => identical output hash).
5. Run `make check`. Gate: >=90% line+branch overall, 100% branch on money-path packages. Nightly `make mut`: mutation score >=85% on those.
6. Tick the matching item in `TODO.md` only after step 5 passes.
