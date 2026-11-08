# ruff: noqa: E501  (report prose and evidence strings; this is a script, not library code)
"""Cross-index date-alignment and session-calendar audit of the stored benchmark series.
Writes four deliverables (deterministic: re-running on identical inputs gives identical files):
  benchmark_alignment_report.json, session_reconciliation_report.json,
  benchmark_unresolved_findings.json, benchmark_evidence_report.md  (+ audit_manifest.json)
Gate activation is NOT part of this audit.
usage: audit_benchmarks.py --db postgresql://... --lake data/lake --out docs/benchmark-audit"""

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from algo.data.benchmark import dataset_hash, levels, references
from algo.data.benchmark_audit import (
    BENCHMARK_ONLY_SESSION,
    DATA_GAP,
    INVESTIGATE,
    QUARANTINED_UNRESOLVED,
    UNCONFIRMED_NO_VALUE,
    Evidence,
    alignment,
    anomaly_overlap,
    discontinuities,
    net_rises,
    ratio_changes,
    reconcile,
)  # fmt: skip
from algo.data.benchmark_compare import correlation, wedge
from algo.data.benchmark_eligibility import DAILY, INTRADAY, assess
from algo.data.lake import LocalLake
from algo.data.providers.nse_bhavcopy_legacy import parse as parse_legacy
from algo.data.providers.nse_holidays import parse_holidays
from algo.data.sessions import REGULAR_HOURS, calendar

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--lake", type=Path, default=Path("data/lake"))
ap.add_argument("--sessions", type=Path, default=Path("config/exchange_sessions.json"))
ap.add_argument("--ids", default="1,2,3,4")
ap.add_argument("--out", type=Path, default=Path("docs/benchmark-audit"))
ap.add_argument("--calendar", type=Path, default=Path("docs/calendar-evidence/historical_calendar_evidence.json"))
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
LABEL = {"TOTAL_RETURN": "GROSS_TRI", "NET_TOTAL_RETURN": "NET_TRI", "PRICE": "PRICE_RETURN"}
SPECIAL_DATE = date(2022, 8, 8)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def clean(x: Any) -> Any:
    """JSON-safe, order-stable form of whatever the audit produced."""
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, float):
        return None if math.isnan(x) else round(x, 10)
    if isinstance(x, dict):
        return {str(clean(k)): clean(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, (list, tuple, set, frozenset)):
        return [clean(v) for v in (sorted(x) if isinstance(x, (set, frozenset)) else x)]
    return x


# ---------------------------------------------------------------- inputs
lake = LocalLake(a.lake)
hol_m = lake.versions("nse", "holiday_master", date.fromisoformat(
    sorted(p.name[3:] for p in (a.lake / "raw/nse/holiday_master").glob("dt=*"))[-1]))[-1]  # fmt: skip
hol_raw = lake.get(hol_m)
holidays = parse_holidays(hol_raw)
cal = calendar(a.sessions, holidays.weekday_holidays)
info = cal.session_info
calendar_version = {
    "sessions_file": str(a.sessions), "sessions_file_sha256": sha(a.sessions.read_bytes()),
    "holiday_feed_sha256": hol_m.checksum,
    "holiday_feed_years": sorted({d.year for d in holidays.weekday_holidays}),
    "regular_hours_rule": [REGULAR_HOURS[0].isoformat(), REGULAR_HOURS[1].isoformat()],
    "regular_hours_status": "current schedule, not verified for earlier years",
}  # fmt: skip
sessions_doc = json.loads(a.sessions.read_text())
listed = {s["date"]: s for s in sessions_doc["sessions"]}

with psycopg.connect(a.db) as conn:
    ids = [int(i) for i in a.ids.split(",")]
    refs = {i: references(conn, i) for i in ids}
    names = {i: f"B{i}_{refs[i]['index_symbol'].replace(' ', '')}_{LABEL[refs[i]['return_type']]}"
             for i in ids}  # fmt: skip
    series = {names[i]: levels(conn, i) for i in ids}
    rows = {names[i]: conn.execute(
        "SELECT count(*), count(DISTINCT observation_date) FROM benchmark_observation"
        " WHERE benchmark_id=%s", (i,)).fetchone() for i in ids}  # fmt: skip
    vals = {}
    for i in ids:
        v = conn.execute(
            "SELECT validation_id, passed, dataset_hash, report FROM benchmark_validation"
            " WHERE benchmark_id=%s ORDER BY validation_id DESC LIMIT 1", (i,)).fetchone()  # fmt: skip
        assert v is not None
        rep = v[3]
        vals[names[i]] = {
            "validation_id": v[0], "passed": v[1],
            "report_version": rep.get("report_version", "legacy (pass/fail only, pre-states)"),
            "technical_validation_passed": rep.get("technical_validation_passed", v[1]),
            "check_states": rep.get("check_states"),
            "owner_accepted_findings": rep.get("owner_accepted_findings", []),
            "covers_current_dataset": v[2] == dataset_hash(conn, i),
            "factsheet_all_passed": all(r["passed"] for r in rep.get("factsheet", [])),
        }  # fmt: skip
    latest = conn.execute(
        "WITH l AS (SELECT DISTINCT ON (partition) partition, status FROM partition_load"
        " WHERE source='nse' AND dataset='bhav' ORDER BY partition, id DESC)"
        " SELECT partition, status FROM l").fetchall()  # fmt: skip
    ex_dates = frozenset(r[0] for r in conn.execute(
        "SELECT DISTINCT ex_date FROM corporate_action WHERE kind='dividend'"))  # fmt: skip
    bar_days = dict(conn.execute("SELECT ts::date, count(*) FROM bar_1d GROUP BY 1").fetchall())

LEGACY = Path("docs/session-evidence/legacy_bhavcopy_check.json")
SECONDARY = Path("config/session_secondary_evidence.json")
legacy_confirmed: dict[date, dict[str, Any]] = {}
if LEGACY.exists():  # re-verify every cited file in the lake before trusting the record
    for e_ in json.loads(LEGACY.read_text())["results"]:
        d_ = date.fromisoformat(e_["date"])
        if not e_.get("existence_confirmed"):
            continue
        m_ = lake.versions("nse", "bhav_legacy", d_)[-1]
        if m_.checksum != e_["sha256"] or parse_legacy(lake.get(m_)).days != {d_}:
            raise SystemExit(
                f"{d_}: the stored legacy bhavcopy no longer matches the evidence record"
            )
        legacy_confirmed[d_] = {"url": e_["url"], "sha256": e_["sha256"],
                                "retrieved_at": e_["retrieved_at"], "rows": e_["rows"]}  # fmt: skip
secondary = json.loads(SECONDARY.read_text())["entries"] if SECONDARY.exists() else []
CALENDAR = a.calendar
ledger_closed: set[date] = set()
ledger_gap: set[date] = set()
if (
    CALENDAR.exists()
):  # exchange-file calendar evidence; every cited file is re-verified in the lake
    for k_, r_ in json.loads(CALENDAR.read_text())["dates"].items():
        d_ = date.fromisoformat(k_)
        if r_["status"] == "TRADED_CONFIRMED":
            m_ = lake.versions("nse", "bhav_legacy", d_)[-1]
            if m_.checksum != r_["instrument_bhavcopy"]["sha256"] or parse_legacy(
                lake.get(m_)
            ).days != {d_}:
                raise SystemExit(f"{d_}: the stored bhavcopy no longer matches the calendar ledger")
            legacy_confirmed.setdefault(d_, {"url": m_.url, "sha256": m_.checksum,
                                             "retrieved_at": m_.fetched_at, "rows": r_["instrument_bhavcopy"]["rows"]})  # fmt: skip
        elif r_["status"] == "CLOSED_INFERRED_BY_CHAIN":
            ledger_closed.add(d_)
        elif r_["status"] == "SESSION_LIKELY_ARCHIVE_GAP":
            ledger_gap.add(d_)
ev = Evidence(
    frozenset(p for p, s in latest if s in ("loaded", "noop")) | frozenset(legacy_confirmed),
    frozenset(p for p, s in latest if s == "not_published"),
    frozenset(p for p, s in latest if s == "quarantined"),
    min(p for p, _ in latest), max(p for p, _ in latest),
    closed_inferred=frozenset(ledger_closed), archive_gap=frozenset(ledger_gap),
)  # fmt: skip
evidence_summary = {
    "legacy_bhavcopy_confirmed_sessions": legacy_confirmed,
    "secondary_evidence_on_purpose_and_hours": secondary,
    "bhavcopy_range": [ev.first, ev.last], "loaded": len(ev.traded),
    "not_published": len(ev.not_published), "quarantined": sorted(ev.quarantined),
    "note": "weekends are requested only for listed special sessions; before the range there is no "
            "independent trading or closure evidence at all",
}  # fmt: skip
short = {n: n.split("_")[0] for n in series}
hashes = {names[i]: refs[i]["dataset_hash"] for i in ids}

# ---------------------------------------------------------------- reconciliation
rec = reconcile(series, info, ev)
al = alignment(series)
disc = discontinuities(series)
weekend = {d: (o, why, [short[s] for s in ser])
           for d, (o, why, ser) in rec.observed.items() if d.weekday() >= 5}  # fmt: skip

# ---------------------------------------------------------------- the 41 vs 395 anomalies
by = {refs[i]["return_type"] + refs[i]["index_symbol"]: names[i] for i in ids}


def short_of(key: str) -> str:
    return by[key].split("_")[0]


n200_g, n200_p = series[by["TOTAL_RETURNNIFTY 200"]], series[by["PRICENIFTY 200"]]
n50_g, n50_n = series[by["TOTAL_RETURNNIFTY 50"]], series[by["NET_TOTAL_RETURNNIFTY 50"]]
w = wedge(n200_p, n200_g)
price_beats = {d: -x for d, x in w.price_beats_tri}
price_gain = {d: -x for d, x in w.daily}
rises = net_rises(n50_g, n50_n)
overlap = anomaly_overlap(price_beats, rises, price_gain, ratio_changes(n50_g, n50_n), ex_dates)
union_days = sorted(
    (set(price_beats) | set(rises)) & set(price_gain) & set(ratio_changes(n50_g, n50_n))
)
rc = ratio_changes(n50_g, n50_n)
overlap["magnitude_correlation_on_anomaly_union"] = (
    correlation([price_gain[d] for d in union_days], [rc[d] for d in union_days])
    if len(union_days) > 2 else None
)  # fmt: skip
overlap["price_vs_tri"] = {
    "max_abs_gain": max((abs(x) for x in price_beats.values()), default=0.0),
    "first": min(price_beats), "last": max(price_beats),
    "by_year": dict(sorted(Counter(d.year for d in price_beats).items())),
}  # fmt: skip
overlap["net_vs_gross"] = {
    "max_abs_gain": max(rises.values(), default=0.0), "first": min(rises), "last": max(rises),
    "by_year": dict(sorted(Counter(d.year for d in rises).items())),
}  # fmt: skip
low = max(overlap["price_vs_tri"]["max_abs_gain"], overlap["net_vs_gross"]["max_abs_gain"]) < 1e-4
overlap["severity"] = "LOW" if low else "REVIEW"
overlap["materiality"] = (
    "numerical behaviour below 0.01% a day; not a material correctness issue for daily research"
    if low else "magnitude exceeds 0.01% a day: review"
)  # fmt: skip

# ---------------------------------------------------------------- 2022-08-08
window = [d for d in sorted(set(bar_days) | set(ev.not_published) | ev.quarantined | set(rec.observed))
          if abs((d - SPECIAL_DATE).days) <= 4]  # fmt: skip
special = {
    "date": SPECIAL_DATE, "weekday": SPECIAL_DATE.strftime("%A"),
    "benchmark_values": {short[n]: lv.get(SPECIAL_DATE) for n, lv in sorted(series.items())},
    "bhavcopy_status": "quarantined" if SPECIAL_DATE in ev.quarantined
    else "loaded" if SPECIAL_DATE in ev.traded else "other",
    "bars_per_day_around": {d: bar_days.get(d, 0) for d in window},
    "bhavcopy_status_around": {d: ("loaded" if d in ev.traded else "not_published" if
                               d in ev.not_published else "quarantined" if d in ev.quarantined
                               else "none") for d in window},
    "benchmark_observation_exists": all(SPECIAL_DATE in lv for lv in series.values()),
    "exchange_traded_independently_shown": SPECIAL_DATE in ev.traded,
    "affects": (
        "resolved: the exchange's own file was recovered (docs/recovery/bhavcopy_2022-08-08.json)"
        if SPECIAL_DATE in ev.traded else
        "EVERY instrument history (no daily bar exists for the date; neighbouring days have "
        f"{bar_days.get(date(2022, 8, 5), 0)} and {bar_days.get(date(2022, 8, 10), 0)} "
        "instruments) as well as the session-level reconciliation; the benchmark series are "
        "unaffected. Nothing was fabricated."),
    "note": (
        "the day's existence is shown by the exchange's own bhavcopy and by the PREV_CLOSE chain of "
        "the 2022-08-05 and 2022-08-10 files"
        if SPECIAL_DATE in ev.traded else
        "the benchmark values are the only evidence that the day was a session"),
}  # fmt: skip

# ---------------------------------------------------------------- historical hours
bar_info = [info(d) for d in sorted(bar_days)]
hours = {
    "rule": calendar_version["regular_hours_rule"], "status": calendar_version["regular_hours_status"],
    "bar_days": len(bar_info), "bar_days_first": min(bar_days), "bar_days_last": max(bar_days),
    "bar_days_on_regular_rule_hours": sum(i.hours_status == "RULE" for i in bar_info),
    "bar_days_on_assumed_special_hours": [i.day for i in bar_info if i.bar_visibility == "ASSUMPTION"],
    "benchmark_dates_before_bar_history": sum(d < min(bar_days) for d in rec.observed),
    "statement": "no historical session hours are held as evidence; every intraday bar visibility "
                 "decision relies on the current 09:15-15:30 schedule, and special sessions on "
                 "assumed regular hours. Daily benchmark levels do not depend on hours.",
}  # fmt: skip

# ---------------------------------------------------------------- outputs
exceptions = {
    k: sorted(d for d, (o, _w, _s) in rec.observed.items() if o == k)
    for k in (INVESTIGATE, QUARANTINED_UNRESOLVED, BENCHMARK_ONLY_SESSION)
}  # fmt: skip
alignment_report = {
    "audit": "benchmark_alignment", "calendar_version": calendar_version,
    "benchmarks": {n: {
        "benchmark_id": int(short[n][1:]), "dataset_hash": hashes[n],
        "first": min(series[n]), "last": max(series[n]), "observations": len(series[n]),
        "stored_rows": rows[n][0], "distinct_dates": rows[n][1],
        "duplicate_dates": rows[n][0] - rows[n][1], "validation": vals[n],
        "weekend_observations": sorted(d for d in series[n] if d.weekday() >= 5),
    } for n in sorted(series)},  # fmt: skip
    "date_differences": al,
    "discontinuities_5pct": {
        "counts": dict(Counter(x["status"] for x in disc)), "items": disc,
    },
    "anomaly_overlap": overlap,
    "limits": ["coverage differs by design: Nifty 50 gross starts 1999-06-30, Nifty 50 net "
               "2000-01-03, the other two 2004-01-01"],
}  # fmt: skip
session_report = {
    "audit": "session_reconciliation",
    "calendar_version": calendar_version,
    "dataset_hashes": hashes,
    "evidence": evidence_summary,
    "rules": {
        "CONFIRMED_REGULAR": "value + bhavcopy on a weekday: the session EXISTED; its kind is regular by the weekday rule only and its hours are assumed, not confirmed",
        "CONFIRMED_SPECIAL": "value + bhavcopy on a listed special session (kind/hours unconfirmed)",
        "WEEKDAY_RULE_PROVISIONAL": "weekday value with no independent evidence (calendar rule only)",
        "BENCHMARK_ONLY_SESSION": "listed session whose only evidence is the benchmark (circular)",
        "QUARANTINED_UNRESOLVED": "value on a day whose bhavcopy is quarantined",
        "INVESTIGATE": "value with no known session, or contradicted by the evidence",
        "DATA_GAP": "bhavcopy proves trading but the series has no value",
        "ALIGNMENT_GAP": "no value, but another series has one",
        "EXPECTED_CLOSED": "no value; holiday list or no bhavcopy published",
        "EXPECTED_NO_SESSION": "no value on an ordinary weekend (counted, not listed)",
        "UNCONFIRMED_NO_VALUE": "weekday without value, no independent closure evidence",
    },
    "observed_counts": rec.observed_counts,
    "exceptions": exceptions,
    "benchmark_only_sessions": [
        {
            "date": d,
            "kind": listed[d.isoformat()]["kind"],
            "kind_status": listed[d.isoformat()]["kind_status"].split(" ")[0],
            "hours_status": listed[d.isoformat()]["hours_status"].split(" ")[0],
        }
        for d in exceptions[BENCHMARK_ONLY_SESSION]
    ],  # fmt: skip
    "missing": {n: {k: v for k, v in m.items()} for n, m in sorted(rec.missing.items())},
    "missing_counts": rec.missing_counts,
    "special_2022_08_08": special,
    "historical_session_hours": hours,
}
session_report["observed"] = {
    d: [o, [short[s] for s in ser]] for d, (o, _w, ser) in sorted(rec.observed.items())
}
gaps = {n: m.get(DATA_GAP, []) for n, m in rec.missing.items()}
unconf = {n: len(m.get(UNCONFIRMED_NO_VALUE, [])) for n, m in rec.missing.items()}
refs_ = {"A": "benchmark_alignment_report.json", "S": "session_reconciliation_report.json"}


def item(id_: str, title: str, sev: str, status: str, cat: str, detail: str, evidence: list[str],
         material: bool) -> dict[str, Any]:  # fmt: skip
    return {"id": id_, "title": title, "severity": sev, "status": status, "category": cat,
            "material_correctness_issue": material, "detail": detail, "evidence": evidence,
            "dataset_hashes": hashes, "calendar_version": calendar_version["sessions_file_sha256"]}  # fmt: skip


findings = [
    item(
        "U01",
        "2022-08-08 bhavcopy quarantined"
        if SPECIAL_DATE not in ev.traded
        else "2022-08-08 bhavcopy recovered from the spreadsheet NSE served",
        "HIGH" if SPECIAL_DATE not in ev.traded else "INFO",
        "UNRESOLVED" if SPECIAL_DATE not in ev.traded else "RESOLVED",
        "session-evidence",
        special["affects"],
        [f"{refs_['S']}#special_2022_08_08", "docs/recovery/bhavcopy_2022-08-08.json"],
        SPECIAL_DATE not in ev.traded,
    ),
    item(
        "U02",
        "Historical session hours are not verified",
        "HIGH",
        "UNRESOLVED",
        "session-hours",
        hours["statement"],
        [f"{refs_['S']}#historical_session_hours"],
        False,
    ),
    item(
        "U03",
        "Special-session kinds are unconfirmed and their hours unknown"
        + (
            "; some are evidenced only by the benchmark"
            if exceptions[BENCHMARK_ONLY_SESSION]
            else ""
        ),
        "MEDIUM",
        "UNRESOLVED",
        "session-evidence",
        f"{len(listed)} listed sessions; existence is confirmed by an exchange bhavcopy for "
        f"{len(listed) - len(exceptions[BENCHMARK_ONLY_SESSION])} of them "
        f"({len([d for d in listed if date.fromisoformat(d) in legacy_confirmed])} via the legacy archive), but every kind is UNCONFIRMED and every "
        f"opening and closing time UNKNOWN. {len(secondary)} have secondary (broker bulletin) "
        "claims about purpose and hours, recorded but not promoted.",
        [
            f"{refs_['S']}#evidence",
            "config/exchange_sessions.json",
            "config/session_secondary_evidence.json",
            "docs/session-evidence/legacy_bhavcopy_check.json",
        ],
        False,
    ),
    item(
        "U04",
        "Weekday sessions before the bhavcopy history rest on the calendar rule",
        "MEDIUM",
        "UNRESOLVED",
        "session-evidence",
        f"{rec.observed_counts.get('WEEKDAY_RULE_PROVISIONAL', 0)} observed weekdays are provisional;"
        f" {sum(unconf.values())} weekday no-value dates across the series are unconfirmed (no "
        "historical holiday list is held; the feed covers "
        f"{calendar_version['holiday_feed_years']} only).",
        [f"{refs_['S']}#observed_counts"],
        False,
    ),
    item(
        "U05",
        "Price return exceeds gross TRI by up to 0.005% on some days",
        "LOW",
        "UNRESOLVED",
        "numerical-behaviour",
        f"{len(price_beats)} days from {min(price_beats)}; mechanism unknown. Overlap verdict with "
        f"the net/gross rises: {overlap['verdict']}.",
        [f"{refs_['A']}#anomaly_overlap"],
        False,
    ),
    item(
        "U06",
        "Net TRI gains on gross TRI on 41 days (0.002-0.006%)",
        "LOW",
        "UNRESOLVED",
        "numerical-behaviour",
        f"{len(rises)} days, dividend-ex-date share "
        f"{overlap['ex_date_share_b']:.2f} against {overlap['ex_date_share_all_common_dates']:.2f} "
        "of all days.",
        ["benchmark_validation (benchmark 3)", f"{refs_['A']}#anomaly_overlap"],
        False,
    ),
    item(
        "U07",
        "11 net/gross jumps on bonus ex-dates: explained, not numerically reconciled",
        "LOW",
        "ACCEPTED_WITH_EVIDENCE",
        "methodology",
        "label EXPLAINED_BY_METHODOLOGY_NOT_NUMERICALLY_"
        "RECONCILED; the net validation stays technically failed.",
        ["benchmark_validation (benchmark 3)"],
        False,
    ),
    item(
        "U08",
        "Gross and net independence unknown; net is a non-resident institutional measure",
        "MEDIUM",
        "UNRESOLVED",
        "methodology",
        "same response row; tax basis 23.92% current rate, "
        "historical rates undocumented; net starts 2000-01-03.",
        ["docs/tri-endpoint-report.md"],
        False,
    ),
    item(
        "U09",
        "Revision behaviour of the endpoints untested",
        "MEDIUM",
        "UNRESOLVED",
        "provenance",
        "only same-day repeats were compared (identical); a later re-fetch is needed.",
        ["docs/tri-endpoint-report.md"],
        False,
    ),
    item(
        "U10",
        "Only the Sep 2026 methodology document is held",
        "MEDIUM",
        "UNRESOLVED",
        "provenance",
        "historical index methodology and dividend treatment cannot be checked.",
        ["docs/tri-endpoint-report.md"],
        False,
    ),
    item(
        "U11",
        "Factsheet CAGR convention unidentified; Nifty 50 gross since-inception not reproducible",
        "LOW",
        "UNRESOLVED",
        "reconciliation",
        "differences up to ~0.01 pp; the published 12.15% matches only from an assumed 1995 base.",
        ["benchmark_validation (benchmark 2)"],
        False,
    ),
]
legacy = sorted(n for n, v in vals.items() if str(v["report_version"]).startswith("legacy"))
if legacy:
    findings.append(
        item(
            "U12",
            "Benchmark validations predate the PASS/FAIL/ACCEPTED report format",
            "LOW",
            "UNRESOLVED",
            "provenance",
            f"{legacy}: their reports record pass/fail only.",
            [f"{refs_['A']}#benchmarks"],
            False,
        )
    )
if any(gaps.values()):
    findings.append(
        item(
            "U13",
            "Confirmed trading sessions without a benchmark value",
            "HIGH",
            "UNRESOLVED",
            "data-gap",
            json.dumps(clean(gaps)),
            [f"{refs_['S']}#missing"],
            True,
        )
    )
if exceptions[INVESTIGATE]:
    findings.append(
        item(
            "U14",
            "Benchmark values with no known session",
            "HIGH",
            "UNRESOLVED",
            "session-evidence",
            str(len(exceptions[INVESTIGATE])) + " dates",
            [f"{refs_['S']}#exceptions"],
            True,
        )
    )
unexplained = [x for x in disc if x["status"] == "UNEXPLAINED"]
if unexplained:
    findings.append(
        item(
            "U15",
            "Large daily moves not corroborated by another series",
            "MEDIUM",
            "UNRESOLVED",
            "discontinuity",
            f"{len(unexplained)} moves",
            [f"{refs_['A']}#discontinuities_5pct"],
            True,
        )
    )
single = [x for x in disc if x["status"] == "UNCORROBORATED_SINGLE_SERIES"]
if single:
    findings.append(
        item(
            "U16",
            "Large daily moves seen by one series only",
            "LOW",
            "UNRESOLVED",
            "discontinuity",
            f"{len(single)} moves (pre-2000/2004 Nifty 50 history; nothing to compare)",
            [f"{refs_['A']}#discontinuities_5pct"],
            False,
        )
    )
SCOPE = {  # id -> (applies_to, blocks)
    "U01": (["ALL"], []), "U02": (["ALL"], [INTRADAY]), "U03": (["ALL"], [INTRADAY]),
    "U04": (["ALL"], []),
    "U05": ([short_of("TOTAL_RETURNNIFTY 200"), short_of("PRICENIFTY 200")], []),
    "U06": ([short_of("TOTAL_RETURNNIFTY 50"), short_of("NET_TOTAL_RETURNNIFTY 50")], []),
    "U07": ([short_of("NET_TOTAL_RETURNNIFTY 50")], []),
    "U08": ([short_of("TOTAL_RETURNNIFTY 50"), short_of("NET_TOTAL_RETURNNIFTY 50")], []),
    "U09": (["ALL"], []), "U10": (["ALL"], []), "U11": (["ALL"], []), "U12": (["ALL"], []),
    "U13": (["ALL"], [DAILY]), "U14": (["ALL"], [DAILY]), "U15": (["ALL"], [DAILY]),
    "U16": (["ALL"], []),
}  # fmt: skip
for f_ in findings:
    f_["applies_to"], f_["blocks"] = SCOPE[f_["id"]]
    f_["blocked_dates"] = [SPECIAL_DATE] if f_["id"] == "U01" and f_["status"] != "RESOLVED" else []
unresolved_report = {"audit": "benchmark_unresolved_findings", "gate_activation": "NOT decided here",
                     "findings": findings}  # fmt: skip

a.out.mkdir(parents=True, exist_ok=True)
eligibility = {
    "audit": "benchmark_eligibility",
    "states": ["DATA_INGESTED", "RESEARCH_ELIGIBLE", "BENCHMARK_GATE_ELIGIBLE"],
    "gate_activation": "NOT decided here; the gate stays disabled",
    "instrument_level_blocked_dates": [] if SPECIAL_DATE in ev.traded else [SPECIAL_DATE],
    "benchmarks": {
        n: {"dataset_hash": hashes[n], **assess(short[n], vals[n], findings)}
        for n in sorted(series)
    },  # fmt: skip
}
outs = {
    "benchmark_eligibility.json": eligibility,
    "benchmark_alignment_report.json": alignment_report,
    "session_reconciliation_report.json": session_report,
    "benchmark_unresolved_findings.json": unresolved_report,
}
for fn, doc in outs.items():
    (a.out / fn).write_text(json.dumps(clean(doc), indent=1, sort_keys=True) + "\n")

# ---------------------------------------------------------------- human-readable report
md = [
    "# Benchmark evidence report",
    "",
    "Cross-index alignment and session-calendar audit. Generated; deterministic for identical "
    "inputs. **This report does not enable any benchmark gate.**",
    "",
    "## Series",
    "",
    "| series | first | last | obs | duplicates | dataset hash | validation | passed | report | "
    "covers current data |",
    "|---|---|---|---:|---:|---|---:|---|---|---|",
]
for n in sorted(series):
    v = vals[n]
    md.append(
        f"| {n} | {min(series[n])} | {max(series[n])} | {len(series[n])} | "
        f"{rows[n][0] - rows[n][1]} | `{hashes[n][:12]}` | {v['validation_id']} | "
        f"{v['passed']} | {v['report_version']} | {v['covers_current_dataset']} |"
    )
md += [
    "",
    "Coverage differs by design (Nifty 50 gross 1999-06-30, net 2000-01-03, the others "
    "2004-01-01); those dates are classified COVERAGE differences, not gaps.",
    "",
    "## Calendar and evidence",
    "",
    f"- sessions file sha256 `{calendar_version['sessions_file_sha256'][:12]}`, holiday feed "
    f"`{calendar_version['holiday_feed_sha256'][:12]}` (years {calendar_version['holiday_feed_years']})",
    f"- independent trading evidence = bhavcopy: {len(ev.traded)} loaded, {len(ev.not_published)} "
    f"not published, quarantined {[str(d) for d in sorted(ev.quarantined)]}, range {ev.first}..{ev.last}",
    "- a benchmark value is never used as evidence that the exchange traded",
    "",
    "## Observed dates by outcome",
    "",
    "| outcome | dates |",
    "|---|---:|",
]
md += [f"| {k} | {v} |" for k, v in sorted(rec.observed_counts.items())]
md += [
    "",
    "## Missing values inside each series' coverage",
    "",
    "| series | " + " | ".join(sorted({k for m in rec.missing_counts.values() for k in m})) + " |",
]
cols = sorted({k for m in rec.missing_counts.values() for k in m})
md += ["|---|" + "---:|" * len(cols)]
md += [
    f"| {n} | " + " | ".join(str(m.get(c, 0)) for c in cols) + " |"
    for n, m in sorted(rec.missing_counts.items())
]
md += [
    "",
    f"Confirmed trading sessions without a value (DATA_GAP): {sum(len(g) for g in gaps.values())}.",
    "",
    "## Discontinuities (>=5% a day)",
    "",
    f"{dict(Counter(x['status'] for x in disc))}",
    "",
    "## Anomaly overlap (Price vs TRI, Net vs Gross)",
    "",
    f"- price beats TRI: {len(price_beats)} days; net gains on gross: {len(rises)} days",
    f"- intersection {len(overlap['intersection'])} dates (expected by chance "
    f"{overlap['expected_by_chance']:.2f}) -> **{overlap['verdict']}**",
    f"- magnitude correlation, all common dates: {overlap['magnitude_correlation_all_common_dates']}; "
    f"on the anomaly union: {overlap['magnitude_correlation_on_anomaly_union']}",
    f"- dividend ex-date share: price {overlap['ex_date_share_a']:.2f}, net {overlap['ex_date_share_b']:.2f}, "
    f"all common dates {overlap['ex_date_share_all_common_dates']:.2f}",
    f"- severity {overlap['severity']}: {overlap['materiality']}",
    "",
    "## 2022-08-08",
    "",
    special["affects"],
    "",
    "## Historical session hours",
    "",
    hours["statement"],
    "",
    "## Eligibility (separate states; the gate stays disabled)",
    "",
    "| series | state | daily research | intraday research | gate |",
    "|---|---|---|---|---|",
]
for n in sorted(series):
    e = eligibility["benchmarks"][n]
    u = e["uses"]
    md.append(
        f"| {n} | {e['state']} | {u['DAILY_RESEARCH']['eligible']} | "
        f"{u['INTRADAY_RESEARCH']['eligible']} | {u['BENCHMARK_GATE']['eligible']} |"
    )
md += [
    "",
    "Instrument-level research must exclude: "
    + (", ".join(str(x) for x in eligibility["instrument_level_blocked_dates"]) or "no date")
    + ".",
    "",
    "## Unresolved findings",
    "",
    "| id | severity | status | title |",
    "|---|---|---|---|",
]
md += [f"| {f['id']} | {f['severity']} | {f['status']} | {f['title']} |" for f in findings]
md += [
    "",
    "Full machine-readable detail: `benchmark_alignment_report.json`, "
    "`session_reconciliation_report.json`, `benchmark_unresolved_findings.json`.",
    "",
]
(a.out / "benchmark_evidence_report.md").write_text("\n".join(md))

manifest = {fn: sha((a.out / fn).read_bytes()) for fn in [*outs, "benchmark_evidence_report.md"]}
manifest["dataset_hashes"] = hashes  # type: ignore[assignment]
(a.out / "audit_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
print(json.dumps(manifest, indent=1, sort_keys=True))
print("observed outcomes:", rec.observed_counts)
print("missing counts:", rec.missing_counts)
print("overlap verdict:", overlap["verdict"], len(overlap["intersection"]))
