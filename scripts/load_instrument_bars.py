# ruff: noqa: E501  (a report script)
"""Load ONE instrument's missing daily bars from raw bhavcopy files already in the lake, and reconcile.

DRY RUN BY DEFAULT: everything runs in one transaction that is rolled back; --apply commits. Never fetches, never changes the
identity tables or the membership deliverables. Rows join the dataset version of the partition they came from.

Reconciliation (the dry run is the exact manifest of what --apply would insert):
  - member sessions the membership deliverable expects for the instrument (docs/stage4/membership/membership_intervals.csv)
  - stored raw sessions in the lake for the window and the rows the instrument's alias maps to, with each file's SHA-256
  - bars already loaded, bars the load would add, expected member sessions still without a bar
  - the effect on per-session strict eligibility, recomputed (not promoted) with algo.data.membership_coverage, with the
    remaining blockers named (so an unchanged eligible count is explained, not asserted)
  - price continuity of the added series against the existing one
usage: load_instrument_bars.py --db URL --instrument 2653 --lake data/lake --from 2019-10-01 --to 2023-07-31 [--apply]
       [--out-dir docs/stage4/bars]"""

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.lake import LocalLake
from algo.data.membership_coverage import Event, MemberSpan, session_coverage
from algo.data.pipeline import backfill_instruments
from algo.data.providers.base import NotPublishedError, ParseError
from algo.data.providers.nse_bhavcopy import NseBhavcopy
from algo.data.sessions import calendar

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--instrument", type=int, required=True)
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
ap.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
ap.add_argument("--membership", type=Path, default=Path("docs/stage4/membership"))
ap.add_argument("--out-dir", type=Path, default=Path("docs/stage4/bars"))
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
iid, iso = a.instrument, date.fromisoformat
mode = "applied" if a.apply else "dry_run"
now = datetime.now(UTC)
lake = LocalLake(a.lake)
prov = NseBhavcopy(
    lambda url: b"", calendar(Path("config/exchange_sessions.json"))
)  # parse only: never fetches

spans = [MemberSpan(r["entity"], iso(r["start"]), iso(r["end_exclusive"]) if r["end_exclusive"] else None)
         for r in csv.DictReader((a.membership / "membership_intervals.csv").open())]  # fmt: skip
events = [Event(r["entity"], iso(r["effective_from"]), iso(r["announcement_date"]))
          for r in csv.DictReader((a.membership / "membership_events.csv").open())]  # fmt: skip
cj = json.loads((a.membership / "membership_coverage.json").read_text())
checked_until = iso(
    cj["independent_checks_by_period"]["N100/N200/Midcap 100 monthly constituents"][1]
)
verified = not cj["verification_status"].startswith("PROVISIONAL")
member_ids = sorted({int(s.entity[2:]) for s in spans if s.entity.startswith("i:")})
mine = [s for s in spans if s.entity == f"i:{iid}"]
lo, hi = iso(cj["window"][0]), iso(cj["window"][1])


def coverage(conn: psycopg.Connection):
    sessions = [r[0] for r in conn.execute(
        "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date d FROM bar_1d WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s ORDER BY d", (lo, hi))]  # fmt: skip
    bars = {(i, d) for i, d in conn.execute(
        "SELECT DISTINCT instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date FROM bar_1d WHERE instrument_id = ANY(%s) AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s", (member_ids, lo, hi))}  # fmt: skip
    return session_coverage(
        sessions, spans, events, lambda i, d: (i, d) in bars, checked_until, verified
    )


def series(conn: psycopg.Connection):
    return conn.execute(
        "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, close FROM bar_1d WHERE instrument_id=%s ORDER BY ts",
        (iid,),
    ).fetchall()


report: dict = {"instrument_id": iid, "window": [str(a.start), str(a.end)], "mode": mode}
with psycopg.connect(a.db, autocommit=True) as conn:
    sym, name, isin = conn.execute(
        "SELECT symbol, name, isin FROM instrument WHERE instrument_id=%s", (iid,)
    ).fetchone()  # type: ignore[misc]
    report["instrument"] = {"symbol": sym, "name": name, "isin": isin}
    days = [iso(n[3:]) for n in sorted(p.name for p in (a.lake / "raw/nse/bhav").glob("dt=*"))]
    days = [d for d in days if a.start <= d <= a.end]
    before_series = series(conn)
    before_cov = coverage(conn)
    # the raw files: rows the instrument's alias maps to, with each file's checksum
    raw_rows, raw_days, holidays = 0, 0, 0
    manifest = []
    for d in days:
        alias = conn.execute(
            "SELECT source_symbol FROM instrument_alias WHERE instrument_id=%s AND source='nse' AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)", (iid, d, d)).fetchone()  # fmt: skip
        v = lake.versions("nse", "bhav", d)
        if alias and v:
            try:
                n = sum(1 for b in prov.parse("bhav", d, lake.get(v[-1])) if b.symbol == alias[0])
            except (
                NotPublishedError,
                ParseError,
            ):  # holiday file (previous day's data) or a non-calendar day
                holidays += 1
                continue
            raw_rows += n
            raw_days += 1 if n else 0
            manifest.append(
                {"day": str(d), "raw_sha256": v[-1].checksum, "symbol": alias[0], "rows_in_file": n}
            )
    with conn.transaction(force_rollback=not a.apply):
        results = backfill_instruments(conn, lake, prov, "bhav", days, {iid}, now)
        after_series = series(conn)
        after_cov = coverage(conn)
    status = Counter(r.status for r in results)
    inserted = sum(r.rows for r in results)
    final_series = series(conn)  # outside the transaction: what persists

report["raw"] = {
    "stored_sessions_in_window": len(days),
    "holiday_files_skipped": holidays,
    "sessions_with_a_row_for_the_alias": raw_days,
    "rows": raw_rows,
}
report["load"] = {
    "status_by_day": dict(status),
    "rows_inserted": inserted,
    "already_loaded_rows": sum(r.already_loaded for r in results),
}
report["bars"] = {
    "before": len(before_series),
    "after_inside_transaction": len(after_series),
    "persisted_now": len(final_series),
}
exp = sorted(
    d.day
    for d in before_cov
    if any(s.start <= d.day and (s.end is None or d.day < s.end) for s in mine)
)
have_before = {d for d, _ in before_series}
have_after = {d for d, _ in after_series}
report["member_sessions"] = {
    "expected_in_window": len(exp), "with_bar_before": sum(d in have_before for d in exp), "missing_before": sum(d not in have_before for d in exp),
    "with_bar_after": sum(d in have_after for d in exp), "missing_after": sum(d not in have_after for d in exp),
}  # fmt: skip
rets = [abs(float(b[1] / a_[1] - 1)) for a_, b in zip(after_series, after_series[1:], strict=False)]
report["continuity"] = {
    "max_abs_daily_return_after": round(max(rets), 4) if rets else None,
    "sessions_over_25pct": sum(r > 0.25 for r in rets),
}
eb, ea = (
    sum(c.eligible_once_verified for c in before_cov),
    sum(c.eligible_once_verified for c in after_cov),
)
blockers: Counter[str] = Counter()
for c in after_cov:
    if f"i:{iid}" in c.members and not c.eligible_once_verified:
        blockers.update(
            [
                *c.untradable,
                *(f"RETROSPECTIVE {e}" for e in c.retrospective),
                *(f"no bar {e}" for e in c.missing_bars),
            ]
        )
newly_ok = sum(
    1
    for b, c in zip(before_cov, after_cov, strict=True)
    if c.eligible_once_verified and not b.eligible_once_verified
)
report["strict_effect"] = {"eligible_once_verified_before": eb, "after": ea, "newly_eligible_sessions": newly_ok,
                           "remaining_blockers_on_sessions_where_the_instrument_is_a_member": dict(blockers.most_common())}  # fmt: skip
sha = hashlib.sha256(
    json.dumps(
        [[str(r.day), r.instrument_id, r.status, r.rows] for r in results], sort_keys=True
    ).encode()
).hexdigest()
report["manifest_sha256"] = sha
report["manifest_inputs"] = {
    "raw_files": len(manifest),
    "raw_files_sha256_of_list": hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest(),
}
a.out_dir.mkdir(parents=True, exist_ok=True)
stem = f"{sym.lower()}_{iid}_bars_{mode}"
(a.out_dir / f"{stem}.json").write_text(
    json.dumps(
        {
            **report,
            "days": [
                {
                    "day": str(r.day),
                    "status": r.status,
                    "rows": r.rows,
                    "already_loaded": r.already_loaded,
                }
                for r in results
            ],
            "raw_files": manifest,
        },
        indent=1,
    )
    + "\n"
)
ms = report["member_sessions"]
L = [f"# {sym} (instrument {iid}, {isin}) bar load: {'APPLIED' if a.apply else 'DRY RUN (rolled back; nothing written)'}", "",
     f"Window {a.start}..{a.end}. Source: stored NSE bhavcopy files only (never fetched). Manifest SHA-256 `{sha}`; per-day detail and every raw file's SHA-256: `{stem}.json`.", "",
     "| item | value |", "|---|---|",
     f"| member sessions expected by the membership deliverable (2020-10-01..) | {ms['expected_in_window']} |",
     f"| stored raw files in the window / holiday files (hold the previous day) / sessions with a row for the alias / rows | {len(days)} / {holidays} / {raw_days} / {raw_rows} |",
     f"| bars before the load | {len(before_series)} |",
     f"| rows the load inserts | {inserted} (days by status: {dict(status)}) |",
     f"| bars after (inside the transaction) / persisted right now | {len(after_series)} / {len(final_series)} |",
     f"| expected member sessions with a bar: before -> after | {ms['with_bar_before']} -> {ms['with_bar_after']} |",
     f"| expected member sessions still without a bar | {ms['missing_after']} |",
     f"| price continuity: largest |daily return| after / sessions over 25% | {report['continuity']['max_abs_daily_return_after']} / {report['continuity']['sessions_over_25pct']} |",
     f"| sessions eligible once verified: before -> after (newly eligible) | {eb} -> {ea} ({newly_ok}) |", "",
     "Why the eligible count moves (or not): the sessions where this instrument is a member that are still not eligible once verified, and what blocks them:", "",
     "| remaining blocker | sessions |", "|---|---|", *[f"| {k} | {v} |" for k, v in blockers.most_common()], "",
     "The membership intervals, identity tables and every other instrument's bars are untouched by this operation (verified by the caller's fingerprints)."]  # fmt: skip
(a.out_dir / f"{stem}.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
