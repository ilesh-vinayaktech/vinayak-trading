# ruff: noqa: E501
"""Count logical constituents (distinct constituent keys, at their ACTUAL effective dates) for every NSE session of the reconstructed Nifty 200
and explain every session that is not 200. A session is explained when (count - additional entities) == 200, where the additional entities are only
those NSE's own releases say are added on top of the 200: the 101st Nifty 100 member Tata Motors DVR, and entities spun off in a demerger ("included
at zero price without divisor adjustment" while the parent stays) from their dummy symbol until NSE excludes them. Also checks that a placeholder
never overlaps its own real listing. Exit 1 if anything is unexplained. usage: check_membership_counts.py --db postgresql://..."""

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dir", type=Path, default=Path("docs/stage4/membership-2018"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")

# additional entities -> (NSE release that says so, the placeholder it replaces or None). The release text is quoted in membership_counts.md.
ADDITIONAL = {
    "TATAMTRDVR": ("explicit Nifty 100 / Nifty 200 sections; month-end lists", None),
    "JIOFIN": ("pr_ind_prs17072023", None),
    "ITCHOTELS": ("pr_ind_prs30122024", "DUMMYITC"), "ENRIN": ("pr_ind_prs02042025", "DUMMYSIEMS"),
    "ABLBL": ("pr_ind_prs19052025", "DUMMYABFRL"), "TMCV": ("pr_ind_prs07102025", "DUMMYTATAM"),
    "KWIL": ("pr_ind_prs28112025", "DUMMYHDLVR"), "VAML": ("pr_ind_prs23042026", "DUMMYVEDL1"),
    "VEDPOWER": ("pr_ind_prs23042026", "DUMMYVEDL2"), "VISL": ("pr_ind_prs23042026", "DUMMYVEDL3"),
    "VOGL": ("pr_ind_prs23042026", "DUMMYVEDL4"),
}  # fmt: skip

iv = list(csv.DictReader((a.dir / "membership_intervals.csv").open()))
for r in iv:
    r["s"] = date.fromisoformat(r["start"])
    r["e"] = date.fromisoformat(r["end_exclusive"]) if r["end_exclusive"] else date.max


FIRST: dict[
    str, date
] = {}  # symbol -> start of its first interval: the demerger stint. A later re-admission in a review is an ordinary member.
for r in sorted(iv, key=lambda x: x["s"]):
    FIRST.setdefault(r["symbol"], r["s"])


def additional(r: dict) -> bool:
    sym = r["symbol"]
    if sym.startswith("DUMMY") or sym == "TATAMTRDVR":
        return True  # the DVR is a 101st member for every one of its stints
    if (
        sym == "JIOFIN"
    ):  # the dummy entity (2023-07-20) and then the real listing, until NSE excluded it on 2023-09-07; an ordinary member again from 2024-03-28
        return r["e"] <= date(2023, 9, 8)
    return sym in ADDITIONAL and r["s"] == FIRST[sym]


bad = []
for r in iv:  # a placeholder hands over to its listing on one day: never both
    for sym, (_, ph) in ADDITIONAL.items():
        if ph and r["symbol"] == ph:
            real = [x for x in iv if x["symbol"] == sym]
            if not real or min(x["s"] for x in real) < r["e"]:
                bad.append(f"{ph} overlaps {sym}")

with psycopg.connect(a.db) as c:
    days = [
        d
        for (d,) in c.execute(
            "SELECT DISTINCT ts::date FROM bar_1d b JOIN instrument i USING (instrument_id) WHERE i.symbol='RELIANCE' AND ts::date BETWEEN '2018-04-02' AND '2026-11-06' ORDER BY 1"
        )
    ]
rows, unexplained = [], []
for d in days:
    m = [r for r in iv if r["s"] <= d < r["e"]]
    extra = [r["symbol"] for r in m if additional(r)]
    rows.append((d, len(m), len(extra), len(m) - len(extra), ";".join(sorted(extra))))
    if len(m) - len(extra) != 200:
        unexplained.append(d)
with (a.dir / "membership_session_counts.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["session", "logical_constituents", "additional", "base", "additional_entities"])
    w.writerows(rows)
over = [r for r in rows if r[1] != 200]
print(
    f"sessions {len(rows)}; not 200: {len(over)}; unexplained: {len(unexplained)}; placeholder overlaps: {len(bad)}"
)
for msg in bad:
    print("OVERLAP", msg)
if unexplained:
    print("UNEXPLAINED", unexplained[:10])
sys.exit(1 if bad or unexplained else 0)
