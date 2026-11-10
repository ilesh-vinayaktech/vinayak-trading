# ruff: noqa: E501  (a report script)
"""Apply the reviewed GSPL / PEL historical-instrument applications. DRY RUN BY DEFAULT: everything runs in one
transaction that is rolled back unless --apply, and the report lists exactly which persisted records changed.

Stage 1 (always): instrument + alias + relationship per application, then re-map the press-release rows and the monthly
constituents that carry these symbols (the rule used when they were first stored, now that the alias exists).
Stage 2 (--with-bars): load the new instruments' daily bars from raw files already in the lake. NOT recommended before the
instruments' corporate actions are loaded (see the review package): bars without their actions look clean but are unadjusted.

The report proves, with row-level fingerprints taken before and after, that ONLY the intended records changed and that the
unrelated look-alikes (GNRL, the successors GUJENERGY / PIRAMALFIN) are byte-identical.
usage: apply_identity_application.py --db URL [--config config/identity_applications/gspl_pel.json] [--lake data/lake]
       [--with-bars] [--apply] [--out-dir docs/stage4/identity]"""

import argparse
import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from algo.data.identity_application import apply_historical_instrument
from algo.data.index_monthly import remap_monthly
from algo.data.index_releases import remap
from algo.data.lake import LocalLake
from algo.data.pipeline import backfill_instruments
from algo.data.providers.nse_bhavcopy import NseBhavcopy
from algo.data.sessions import calendar

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--config", type=Path, default=Path("config/identity_applications/gspl_pel.json"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--with-bars", action="store_true")
ap.add_argument("--apply", action="store_true")
ap.add_argument("--out-dir", type=Path, default=Path("docs/stage4/identity"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
cfg = json.loads(a.config.read_text())
now = datetime.now(UTC)
mode = ("applied" if a.apply else "dry_run") + ("_with_bars" if a.with_bars else "_identity_only")
SYMS = [x["instrument"]["symbol"] for x in cfg["applications"]]
LOOKALIKES = ["GNRL", *cfg["targets_expected"]]  # must be byte-identical before and after

FP = {
    "instrument": "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM instrument x WHERE x.symbol <> ALL(%(new)s)",
    "instrument_alias": "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM instrument_alias x WHERE x.source_symbol <> ALL(%(new)s)",
    "corporate_action_relationship": "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM corporate_action_relationship x WHERE x.target_symbol <> ALL(%(tgt)s)",
    "security_conversion": "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM security_conversion x",
    "corporate_action": "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM corporate_action x",
    "action_resolution": "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM action_resolution x",
    "bar_1d (other instruments)": "SELECT count(*), md5(sum(hashtext(x::text))::text) FROM bar_1d x WHERE x.instrument_id NOT IN (SELECT instrument_id FROM instrument WHERE symbol = ANY(%(new)s))",
    "index_release_row (other symbols)": "SELECT count(*), md5(sum(hashtext(x::text))::text) FROM index_release_row x WHERE x.symbol <> ALL(%(new)s)",
    "index_monthly_constituent (other symbols)": "SELECT count(*), md5(sum(hashtext(x::text))::text) FROM index_monthly_constituent x WHERE x.symbol <> ALL(%(new)s)",
    "index_snapshot": "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM index_snapshot x",
    "review_decision": "SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM review_decision x",
    "look-alikes GNRL / GUJENERGY / PIRAMALFIN (instrument + alias + bars)": "SELECT count(*), md5(sum(hashtext(x))::text) FROM (SELECT i::text x FROM instrument i WHERE i.symbol = ANY(%(look)s) UNION ALL SELECT a::text FROM instrument_alias a JOIN instrument i USING (instrument_id) WHERE i.symbol = ANY(%(look)s) UNION ALL SELECT b::text FROM bar_1d b JOIN instrument i USING (instrument_id) WHERE i.symbol = ANY(%(look)s)) q",
}  # fmt: skip
TABLES = (
    "instrument",
    "instrument_alias",
    "corporate_action_relationship",
    "bar_1d",
    "partition_load",
    "index_release_row",
    "index_monthly_constituent",
)


def fingerprints(conn: psycopg.Connection) -> dict[str, tuple[int, str]]:
    p = {"new": SYMS, "tgt": list(cfg["targets_expected"]), "look": LOOKALIKES}
    return {k: tuple(conn.execute(q, p).fetchone()) for k, q in FP.items()}  # type: ignore[misc]


def counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}  # type: ignore[index]  # noqa: S608


def rows(conn: psycopg.Connection, sql: str, *params) -> list[list[str]]:
    return [list(map(str, r)) for r in conn.execute(sql, params)]


report: dict = {
    "mode": mode,
    "config_sha256": hashlib.sha256(a.config.read_bytes()).hexdigest(),
    "applications": [],
}
bar_results = []
with psycopg.connect(a.db, autocommit=True) as conn:
    before, counts_before = fingerprints(conn), counts(conn)
    unmapped_before = {
        s: [conn.execute("SELECT count(*) FROM index_release_row WHERE symbol=%s AND mapping_status<>'MAPPED'", (s,)).fetchone()[0],  # type: ignore[index]
            conn.execute("SELECT count(*) FROM index_monthly_constituent WHERE symbol=%s AND mapping_status<>'MAPPED'", (s,)).fetchone()[0]]  # type: ignore[index]
        for s in SYMS
    }  # fmt: skip
    with conn.transaction(force_rollback=not a.apply):
        ids = {}
        for app in cfg["applications"]:
            r = apply_historical_instrument(conn, app, cfg["targets_expected"], now)
            ids[app["instrument"]["symbol"]] = r
            report["applications"].append({"item_id": app["item_id"], "instrument_id": r.instrument_id, "relationship_id": r.relationship_id, "target_instrument_id": r.target_instrument_id})  # fmt: skip
        remapped_releases, remapped_monthly = remap(conn, SYMS), remap_monthly(conn, SYMS)
        if a.with_bars:
            lake = LocalLake(a.lake)
            prov = NseBhavcopy(lambda url: b"", calendar(Path("config/exchange_sessions.json")))
            all_days = [
                date.fromisoformat(n[3:])
                for n in sorted(p.name for p in (a.lake / "raw/nse/bhav").glob("dt=*"))
            ]
            for app in cfg["applications"]:
                lo, hi = (
                    date.fromisoformat(app["alias"]["valid_from"]),
                    date.fromisoformat(app["instrument"]["last_traded_on"]),
                )
                bar_results += backfill_instruments(conn, lake, prov, "bhav", [d for d in all_days if lo <= d <= hi], {ids[app["instrument"]["symbol"]].instrument_id}, now)  # fmt: skip
        after, counts_after = fingerprints(conn), counts(conn)
        new_rows = {
            "instrument": rows(conn, "SELECT instrument_id, symbol, isin, name, status, listed_on, delisted_on, first_observed_on, last_traded_on, exchange_id FROM instrument WHERE symbol = ANY(%s) ORDER BY 1", SYMS),
            "instrument_alias": rows(conn, "SELECT instrument_id, source, source_symbol, valid_from, valid_from_basis, valid_to, valid_to_basis FROM instrument_alias WHERE source_symbol = ANY(%s) ORDER BY 1", SYMS),
            "corporate_action_relationship": rows(conn, "SELECT relationship_id, relationship_type, source_instrument_id, target_instrument_id, target_symbol, effective_date, last_source_session, ratio_num, ratio_den, verification_status, review_decision_id FROM corporate_action_relationship WHERE source_instrument_id = ANY(%s) ORDER BY 1", [v.instrument_id for v in ids.values()]),
        }  # fmt: skip
        release_rows = rows(
            conn,
            "SELECT symbol, component, action, mapping_status, count(*), min(effective_from), max(effective_from) FROM index_release_row WHERE symbol = ANY(%s) GROUP BY 1,2,3,4 ORDER BY 1,2,3,4",
            SYMS,
        )
        monthly_rows = rows(
            conn,
            "SELECT k.symbol, s.index_name, k.mapping_status, count(*), min(s.as_of), max(s.as_of) FROM index_monthly_constituent k JOIN index_monthly_snapshot s USING (snapshot_id) WHERE k.symbol = ANY(%s) GROUP BY 1,2,3 ORDER BY 1,2,3",
            SYMS,
        )
        bars_by = rows(
            conn,
            "SELECT i.symbol, count(*), min((ts AT TIME ZONE 'Asia/Kolkata')::date), max((ts AT TIME ZONE 'Asia/Kolkata')::date) FROM bar_1d b JOIN instrument i USING (instrument_id) WHERE i.symbol = ANY(%s) GROUP BY 1 ORDER BY 1",
            SYMS,
        )
    persisted = counts(conn)

status: dict[str, int] = {}
for r in bar_results:
    status[r.status] = status.get(r.status, 0) + (r.rows if r.status == "loaded" else 1)
changed = {k: [list(before[k]), list(after[k])] for k in before if before[k] != after[k]}
report.update({
    "counts_before": counts_before, "counts_after_inside_transaction": counts_after, "counts_persisted_now": persisted,
    "release_rows_remapped": remapped_releases, "monthly_constituents_remapped": remapped_monthly,
    "unmapped_before_(release_rows,monthly)": unmapped_before, "new_rows": new_rows, "release_rows_after": release_rows,
    "monthly_after": monthly_rows, "bars_after": bars_by, "bar_load_status": status,
    "fingerprint_changes_outside_the_intended_set": changed,
})  # fmt: skip
a.out_dir.mkdir(parents=True, exist_ok=True)
(a.out_dir / f"gspl_pel_{mode}.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
L = [f"# GSPL / PEL identity application: {'APPLIED' if a.apply else 'DRY RUN (rolled back; nothing written)'}" + (" - with bars" if a.with_bars else " - identity only"), "",
     f"Config `{a.config}` sha256 `{report['config_sha256']}`. Persisted right now: {persisted}.", "",
     "## Records that change (inside the transaction)", "", "| table | before | after |", "|---|---|---|",
     *[f"| {t} | {counts_before[t]} | {counts_after[t]} |" for t in counts_before if counts_before[t] != counts_after[t]], "",
     f"Press-release rows re-mapped: **{remapped_releases}**; monthly constituents re-mapped: **{remapped_monthly}**. Unmapped before [release rows, monthly]: {unmapped_before}.", "",
     "### New instrument / alias / relationship rows", "",
     *[f"- instrument {r}" for r in new_rows["instrument"]], *[f"- alias {r}" for r in new_rows["instrument_alias"]], *[f"- relationship {r}" for r in new_rows["corporate_action_relationship"]], "",
     "### Press-release rows for these symbols after [symbol, component, action, mapping, rows, first, last]", "", *[f"- {r}" for r in release_rows], "",
     "### Monthly constituents after [symbol, index, mapping, rows, first, last]", "", *[f"- {r}" for r in monthly_rows], "",
     "### Bars after [symbol, rows, first, last]", "", *([f"- {r}" for r in bars_by] or ["- none (identity-only stage)"]), "",
     "## Fingerprints outside the intended set: before vs after", "",
     "| record set | before (rows, hash) | after | unchanged |", "|---|---|---|---|",
     *[f"| {k} | {before[k][0]}, {before[k][1][:10]} | {after[k][0]}, {after[k][1][:10]} | {'yes' if before[k] == after[k] else '**NO**'} |" for k in before], ""]  # fmt: skip
(a.out_dir / f"gspl_pel_{mode}.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
