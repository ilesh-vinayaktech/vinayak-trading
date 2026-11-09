# ruff: noqa: E501  (a report script)
"""READ-ONLY: compare an issuer's series today with the series from a pre-migration BASELINE database
(a restored backup), in every adjustment mode. The baseline reads the instrument as it was (one
instrument holding everything); today's database is read through the issuer-scoped path. They must be
identical: same bars, closes, factors, volumes and adjustment version. Also reports the instrument-scoped
reads, which must now be separate.
usage: verify_issuer_baseline.py --baseline-db URL --db URL --old-instrument ID [--instrument 1589]
       [--out docs/stage4/apply_proposals/nestleind_post_apply_baseline_check.md]"""

import argparse
import os
from datetime import date
from pathlib import Path

import psycopg

from algo.data.reader import BarReader

ap = argparse.ArgumentParser()
ap.add_argument("--baseline-db", required=True)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--instrument", type=int, default=1589)
ap.add_argument("--old-instrument", type=int, required=True)
ap.add_argument(
    "--out",
    type=Path,
    default=Path("docs/stage4/apply_proposals/nestleind_post_apply_baseline_check.md"),
)
a = ap.parse_args()
first, last = date(1900, 1, 1), date(2100, 1, 1)
RO = "-c default_transaction_read_only=on"

ok = True
lines = ["# NESTLEIND post-apply check against the pre-migration baseline (read-only)", ""]
with psycopg.connect(a.baseline_db, options=RO) as base, psycopg.connect(a.db, options=RO) as cur:
    rb, rc = BarReader(base), BarReader(cur)
    lines += [
        "| mode | bars (baseline / now) | closes | factors | volumes | adjustment_version | owners |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode in ("none", "split", "total_return"):
        hb = rb.history(a.instrument, first, last, adjust=mode)
        for label, ident in (
            ("issuer via new", a.instrument),
            ("issuer via old", a.old_instrument),
        ):
            hc = rc.issuer_history(ident, first, last, adjust=mode)
            eq = (
                len(hb.bars) == len(hc.bars),
                [(b.ts, b.close) for b in hb.bars] == [(b.ts, b.close) for b in hc.bars],
                [b.factor for b in hb.bars] == [b.factor for b in hc.bars],
                [b.volume for b in hb.bars] == [b.volume for b in hc.bars],
                hb.adjustment_version == hc.adjustment_version,
            )
            owners = sorted({b.owner for b in hc.bars})
            ok &= all(eq)
            lines.append(
                f"| {mode} ({label}) | {len(hb.bars)} / {len(hc.bars)} | {eq[1]} | {eq[2]} | {eq[3]} | {eq[4]} | {owners} |"
            )
    new_own = rc.history(a.instrument, first, last)
    old_own = rc.history(a.old_instrument, first, last)
    sep = (
        len(new_own.bars) == 704
        and len(old_own.bars) == 107
        and {b.owner for b in new_own.bars} == {a.instrument}
    )
    ok &= sep
    lines += [
        "",
        f"- instrument-scoped reads are separate: new {len(new_own.bars)} bars, old {len(old_own.bars)} bars (expected 704 / 107): {sep}",
    ]
lines += ["", f"**Result: {'PASS' if ok else 'FAIL'}**"]
a.out.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
raise SystemExit(0 if ok else 1)
