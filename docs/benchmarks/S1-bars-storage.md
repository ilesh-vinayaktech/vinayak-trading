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

**2026-11-15, TimescaleDB 2.17.2 (the development container), synthetic, 5,000,000 rows, 500 instruments (`--timescale`):** all nine criteria PASS (ingest about 238,000 rows/s,
daily continuous aggregate 0.3 s per million rows, queries unchanged or faster after compression). The 74.6x compression ratio is an artefact of the synthetic
prices (a repeating pattern) and is NOT evidence about real data.

**2026-11-15, the real `bar_1m` table in the development database (396,118,296 rows, 2016 to 2026-11-13; already four times the 100-million-row scale the TODO named):**
- Compression, from TimescaleDB's own statistics: 53 GB before, 6,592 MB after, **8.2x**. This is the real figure.
- Criterion 2, one instrument over the last year (92,693 rows, compressed chunks): **581 ms, FAIL** against 250 ms. The criterion stands as written.
- Criterion 3, one whole session across the universe: 2026-06-12 returned 184,814 rows in 667 ms (the shape of criterion 3, PASS); 2026-11-13 returned 768,922 rows
  (about four times as many instruments with minute bars, from the live feed) in 2.8 s, about 3.7 microseconds a row either way.
- Criterion 4, a year of daily roll-ups for one instrument: 69 ms, PASS.

What the failure means: daily research and the feature job read `bar_1d`, not `bar_1m`, so no current workload is affected; a minute-bar study that reads one stock for a
year at a time would feel 0.6 s per read. Nothing has been tuned (segment-by, order-by, chunk size) and no claim is made that it can be; that is a decision for the day an
intraday strategy needs it.
