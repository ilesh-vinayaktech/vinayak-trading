# ruff: noqa: E501  (a report script)
"""READ-ONLY: classify every trading session of the Nifty 200 research window (algo.data.membership_coverage).

Inputs: the committed membership deliverables (intervals, events, coverage.json for the independent-check period and the
verification status) and, from the database, the trading sessions and which member instruments have a bar each session.
Outputs: membership_sessions.csv (one row per session: the four classifications, the entities behind them and a SHA-256
of the member set, so the daily member set is reproducible) and MEMBERSHIP_COVERAGE.md. Nothing is written to the database.
usage: build_membership_coverage.py --db URL [--dir docs/stage4/membership]"""

import argparse
import csv
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path

import psycopg

from algo.data.membership_coverage import Event, MemberSpan, session_coverage

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--dir", type=Path, default=Path("docs/stage4/membership"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")

iso = date.fromisoformat
spans = [MemberSpan(r["entity"], iso(r["start"]), iso(r["end_exclusive"]) if r["end_exclusive"] else None)
         for r in csv.DictReader((a.dir / "membership_intervals.csv").open())]  # fmt: skip
events = [Event(r["entity"], iso(r["effective_from"]), iso(r["announcement_date"]))
          for r in csv.DictReader((a.dir / "membership_events.csv").open())]  # fmt: skip
cov_json = json.loads((a.dir / "membership_coverage.json").read_text())
lo, hi = (iso(x) for x in cov_json["window"])
checked_until = iso(
    cov_json["independent_checks_by_period"]["N100/N200/Midcap 100 monthly constituents"][1]
)
verified = not cov_json["verification_status"].startswith("PROVISIONAL")
ids = sorted({int(s.entity[2:]) for s in spans if s.entity.startswith("i:")})

with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    sessions = [r[0] for r in c.execute(
        "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date d FROM bar_1d WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s ORDER BY d", (lo, hi))]  # fmt: skip
    bars = {(i, d) for i, d in c.execute(
        "SELECT DISTINCT instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date FROM bar_1d WHERE instrument_id = ANY(%s) AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s", (ids, lo, hi))}  # fmt: skip

cov = session_coverage(
    sessions, spans, events, lambda i, d: (i, d) in bars, checked_until, verified
)
with (a.dir / "membership_sessions.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["day", "members", "members_sha256", "completeness", "knowledge", "independent_check", "verification",
                "eligible_once_verified", "strict_eligible", "untradable", "missing_bars", "retrospective"])  # fmt: skip
    for x in cov:
        w.writerow([x.day, len(x.members), x.members_hash, x.completeness, x.knowledge, x.independent_check, x.verification,
                    x.eligible_once_verified, x.strict_eligible, " ".join(x.untradable), " ".join(x.missing_bars), " ".join(x.retrospective)])  # fmt: skip

runs: list[list] = []  # contiguous runs of sessions that would be eligible once verified
prev_ok = False
for x in cov:
    if x.eligible_once_verified:
        if prev_ok:
            runs[-1][1], runs[-1][2] = x.day, runs[-1][2] + 1
        else:
            runs.append([x.day, x.day, 1])
    prev_ok = x.eligible_once_verified

n = len(cov)
axis = {
    k: Counter(getattr(x, k) for x in cov)
    for k in ("completeness", "knowledge", "independent_check", "verification")
}
why = Counter([*(f"member without an instrument: {e}" for x in cov for e in x.untradable),
               *(f"member without a bar: {e}" for x in cov for e in x.missing_bars),
               *(f"not yet published at the decision: {e}" for x in cov for e in x.retrospective)])  # fmt: skip
L = ["# Nifty 200 membership coverage per trading session (read-only)", "",
     f"Window {lo}..{hi}: {n} trading sessions with bars ({sessions[0]}..{sessions[-1]}). Independent official N200 / Midcap 100 monthly snapshots end {checked_until}.",
     f"Verification status: {cov_json['verification_status']}", "",
     "## Two separate questions", "", "| Axis | What it answers | Sessions |", "|---|---|---|",
     f"| Reconstruction completeness | every member a tradable instrument with a bar that session | COMPLETE {axis['completeness']['COMPLETE']}, INCOMPLETE {axis['completeness']['INCOMPLETE']} |",
     f"| Point-in-time knowledge | every member's state already published by that day's decision | CONTEMPORANEOUS {axis['knowledge']['CONTEMPORANEOUS']}, RETROSPECTIVE {axis['knowledge']['RETROSPECTIVE']} |",
     f"| Independent check | an official snapshot series covers the session (quality; does not block) | CHECKPOINTED {axis['independent_check']['CHECKPOINTED']}, RELEASE_ONLY {axis['independent_check']['RELEASE_ONLY']} |",
     f"| Verification | person-verified | {dict(axis['verification'])} |", "",
     f"**Strict-eligible sessions: {sum(x.strict_eligible for x in cov)} of {n}.** Eligible once verified (complete and contemporaneous): {sum(x.eligible_once_verified for x in cov)} of {n}.", "",
     "## Why sessions are not eligible once verified (entity: sessions affected)", "", "| reason | sessions |", "|---|---|",
     *[f"| {k} | {v} |" for k, v in why.most_common()], "",
     "## Contiguous runs that would be eligible once verified", "", "| from | to | sessions |", "|---|---|---|",
     *[f"| {s} | {e} | {k} |" for s, e, k in runs], "",
     "Per-session detail and the SHA-256 of each day's member set: `membership_sessions.csv`. A release dated d counts as known at d's close."]  # fmt: skip
(a.dir / "MEMBERSHIP_COVERAGE.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
