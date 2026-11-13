# Restore the database from a backup

The `db-backup` job (every night 23:00 IST) writes `data/backups/algo_<date>.dump`: a custom-format
`pg_dump -Fc` of the `algo` database from the `algo-dev` container, 14 days kept (about 4.8 GB each).

## Restore into a throwaway database (to test a backup, or to inspect old data)
TimescaleDB needs its pre/post restore calls around `pg_restore`; without them the restore fails or
leaves the hypertables broken.

```bash
D=data/backups/algo_2026-11-13.dump
docker exec algo-dev psql -U postgres -c "create database algo_restore_test"
docker exec algo-dev psql -U postgres -d algo_restore_test \
  -c "create extension if not exists timescaledb" -c "select timescaledb_pre_restore()"
docker exec -i algo-dev pg_restore -U postgres -d algo_restore_test --no-owner < $D
docker exec algo-dev psql -U postgres -d algo_restore_test -c "select timescaledb_post_restore()"
```

Check it before trusting it: compare exact row counts per table against the live database. The restored
copy may be lower than live for anything written after the dump (the dump is a snapshot), never higher.

```sql
select table_schema||'.'||table_name,
       (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text
from information_schema.tables
where table_type='BASE TABLE' and table_schema not in ('pg_catalog','information_schema','_timescaledb_internal')
order by 1;
```

Drop the copy when done: `docker exec algo-dev psql -U postgres -c "drop database algo_restore_test"`.

## Restore over the live database (disaster)
1. `./start_all.sh stop` (API, web, worker, feed; the database container stays up).
2. Rename or drop the damaged `algo` database, create an empty one, then run the four steps above against
   it (use `-d algo`).
3. `./start_all.sh` (applies any newer migrations on start), then run `check_stale.py` and look at the
   dashboard's Platform status.
4. Data written after the dump (bars, live minutes, paper orders, portal changes) is lost: re-run
   `bhavcopy-daily` and `gap-nightly`, and the loaders for the Kite candles.

## Drill record
| date | backup | result |
|---|---|---|
| 2026-11-13 | `algo_2026-11-13.dump`, 4.8 GB | Restored in 14 min 25 s with no `pg_restore` errors. All 96 tables present; every row count is lower than or equal to live (the dump was older), e.g. `live_bar_1m` differs by exactly the 602,035 bars the feed logged afterwards. The one missing table (`screener_snapshot`) belongs to migration 053, which was newer than the dump. Hypertable and its 4 policy jobs came back. |

Not yet covered: an automated restore test in CI, and a restore of the data lake (`data/lake`), which is
not backed up (it needs a destination).
