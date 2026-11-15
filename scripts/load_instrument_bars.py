# ruff: noqa: E501
"""Load the daily bars of NAMED instruments from raw bhavcopy files already in the lake (never fetches). Dry run unless --apply: everything runs in a
transaction that is rolled back. Only the named instruments' bars are inserted (the same `backfill_instruments` the identity application uses); the
script checks that no other instrument's bars changed. Corporate actions are NOT touched: a stock whose actions are unresolved stays unusable in strict mode.
usage: load_instrument_bars.py --db URL --symbols GSPL PEL [--lake data/lake] [--apply] [--out FILE.md]"""

import argparse
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.lake import LocalLake
from algo.data.pipeline import backfill_instruments
from algo.data.providers.nse_bhavcopy import NseBhavcopy
from algo.data.sessions import calendar

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--symbols", nargs="+", required=True)
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--apply", action="store_true")
ap.add_argument("--out", type=Path)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
now = datetime.now(UTC)
lake = LocalLake(a.lake)
prov = NseBhavcopy(lambda url: b"", calendar(Path("config/exchange_sessions.json")))
all_days = [date.fromisoformat(p.name[3:]) for p in sorted((a.lake / "raw/nse/bhav").glob("dt=*"))]
lines = [
    f"# Bars for {', '.join(a.symbols)}: {'APPLIED' if a.apply else 'DRY RUN (rolled back; nothing written)'} ({now:%Y-%m-%d %H:%M} UTC)",
    "",
]
with psycopg.connect(a.db) as conn:
    others_before = conn.execute(
        "SELECT count(*), md5(string_agg(instrument_id::text || ts::text || source || close::text, ',' ORDER BY instrument_id, ts, source)) FROM bar_1d WHERE instrument_id <> ALL(%s)",
        ([0],),
    ).fetchone()
    ids: dict[str, int] = {}
    for sym in a.symbols:
        found = conn.execute(
            "SELECT DISTINCT i.instrument_id, al.valid_from, i.last_traded_on FROM instrument i JOIN instrument_alias al USING (instrument_id) WHERE al.source='nse' AND al.source_symbol=%s",
            (sym,),
        ).fetchall()
        if len(found) != 1:
            raise SystemExit(f"error: {sym} names {len(found)} instruments: name exactly one")
        ids[sym] = found[0][0]
    others_excl = conn.execute(
        "SELECT count(*), md5(string_agg(instrument_id::text || ts::text || source || close::text, ',' ORDER BY instrument_id, ts, source)) FROM bar_1d WHERE instrument_id <> ALL(%s)",
        (list(ids.values()),),
    ).fetchone()
    with conn.transaction(force_rollback=not a.apply):
        for sym, iid in ids.items():
            lo, hi = conn.execute(
                "SELECT (SELECT min(valid_from) FROM instrument_alias WHERE instrument_id=%s AND source='nse'), last_traded_on FROM instrument WHERE instrument_id=%s",
                (iid, iid),
            ).fetchone()
            days = [d for d in all_days if lo <= d <= hi]
            res = backfill_instruments(conn, lake, prov, "bhav", days, {iid}, now)
            by: dict[str, int] = {}
            for r in res:
                by[r.status] = by.get(r.status, 0) + (r.rows if r.status == "loaded" else 1)
            n, first, last = conn.execute(
                "SELECT count(*), min((ts AT TIME ZONE 'Asia/Kolkata')::date), max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d WHERE instrument_id=%s",
                (iid,),
            ).fetchone()
            lines += [
                f"## {sym} (instrument {iid}), lake days {days[0]}..{days[-1]} ({len(days)} files)",
                f"- bars now: {n} rows, {first}..{last}",
                f"- load status: {by}",
                "",
            ]
        after = conn.execute(
            "SELECT count(*), md5(string_agg(instrument_id::text || ts::text || source || close::text, ',' ORDER BY instrument_id, ts, source)) FROM bar_1d WHERE instrument_id <> ALL(%s)",
            (list(ids.values()),),
        ).fetchone()
        unchanged = after == others_excl
        lines += [
            f"Every other instrument's bars unchanged: **{'yes' if unchanged else 'NO'}** ({after[0]} rows).",
            "",
        ]
        if not unchanged:
            raise SystemExit("error: other instruments' bars changed: aborting (rolled back)")
print("\n".join(lines))
if a.out:
    a.out.write_text("\n".join(lines))
