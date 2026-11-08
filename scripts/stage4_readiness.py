# ruff: noqa: E501  (report prose; this is a script, not library code)
"""Stage 4 step 2: is a STRICT-mode run of the first strategy possible on the data we hold today?

Read-only. Every check states what it measured; nothing is inferred beyond that. A FAIL here is a
finding to fix upstream, never something to work around inside the strategy.
usage: stage4_readiness.py --db postgresql://... [--out docs/stage4/readiness.json]"""

import argparse
import json
import os
from pathlib import Path

import psycopg

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--out", type=Path, default=Path("docs/stage4/readiness.json"))
a = ap.parse_args()

checks: list[dict[str, object]] = []


def check(cid: str, requirement: str, status: str, evidence: str) -> None:
    checks.append({"id": cid, "requirement": requirement, "status": status, "evidence": evidence})


with psycopg.connect(a.db, options="-c default_transaction_read_only=on") as c:
    first, last, n_days = c.execute("SELECT min(ts)::date, max(ts)::date, count(DISTINCT ts::date) FROM bar_1d").fetchone()  # type: ignore[misc]
    years = (last - first).days / 365.25
    check("D1", "Daily bars cover enough history for warm-up, walk-forward and a 20-30% untouched holdout",
          "PASS" if years >= 7 else "FAIL",
          f"bar_1d {first}..{last}: {n_days} sessions, {years:.1f} years. The 1999-2019 bhavcopy archive is stored but deliberately NOT loaded as bars.")

    events = c.execute("SELECT count(*) FROM index_membership_event").fetchone()[0]  # type: ignore[index]
    cov = c.execute("SELECT count(*) FROM index_membership_coverage").fetchone()[0]  # type: ignore[index]
    snap = c.execute("SELECT index_id, as_of, count(*) FROM index_snapshot WHERE index_id='NIFTY200' GROUP BY 1,2 ORDER BY 2").fetchall()
    check("U1", "Point-in-time Nifty 200 membership with verified coverage for the whole research window (members_on never guesses)",
          "PASS" if events > 0 and cov > 0 else "FAIL",
          f"index_membership_event={events}, verified coverage declarations={cov}. Only current snapshots exist: {[(str(s[1]), s[2]) for s in snap]}. Using today's 200 for past dates is survivorship bias and is not allowed in strict mode.")

    rows = c.execute("SELECT mapping_status, count(*) FROM index_release_row GROUP BY 1 ORDER BY 1").fetchall()
    unmapped = sum(n for s, n in rows if s != "MAPPED")
    manual = dict(rows).get("UNMAPPED_SYMBOL", 0)
    delisted = c.execute("SELECT count(*) FROM instrument WHERE status <> 'active'").fetchone()[0]  # type: ignore[index]
    check("U2", "Every removed/added constituent maps to a permanent instrument with prices (delisted names included)",
          "FAIL" if unmapped else "PASS",
          f"index_release_row mapping: {dict(rows)}; {manual} rows reference symbols with no instrument (e.g. delisted/merged names). Instrument master holds {delisted} non-active instruments (inferred, not from a delisting source).")

    review = c.execute("SELECT kind, count(*) FROM corporate_action WHERE status <> 'ok' GROUP BY 1 ORDER BY 2 DESC").fetchall()
    price_moving = sum(n for k, n in review if k != "dividend")
    check("C1", "Strict mode: every price-affecting corporate action verified (none pending review)",
          "FAIL" if price_moving else "PASS",
          f"{price_moving} non-dividend actions still in review ({dict((k, n) for k, n in review if k != 'dividend')}); a further {dict(review).get('dividend', 0)} dividends in review matter only to the total-return basis.")

sch = [s for f in sorted(Path("config/cost_schedules").glob("*.json")) for s in json.loads(f.read_text())["schedules"]]
verified = [s for s in sch if s["status"] == "verified"]
check("K1", "Versioned, non-placeholder, VERIFIED cost schedule covering the whole research window",
      "PASS" if verified else "FAIL",
      "schedules: " + "; ".join(f"{s['id']} [{s['status']}] {s['valid_from']}..{s['valid_until']}" for s in sch) + ". None is verified; the backfill is opt-in and cannot support promotion.")

th = json.loads(Path("config/validation_thresholds.json").read_text())
check("V1", "Validation thresholds confirmed by the owner BEFORE the first validation", "FAIL" if th["status"] != "confirmed" else "PASS",
      f"config/validation_thresholds.json status={th['status']}. A pass against provisional thresholds does not lift the promotion blocker.")

rel = json.loads(Path("docs/benchmark-release-1.1/release.json").read_text())["eligibility"]["B1_NIFTY200_GROSS_TRI"]
check("B1", "Benchmark (Nifty 200 Gross TRI) available for daily research comparison",
      "PASS" if rel["uses"]["DAILY_RESEARCH"] else "FAIL",
      f"Release 1.1 state={rel['state']}, uses={rel['uses']} (gate use is blocked by design; daily research use is allowed).")

check("R1", "Hypothesis, parameter ranges and holdout registered before any run", "FAIL",
      "Nothing is registered yet. The draft in docs/stage4/preregistration-draft.md awaits owner confirmation; registering increments the trial counter and fixes the holdout.")

blocking = [x["id"] for x in checks if x["status"] != "PASS"]
report = {"audit": "stage4_readiness", "mode": "strict", "checks": checks, "strict_run_possible": not blocking, "blocking": blocking}
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
for x in checks:
    print(f"{x['status']:5} {x['id']}  {x['requirement']}")
print("strict run possible:", not blocking, "| blocking:", blocking)
