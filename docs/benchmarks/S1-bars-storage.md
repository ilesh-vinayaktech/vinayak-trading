# S1: bar storage benchmark (pass criteria written BEFORE the first run)

Question: is PostgreSQL (with TimescaleDB where installed) fast enough to hold the 1-minute bars the platform needs, for the queries it actually makes?
Reproduce: `uv run python scripts/bench_bars.py --db "$ALGO_DB_URL" --rows 5000000` (any row count; the claim is checked at the size it was run at).
The script works in a throwaway schema it creates and drops, touches no platform table, and prints one JSON line per measurement.

Workload: N instruments x one-minute bars over 375-minute sessions, synthetic prices, a table shaped like `bar_1m` (instrument_id, ts, OHLC, volume).

| # | Measure | Pass criterion |
|---|---|---|
| 1 | Bulk ingest with COPY | at least 50,000 rows/s |
| 2 | One instrument, one year of minutes (about 94,000 rows) | at most 250 ms |
| 3 | 500 instruments, one session (187,500 rows) | at most 1,500 ms |
| 4 | Daily roll-up of one instrument over a year (aggregate query) | at most 500 ms |
| 5 | Table + index size per million rows | reported only (no criterion without compression; TimescaleDB compression is judged where it is installed) |

A criterion that is missed is reported as FAIL with the number; it is not adjusted afterwards. The 100-million-row scale the TODO names is a run of the same script
with `--rows 100000000` on the production host; results at smaller sizes are labelled with the size they were measured at.

## Added before the TimescaleDB run (2026-11-15; written before that run, which is why they sit above the results)

Run with `--timescale` where the extension is installed. The table becomes a hypertable (90-day chunks, as `bar_1m`), compression is enabled (segment by instrument,
order by time), every chunk is compressed, and a continuous aggregate of daily bars is created and refreshed.

| # | Measure | Pass criterion |
|---|---|---|
| 6 | Compression ratio, uncompressed total size over compressed total size | at least 4x (synthetic prices compress differently from real ones: reported with that caveat) |
| 7 | Continuous aggregate (daily bars) initial refresh | at most 5 s per million rows |
| 8 | Criteria 2-4 again on the compressed table | the same limits |

## Results

**2026-11-15, 2,000,000 rows, 500 instruments, plain PostgreSQL on the development machine (no TimescaleDB, no compression):** ingest 127,000 rows/s (PASS),
session of 500 instruments 838 ms (PASS), daily roll-up 4 ms (PASS), one-instrument-year 15 ms (PASS but NOT MEANINGFUL: at this size each instrument has about
10 sessions, so the query returned about 4,000 rows, not 94,000). Size 121 MB per million rows uncompressed. Criterion 2 is only a real test from about 47 million
rows (500 instruments x one year); the 100-million-row run on the production host, with TimescaleDB compression measured there, is still to do.
