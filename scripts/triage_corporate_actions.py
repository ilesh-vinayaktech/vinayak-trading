# ruff: noqa: E501  (a report script)
"""READ-ONLY triage of the non-dividend corporate actions still in review (the readiness check C1).

Ranks them by whether they can affect the Nifty 200 research universe and window, so review effort goes where
a wrong adjustment would change signals or returns. Nothing is written to the database.

Tiers (membership from docs/stage4/membership/membership_intervals.csv; window starts at its first day):
  A  ex-date in the research window AND the instrument was a Nifty 200 member that day (held / signalled directly)
  B  ex-date in the research window, member at some other time in the window (distorts its adjusted history)
  C  ex-date in the warm-up (bars start .. window start), member at some time in the window (distorts early lookbacks)
  D  everything else (never a member in the window, or outside the loaded bars): lowest priority, not zero (strict mode needs none pending)
Evidence shown per action: kind, subject, and the observed raw close-to-close move across the ex-date against the
instrument's typical daily move (a discontinuity that an adjustment must explain). Reports facts; resolves nothing.
usage: triage_corporate_actions.py --db URL [--intervals docs/stage4/membership/membership_intervals.csv]
       [--out-dir docs/stage4/corporate_actions]"""

import argparse
import csv
import os
from datetime import date, timedelta
from pathlib import Path
from statistics import median

import psycopg

from algo.data.review import evidence_class

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--intervals", type=Path, default=Path("docs/stage4/membership/membership_intervals.csv")
)
ap.add_argument("--out-dir", type=Path, default=Path("docs/stage4/corporate_actions"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")

spans: dict[int, list[tuple[date, date | None]]] = {}
for r in csv.DictReader(a.intervals.open()):
    if r["tradable"] == "True":
        spans.setdefault(int(r["instrument_id"]), []).append(
            (
                date.fromisoformat(r["start"]),
                date.fromisoformat(r["end_exclusive"]) if r["end_exclusive"] else None,
            )
        )
WINDOW_START = min(s for v in spans.values() for s, _ in v)


def member_on(iid: int, d: date) -> bool:
    return any(s <= d and (e is None or d < e) for s, e in spans.get(iid, []))


with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    bars_first, bars_last = c.execute(
        "SELECT min((ts AT TIME ZONE 'Asia/Kolkata')::date), max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d"
    ).fetchone()  # type: ignore[misc]
    actions = c.execute(
        "SELECT a.id, a.instrument_id, i.symbol, a.ex_date, a.kind, a.subject,"
        " (SELECT r.status FROM action_resolution r WHERE r.instrument_id=a.instrument_id AND r.ex_date=a.ex_date AND r.kind=a.kind ORDER BY r.id DESC LIMIT 1),"
        " (SELECT r.method FROM action_resolution r WHERE r.instrument_id=a.instrument_id AND r.ex_date=a.ex_date AND r.kind=a.kind ORDER BY r.id DESC LIMIT 1)"
        " FROM corporate_action a JOIN instrument i USING (instrument_id) WHERE a.status='review' AND a.kind <> 'dividend' ORDER BY a.ex_date, i.symbol"
    ).fetchall()
    out = []
    for aid, iid, sym, ex, kind, subject, st, method in actions:
        res = evidence_class(st, method)
        closes = c.execute(
            "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date, close FROM bar_1d WHERE instrument_id=%s"
            " AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s ORDER BY ts",
            (iid, ex - timedelta(days=400), ex + timedelta(days=10)),
        ).fetchall()
        px = dict(closes)
        before = [d for d, _ in closes if d < ex]
        after = [d for d, _ in closes if d >= ex]
        jump = z = None
        if before and after and after[0] <= ex + timedelta(days=7):
            jump = float(px[after[0]] / px[before[-1]] - 1)
            rets = [
                abs(float(px[y] / px[x] - 1))
                for x, y in zip(before[-251:], before[-250:], strict=False)
                if px[x]
            ]
            typ = median(rets) if rets else None
            z = abs(jump) / typ if typ else None
        window = WINDOW_START <= ex <= bars_last
        warm = bars_first <= ex < WINDOW_START
        ever = bool(spans.get(iid))
        tier = (
            "A"
            if window and member_on(iid, ex)
            else "B"
            if window and ever
            else "C"
            if warm and ever
            else "D"
        )
        out.append((tier, aid, iid, sym, ex, kind, subject, jump, z, res, ever))

order = {"A": 0, "B": 1, "C": 2, "D": 3}
out.sort(key=lambda r: (order[r[0]], -(r[8] or 0), r[4]))
a.out_dir.mkdir(parents=True, exist_ok=True)
with (a.out_dir / "triage.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(
        [
            "tier",
            "action_id",
            "instrument_id",
            "symbol",
            "ex_date",
            "kind",
            "subject",
            "raw_move_across_ex",
            "move_vs_typical_daily",
            "evidence_class",
            "member_in_window",
        ]
    )
    for t, aid, iid, sym, ex, kind, subj, jump, z, res, ever in out:
        w.writerow(
            [
                t,
                aid,
                iid,
                sym,
                ex,
                kind,
                subj,
                f"{jump:.4f}" if jump is not None else "",
                f"{z:.1f}" if z is not None else "",
                res or "",
                ever,
            ]
        )
by = {t: [r for r in out if r[0] == t] for t in "ABCD"}
meaning = {
    "A": "ex-date in window, member that day",
    "B": "ex-date in window, member at another time",
    "C": "warm-up ex-date, member in window",
    "D": "never a member in window / outside bars",
}
lines = [
    "# Corporate actions in review: triage (read-only)", "",
    f"Research window {WINDOW_START}..{bars_last} (membership intervals); bars start {bars_first}. {len(out)} non-dividend actions in review.", "",
    "| Tier | Meaning | Count | buyback / rights / arrangement+demerger / other |", "|---|---|---|---|",
]  # fmt: skip
for t in "ABCD":
    rs = by[t]

    def k(*names: str, rs: list = rs) -> int:
        return sum(1 for r in rs if r[5] in names)

    lines.append(
        f"| {t} | {meaning[t]} | {len(rs)} | {k('buy')} / {k('rights')} / {k('arrangement', 'arangement', 'demerger', 'sch of')} / {k('other')} |"
    )
lines += [
    "",
    "Raw move = unadjusted close-to-close across the ex-date; x typical = that move over the instrument's median absolute daily move (prior year).",
    "",
]
for t in "ABC":
    lines += [
        f"## Tier {t}: {meaning[t]} ({len(by[t])})",
        "",
        "| id | symbol | ex-date | kind | raw move | x typical | evidence class | subject |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r[1]} | {r[3]} | {r[4]} | {r[5]} | {f'{r[7]:+.1%}' if r[7] is not None else 'n/a'} | {f'{r[8]:.1f}' if r[8] is not None else 'n/a'} | {r[9] or 'none'} | {r[6][:90]} |"
        for r in by[t]
    ]
    lines.append("")
lines += [f"Tier D ({len(by['D'])}) is in `triage.csv` only."]
(a.out_dir / "TRIAGE.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines[:12]))
