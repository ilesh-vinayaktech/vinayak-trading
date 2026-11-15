# Architecture decision records

One file per decision: context, decision, consequences, and what would make us revisit. Written 2026-11-15 from what the repository does today;
status is "accepted (as built)". A decision that changes gets a new ADR that supersedes the old one, never an edit of history.

- [ADR-001 Python 3.12 with uv](001-python.md)
- [ADR-002 Modular monolith with isolated processes for the OMS, reconciler and strategy sandbox](002-modular-monolith.md)
- [ADR-003 PostgreSQL/Timescale plus a raw file lake; no ClickHouse, no Kafka in v1](003-storage.md)
- [ADR-004 Build, do not adopt NautilusTrader (no formal spike was run)](004-build-not-adopt.md)
