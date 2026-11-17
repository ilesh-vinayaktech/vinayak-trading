# ruff: noqa: E501
"""Run new strategies through the research pipeline, the way the first 19 went: a fixed-setting study of each definition (development 2016-2022, inner holdout 2023-2024),
its trials, the development verdict, and the inner holdout only if the verdict passed. The outer holdout stays the owner's separate step (research_holdout.py submit / the Holdout page).

usage: run_pipeline.py [STRATEGY_ID ...] [--version 1] [--owner USER_UUID] [--family 1] [--db URL] [--interval 20]
With no ids it takes every registered definition that has no study yet. Needs study_worker.py processes running (more workers, or ALGO_STUDY_SLOTS, run more at once).
Resumable: run it again and it carries on from what exists. Refuses a dirty src/ or config/ tree: a study registered from uncommitted code cannot be reproduced, so it could never be submitted."""

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from uuid import UUID

import psycopg

from algo.factory import study
from algo.research import study_jobs
from algo.research.code_identity import git_state
from algo.research.holdout_lock import HoldoutError
from algo.research.pipeline import next_step

ap = argparse.ArgumentParser()
ap.add_argument("strategies", nargs="*")
ap.add_argument("--version", type=int, default=1)
ap.add_argument("--owner", type=UUID, help="who registers them (default: the first ADMIN)")
ap.add_argument("--family", type=int, default=1)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--interval", type=float, default=20.0)
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")
commit, dirty = git_state()
if dirty:
    sys.exit(
        f"error: src/ or config/ differs from commit {commit[:8]}: commit first, or the studies cannot be reproduced and locked"
    )
conn = psycopg.connect(a.db, autocommit=True)
owner = (
    a.owner
    or conn.execute(
        "SELECT user_id FROM portal_user WHERE role='ADMIN' AND status='ACTIVE' ORDER BY created_at LIMIT 1"
    ).fetchone()[0]
)
now = lambda: datetime.now(UTC)  # noqa: E731
if a.strategies:
    todo = [(s, a.version) for s in a.strategies]
else:
    todo = [
        (s, v)
        for s, v in conn.execute(
            "SELECT strategy_id, version FROM strategy_definition ORDER BY strategy_id, version"
        ).fetchall()
        if not conn.execute(
            "SELECT 1 FROM experiment WHERE strategy_id='dsl' AND study->'spec'->'definition'->>'strategy_id'=%s AND (study->'spec'->'definition'->>'version')::int=%s",
            (s, v),
        ).fetchone()
    ]
studies: dict[int, str] = {}
for sid, ver in todo:
    spec = study.spec_for(
        conn,
        sid,
        ver,
        family_id=a.family,
        start=study.WINDOW[0],
        end=study.WINDOW[1],
        holdout_start=study.WINDOW[2],
        fixed=True,
    )
    try:
        eid = conn.execute(
            "SELECT experiment_id FROM experiment WHERE name=%s AND strategy_id='dsl'", (spec.name,)
        ).fetchone()
        eid = int(eid[0]) if eid else study.register(conn, owner, spec, now())
    except HoldoutError as e:
        sys.exit(f"error: research is locked: {e}")
    studies[eid] = sid
    print(f"study {eid}: {sid} v{ver}", flush=True)
if not studies:
    sys.exit("nothing to run: every definition already has a study (name ids to run specific ones)")
open_ = set(studies)
while open_:
    for eid in sorted(open_):
        runs = dict(
            conn.execute(
                "SELECT kind, status FROM (SELECT DISTINCT ON (kind) kind, status FROM study_run WHERE experiment_id=%s ORDER BY kind, run_id DESC) x",
                (eid,),
            ).fetchall()
        )
        rep = study_jobs.latest_report(conn, eid)
        kind, finished = next_step(runs, None if rep is None else bool(rep["passed"]))
        if kind:
            study_jobs.enqueue(conn, eid, owner, now(), kind)
            print(f"{now():%H:%M} {studies[eid]}: queued {kind}", flush=True)
        if finished:
            print(
                f"{now():%H:%M} {studies[eid]}: done ({'passed development' if rep and rep['passed'] else 'failed development'})",
                flush=True,
            )
            open_.discard(eid)
    if open_:
        time.sleep(a.interval)
print("PIPELINE DONE: see /research/pipeline", flush=True)
