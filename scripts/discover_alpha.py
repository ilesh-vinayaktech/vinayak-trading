# ruff: noqa: E501
"""Alpha discovery (plan.md phase 2): test every USABLE feature at the chosen horizons on one data freeze and record each as a hypothesis.

Every result is stored, failures included, and the multiple-testing correction counts every test ever run. Takes the research slot. The universe is the
freeze's instruments, which is NOT point-in-time Nifty 200 membership: the run says so in every record, and nothing it finds is evidence about the
Nifty 200 until membership is strict-eligible. Only development days are read (the guarded reader cannot return a holdout day).
usage: discover_alpha.py [--db URL] [--freeze UUID (default: the newest)] [--from YYYY-MM-01] [--horizons 1,5,20,60] [--min-names 20] [--dry-run]"""

import argparse
import os
import sys
from datetime import UTC, date, datetime
from uuid import UUID

import psycopg

from algo.alpha import registry, run
from algo.core.clock import SystemClock
from algo.jobs import progress
from algo.research import slot

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--freeze")
ap.add_argument("--from", dest="first", default="2020-10-01")
ap.add_argument("--horizons", default="1,5,20,60,120,250")
ap.add_argument("--min-names", type=int, default=20)
ap.add_argument(
    "--liquid-top",
    type=int,
    default=None,
    help="test only the N most traded names of each day (by the 20-day traded value known that day)",
)
ap.add_argument(
    "--through",
    help="stop at this day (e.g. 2019-12-31): the later years are not looked at, so they stay clean for validation",
)
ap.add_argument(
    "--segments",
    help="only the stocks a study would trade: AMFI market-cap segments, e.g. large,mid (point in time; before the first AMFI list, ranked by traded value)",
)
ap.add_argument("--dry-run", action="store_true", help="measure and print, record nothing")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
horizons = tuple(sorted({int(h) for h in a.horizons.split(",")}))
CONTEXT = {
    "universe": "the data freeze's instruments; NOT point-in-time Nifty 200 membership"
    if a.liquid_top is None
    else f"the {a.liquid_top} most traded names of each day (20-day traded value known that day), chosen point in time from the data freeze's instruments; NOT point-in-time Nifty 200 membership",
    "method": "rank IC, Newey-West, Benjamini-Hochberg false discovery rate over all tests ever run",
    "through": a.through,
    "segments": a.segments,
    "liquid_top": a.liquid_top,
}

with psycopg.connect(a.db, autocommit=True) as conn, slot.hold(conn, "alpha discovery", nice=10):
    fid = (
        a.freeze
        or (
            conn.execute(
                "SELECT freeze_id FROM data_freeze ORDER BY taken_at DESC LIMIT 1"
            ).fetchone()
            or [None]
        )[0]
    )
    if fid is None:
        sys.exit("error: no data freeze")
    first = date.fromisoformat(a.first)
    through = date.fromisoformat(a.through) if a.through else None
    members = None
    if a.segments:
        from algo.research import holdout_lock
        from algo.research.study import UniverseSpec
        from algo.research.study_universe import build as build_universe

        end = min(through or date.max, holdout_lock.require(conn).development_end)
        members, _ = build_universe(conn, UniverseSpec(segments=a.segments.split(",")), first, end)
    try:
        if a.dry_run:
            for e in run.measure(
                conn,
                UUID(str(fid)),
                first,
                horizons=horizons,
                min_names=a.min_names,
                liquid_top=a.liquid_top,
                through=through,
                members=members,
            ):
                print(
                    f"{e.feature}@{e.version} h={e.horizon}: days {e.days}, mean IC {e.mean_ic}, p {e.p_value}"
                )
            sys.exit(0)
        step_of = {"reading prices": 0, "loading features": 1, "testing": 2, "recording": 3}
        with (
            psycopg.connect(
                a.db, autocommit=True
            ) as pconn,  # its own connection: each progress update shows at once
            progress.Progress(
                pconn, SystemClock(), "alpha_discovery", "Alpha discovery", 4, uniform=False
            ) as prog,
        ):
            ids = run.run_discovery(
                conn,
                UUID(str(fid)),
                first,
                datetime.now(UTC),
                horizons=horizons,
                min_names=a.min_names,
                context=CONTEXT,
                liquid_top=a.liquid_top,
                through=through,
                members=members,
                report=lambda phase, msg: prog.step(phase, msg, done=step_of.get(phase)),
            )
            prog.finish(True, f"{len(ids)} hypotheses recorded")
    except run.DiscoveryError as e:
        sys.exit(f"refused: {e}")
    rows = conn.execute(
        "SELECT feature_name, feature_version, horizon_days, research_status, evidence->>'mean_ic', evidence->>'p_adjusted' FROM alpha_hypothesis WHERE hypothesis_id = ANY(%s) ORDER BY hypothesis_id",
        (ids,),
    ).fetchall()
    for name, version, h, status, ic, padj in rows:
        print(f"{name}@{version} h={h}: {status}  mean IC {ic}  adjusted p {padj}")
    print(f"{len(ids)} hypotheses recorded; {registry.tests_ever_run(conn)} tests ever run")
