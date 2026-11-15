# ruff: noqa: E501  (report prose; this is a script, not library code)
"""Stage 4 step 2: is a STRICT-mode run of the first strategy possible on the data we hold today?

Read-only. Every check states what it measured; nothing is inferred beyond that. A FAIL here is a
finding to fix upstream, never something to work around inside the strategy.
usage: stage4_readiness.py --db postgresql://... [--out docs/stage4/readiness.json]"""

import argparse
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path

import psycopg

from algo.data.membership_audit import audit
from algo.data.review import evidence_class

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument(
    "--from",
    dest="window_from",
    default="2020-10-01",
    help="first research-window session (bars from 2019-10 plus a year of warm-up)",
)
ap.add_argument("--out", type=Path, default=Path("docs/stage4/readiness.json"))
a = ap.parse_args()
a.window_from = date.fromisoformat(a.window_from)
INDEX = "NIFTY200"

checks: list[dict[str, object]] = []


def check(cid: str, requirement: str, status: str, evidence: str) -> None:
    checks.append({"id": cid, "requirement": requirement, "status": status, "evidence": evidence})


with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    first, last, n_days = c.execute(
        "SELECT min(ts)::date, max(ts)::date, count(DISTINCT ts::date) FROM bar_1d"
    ).fetchone()  # type: ignore[misc]
    years = (last - first).days / 365.25
    check(
        "D1",
        "Daily bars cover enough history for warm-up, walk-forward and a 20-30% untouched holdout",
        "PASS" if years >= 7 else "FAIL",
        f"bar_1d {first}..{last}: {n_days} sessions, {years:.1f} years. The 1999-2019 bhavcopy archive is stored but deliberately NOT loaded as bars.",
    )

    # Membership, read from the STORED events (revision 4, verified in the database), over the research window: sessions of one liquid stock's bars.
    cov = c.execute(
        "SELECT max(covered_until) FROM index_membership_coverage WHERE index_id=%s AND verified_status='VERIFIED'",
        (INDEX,),
    ).fetchone()[0]  # type: ignore[index]
    sessions = [
        d for (d,) in c.execute(
            "SELECT DISTINCT ts::date FROM bar_1d b JOIN instrument i USING (instrument_id) WHERE i.symbol='RELIANCE' AND ts::date BETWEEN %s AND %s ORDER BY 1",
            (a.window_from, cov or a.window_from),
        )
    ]  # fmt: skip
    m = audit(c, INDEX, sessions)
    window = f"{sessions[0]}..{sessions[-1]}" if sessions else "none"

    def spans(d: dict) -> str:
        return (
            "; ".join(
                f"{k} {lo}..{hi} ({n} sessions)"
                for k, (lo, hi, n) in sorted(d.items(), key=lambda x: -x[1][2])
            )
            or "none"
        )

    syms = dict(
        c.execute(
            "SELECT instrument_id, symbol FROM instrument WHERE instrument_id = ANY(%s)",
            (list(m.missing_bars),),
        ).fetchall()
    )
    check(
        "U1",
        "Membership completeness: every Nifty 200 member of every research-window session is a tradable instrument (zero-price index placeholders, accepted by the owner as D4, are reported but not counted)",
        "PASS" if sessions and not m.untradable and m.unverified == 0 else "FAIL",
        f"{m.sessions} sessions {window} from the stored membership events. Members without an instrument that are not placeholders: {spans(m.untradable)}. By-design zero-price placeholders (members, not investable): {spans(m.by_design)}. Sessions with no verified answer: {m.unverified}.",
    )
    check(
        "U1b",
        "Membership evidence quality: events and coverage VERIFIED in the database, read point-in-time by announcement date (no lookahead). Handover days whose only evidence is a later release are a disclosed, owner-accepted limit (D5)",
        "PASS" if sessions and m.unverified == 0 else "FAIL",
        f"{m.unverified} of {m.sessions} sessions without VERIFIED coverage/events; {m.retrospective} sessions where the actual members differ from the members knowable by that day (a later release is the only evidence of a listing handover; accepted by the owner as D5 on 2026-11-15: a strict point-in-time query uses the announcement date and never sees them early, so on those days it understates the members, it does not leak).",
    )
    check(
        "U2",
        "Every research-window Nifty 200 member is a permanent instrument with a daily bar on its member sessions",
        "FAIL" if m.untradable or m.missing_bars else "PASS",
        f"members without an instrument: {spans(m.untradable)}. Members without a bar: {spans({syms.get(k, k): v for k, v in m.missing_bars.items()})}.",
    )

    review = c.execute(
        "SELECT kind, count(*) FROM corporate_action WHERE status <> 'ok' GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    price_moving = sum(n for k, n in review if k != "dividend")
    classes = Counter(
        evidence_class(st, m)
        for st, m in c.execute(
            "SELECT r.status, r.method FROM corporate_action a LEFT JOIN LATERAL (SELECT status, method FROM action_resolution x"
            " WHERE x.instrument_id=a.instrument_id AND x.ex_date=a.ex_date AND x.kind=a.kind ORDER BY x.id DESC LIMIT 1) r ON true"
            " WHERE a.status <> 'ok' AND a.kind <> 'dividend'"
        ).fetchall()
    )
    check(
        "C1",
        "Strict mode: every price-affecting corporate action verified (none pending review)",
        "FAIL" if price_moving else "PASS",
        f"{price_moving} non-dividend actions still in review ({dict((k, n) for k, n in review if k != 'dividend')}); by evidence of their latest resolution: {dict(sorted(classes.items()))}. A further {dict(review).get('dividend', 0)} dividends in review matter only to the total-return basis.",
    )

sch = [
    s
    for f in sorted(Path("config/cost_schedules").glob("*.json"))
    for s in json.loads(f.read_text())["schedules"]
]
verified = [s for s in sch if s["status"] == "verified"]
check(
    "K1",
    "Versioned, non-placeholder, VERIFIED cost schedule covering the whole research window",
    "PASS" if verified else "FAIL",
    "schedules: "
    + "; ".join(f"{s['id']} [{s['status']}] {s['valid_from']}..{s['valid_until']}" for s in sch)
    + ". None is verified; the backfill is opt-in and cannot support promotion.",
)

th = json.loads(Path("config/validation_thresholds.json").read_text())
check(
    "V1",
    "Validation thresholds confirmed by the owner BEFORE the first validation",
    "FAIL" if th["status"] != "confirmed" else "PASS",
    f"config/validation_thresholds.json status={th['status']}. A pass against provisional thresholds does not lift the promotion blocker.",
)

rel = json.loads(Path("docs/benchmark-release-1.1/release.json").read_text())["eligibility"][
    "B1_NIFTY200_GROSS_TRI"
]
check(
    "B1",
    "Benchmark (Nifty 200 Gross TRI) available for daily research comparison",
    "PASS" if rel["uses"]["DAILY_RESEARCH"] else "FAIL",
    f"Release 1.1 state={rel['state']}, uses={rel['uses']} (gate use is blocked by design; daily research use is allowed).",
)

check(
    "R1",
    "Hypothesis, parameter ranges and holdout registered before any run",
    "FAIL",
    "Nothing is registered yet. The draft in docs/stage4/preregistration-draft.md awaits owner confirmation; registering increments the trial counter and fixes the holdout.",
)

blocking = [x["id"] for x in checks if x["status"] != "PASS"]
report = {
    "audit": "stage4_readiness",
    "mode": "strict",
    "checks": checks,
    "strict_run_possible": not blocking,
    "blocking": blocking,
}
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
for x in checks:
    print(f"{x['status']:5} {x['id']}  {x['requirement']}")
print("strict run possible:", not blocking, "| blocking:", blocking)
