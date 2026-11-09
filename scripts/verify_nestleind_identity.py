# ruff: noqa: E501  (a report script)
"""READ-ONLY regression on the REAL data of instrument 1589 (NESTLEIND): split its bars and corporate
actions at the ISIN change IN MEMORY into an old-ISIN and a new-ISIN instrument, read them back through
the issuer-scoped path, and prove the result equals today's single-instrument read, in every adjustment
mode. Nothing is written and instrument 1589 is not migrated.
usage: verify_nestleind_identity.py --db postgresql://... [--instrument 1589] [--change 2024-01-05]
       [--out docs/stage4/apply_proposals/nestleind_reader_check.md]"""

import argparse
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg

from algo.data.corporate_actions import records_for
from algo.data.issuer_series import IST, Link, chain, stitch
from algo.data.reader import BarReader, Loaded

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--instrument", type=int, default=1589)
ap.add_argument("--change", default="2024-01-05")
ap.add_argument(
    "--out", type=Path, default=Path("docs/stage4/apply_proposals/nestleind_reader_check.md")
)
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
change, NEW, OLD = date.fromisoformat(a.change), a.instrument, -1  # OLD is an in-memory stand-in id


def day(r):
    return r[0].astimezone(IST).date()


lines = ["# NESTLEIND reader check (read-only, in memory; instrument 1589 is NOT migrated)", ""]
ok = True
with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    rd = BarReader(c)
    rows = rd._raw(NEW)
    recs = records_for(c, NEW)
    pre, post = [r for r in rows if day(r) < change], [r for r in rows if day(r) >= change]
    apre, apost = [x for x in recs if x.ex_date < change], [x for x in recs if x.ex_date >= change]
    rel = [
        r[0]
        for r in c.execute(
            "SELECT effective_from FROM index_release_row WHERE instrument_id=%s AND component IS NOT NULL"
            " AND parser_version = (SELECT max(parser_version) FROM index_release_document)",
            (NEW,),
        ).fetchall()
    ]
    lines += [
        f"- bars: {len(rows)} total = {len(pre)} before {change} (old ISIN) + {len(post)} from {change} (new ISIN)",
        f"- corporate actions: {len(recs)} total = {len(apre)} before + {len(apost)} from the change",
        f"- release rows: {len(rel)} total, {sum(1 for d in rel if d is not None and d < change)} dated before the change, {sum(1 for d in rel if d is None)} undated",
        "",
    ]
    segs = chain([Link(OLD, NEW, change)], NEW)
    s_rows, owners, s_recs = stitch(segs, {OLD: pre, NEW: post}, {OLD: apre, NEW: apost})
    unique_actions = len({(x.ex_date, x.kind, x.status, x.num, x.den, x.amount) for x in recs})
    ok &= (
        len(s_rows) == len(rows)
        and owners.count(OLD) == len(pre)
        and owners.count(NEW) == len(post)
    )
    ok &= len(s_recs) == unique_actions
    lines.append(
        f"- stitched bars {len(s_rows)} (= {len(rows)}), owners old/new {owners.count(OLD)}/{owners.count(NEW)}; actions {len(s_recs)} (= {unique_actions} distinct)"
    )
    first, last = day(rows[0]), day(rows[-1])
    today = Loaded(rows, recs, rd.visible_after, False, [NEW] * len(rows))
    proposed = Loaded(s_rows, s_recs, rd.visible_after, False, owners)
    lines += [
        "",
        "| mode | bars | closes equal | factors equal | volumes equal | adjustment_version equal |",
        "|---|---|---|---|---|---|",
    ]
    for mode in ("none", "split", "total_return"):
        h1, h2 = today.history(first, last, adjust=mode), proposed.history(first, last, adjust=mode)
        eq = (
            [b.close for b in h1.bars] == [b.close for b in h2.bars],
            [b.factor for b in h1.bars] == [b.factor for b in h2.bars],
            [b.volume for b in h1.bars] == [b.volume for b in h2.bars],
            h1.adjustment_version == h2.adjustment_version,
        )
        ok &= all(eq) and len(h1.bars) == len(h2.bars)
        lines.append(f"| {mode} | {len(h1.bars)} | {eq[0]} | {eq[1]} | {eq[2]} | {eq[3]} |")
    # prefix invariance: the series up to the day before the change, as known that afternoon, is the
    # same whether or not anything from the change date onward exists
    eve = datetime.combine(change - timedelta(days=1), datetime.min.time(), UTC).replace(hour=14)
    end = change - timedelta(days=1)
    full = proposed.history(first, end, adjust="split", as_of=eve)
    cut = Loaded(pre, apre, rd.visible_after, False, [OLD] * len(pre))
    pref = cut.history(first, end, adjust="split", as_of=eve)
    pi = [b.close for b in full.bars] == [b.close for b in pref.bars] and [
        b.factor for b in full.bars
    ] == [b.factor for b in pref.bars]
    ok &= pi
    lines += ["", f"- prefix invariance (as of the afternoon before {change}): {pi}"]
lines += ["", f"**Result: {'PASS' if ok else 'FAIL'}**"]
a.out.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
raise SystemExit(0 if ok else 1)
