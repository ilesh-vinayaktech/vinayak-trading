# ADR-003: PostgreSQL (Timescale) as the system of record, a raw file lake for source documents; no ClickHouse, no Kafka in v1

**Context.** Data volume is modest (about 500 Indian equities, daily bars from 2019, minute bars for a subset), queries are by instrument and date range,
and the strongest requirement is auditability: what did we know, when, and from which document.

**Decision.** PostgreSQL holds bars, corporate actions, membership, the event-sourced OMS log, research registries and costs; tables that carry evidence
are append-only (triggers refuse update and delete). Source documents (bhavcopy files, circulars, cost pages) are kept unchanged in a raw lake
(`data/lake`; saved PDFs under `data/evidence` with recorded sha256), so a number in the database can be traced to its file. Readers pin to a `known_at`
moment, so later ingests cannot change an old result. There is no message broker: scheduled jobs and database state coordinate the work.

**Consequences.** One datastore to back up and restore (`docs/runbooks`), transactional guarantees for the order log, no second engine to operate.
Large analytical scans would be slower than in a columnar store.

**Not adopted.** ClickHouse and Kafka (no workload needs them). No Parquet/DuckDB layer exists today; the lake layout would allow one.

**Revisit when** minute-bar research over the whole market makes scans the bottleneck, or live feeds need fan-out to several consumers.
