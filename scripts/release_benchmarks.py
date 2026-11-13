# ruff: noqa: E501
"""Benchmark Release 1.0: freeze the evidence (dataset hashes, validation records, audit output
hashes, calendar inputs, eligibility) into docs/benchmark-release-1.0/release.json, or --verify that
the database and files still match it. A later correction must create a NEW release, never rewrite
this one. The benchmark gate is not touched.
usage: release_benchmarks.py --db postgresql://... (--write | --verify) [--version 1.0]"""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import psycopg

from algo.data.benchmark import dataset_hash

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--ids", default="1,2,3,4")
ap.add_argument("--audit", type=Path, default=Path("docs/benchmark-audit"))
ap.add_argument("--version", default="1.0")
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--write", action="store_true")
g.add_argument("--verify", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
out = Path(f"docs/benchmark-release-{a.version}")
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
EXTRA = [Path("config/session_secondary_evidence.json"),
         Path("docs/session-evidence/legacy_bhavcopy_check.json"),
         Path("docs/recovery/bhavcopy_2022-08-08.json")]  # fmt: skip
FILES = ["benchmark_alignment_report.json", "session_reconciliation_report.json",
         "benchmark_unresolved_findings.json", "benchmark_eligibility.json",
         "benchmark_evidence_report.md", "audit_manifest.json"]  # fmt: skip


def gate_activation() -> str:
    cfg = Path("config/benchmark_gate.json")
    g = json.loads(cfg.read_text()) if cfg.exists() else {}
    return (
        f"ENABLED (decided {g.get('decided')} by {g.get('by')})"
        if g.get("enabled") is True
        else "NOT enabled; a separate decision"
    )


def current() -> dict:
    with psycopg.connect(a.db) as conn:
        bms = {}
        for i in (int(x) for x in a.ids.split(",")):
            name, sym, rtype = conn.execute(
                "SELECT name, index_symbol, return_type FROM benchmark WHERE benchmark_id=%s",
                (i,)).fetchone()  # fmt: skip
            v = conn.execute(
                "SELECT validation_id, passed, created_at, dataset_hash, report FROM"
                " benchmark_validation WHERE benchmark_id=%s ORDER BY validation_id DESC LIMIT 1",
                (i,)).fetchone()  # fmt: skip
            n = conn.execute("SELECT count(*) FROM benchmark_observation WHERE benchmark_id=%s",
                             (i,)).fetchone()  # fmt: skip
            bms[str(i)] = {
                "name": name, "index_symbol": sym, "return_type": rtype, "observations": n[0],
                "dataset_hash": dataset_hash(conn, i),
                "validation": {"validation_id": v[0], "passed": v[1], "created_at": v[2].isoformat(),
                               "dataset_hash": v[3], "report_version": v[4].get("report_version"),
                               "technical_validation_passed": v[4].get("technical_validation_passed"),
                               "owner_accepted_findings": v[4].get("owner_accepted_findings", [])},
            }  # fmt: skip
    elig = json.loads((a.audit / "benchmark_eligibility.json").read_text())
    unres = json.loads((a.audit / "benchmark_unresolved_findings.json").read_text())
    return {
        "release": a.version, "gate_activation": gate_activation(),
        "code_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                      check=True).stdout.strip(),
        "benchmarks": bms,
        "audit_file_sha256": {f: sha(a.audit / f) for f in FILES},
        "calendar_inputs": {"sessions_file_sha256": sha("config/exchange_sessions.json"),
                            "evidence_manifest_sha256": sha("docs/evidence-manifest.json"),
                            **{f"{p.name}_sha256": sha(p) for p in EXTRA if p.exists()}},
        "eligibility": {n: {"state": b["state"], "uses": {u: x["eligible"] for u, x in b["uses"].items()}}
                        for n, b in elig["benchmarks"].items()},
        "instrument_level_blocked_dates": elig["instrument_level_blocked_dates"],
        "unresolved_findings": [{"id": f["id"], "severity": f["severity"], "status": f["status"],
                                 "title": f["title"]} for f in unres["findings"]],
    }  # fmt: skip


if a.write:
    if (out / "release.json").exists():
        raise SystemExit(
            f"{out}/release.json exists: a release is never rewritten; use a new --version"
        )
    out.mkdir(parents=True)
    doc = current()
    (out / "release.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}/release.json (sha256 {sha(out / 'release.json')[:16]})")
else:
    frozen = json.loads((out / "release.json").read_text())
    now = current()
    bad = []
    for i, b in frozen["benchmarks"].items():
        n = now["benchmarks"][i]
        if n["dataset_hash"] != b["dataset_hash"] or n["observations"] != b["observations"]:
            bad.append(f"benchmark {i}: dataset changed since the release")
        if b["validation"]["dataset_hash"] != b["dataset_hash"]:
            bad.append(f"benchmark {i}: the released validation did not cover the released data")
    bad += [f"{f}: audit output changed" for f, h in frozen["audit_file_sha256"].items()
            if now["audit_file_sha256"][f] != h]  # fmt: skip
    bad += [f"{k}: calendar input changed" for k, h in frozen["calendar_inputs"].items()
            if now["calendar_inputs"][k] != h]  # fmt: skip
    if bad:
        raise SystemExit("RELEASE DRIFT:\n  " + "\n  ".join(bad))
    print(
        f"release {frozen['release']} verified: datasets, audit outputs and calendar inputs unchanged"
    )
