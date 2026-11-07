# ruff: noqa: E501
"""Verify and (optionally) load a bhavcopy that is already in the lake but was quarantined, e.g. the
file NSE served for 2022-08-08 as a spreadsheet under the CSV url. The raw bytes are never altered;
every claim is checked against the file itself and against the exchange's own neighbouring files.
Writes an evidence report; --load then runs the normal pipeline on the stored raw file, with its
TRUE source url and original retrieval time.
usage: recover_bhavcopy.py --lake data/lake --db postgresql://... --date 2022-08-08 --out docs/recovery/x.json [--load]"""

import argparse
import csv
import io
import json
import os
import statistics
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg

from algo.data.benchmark import levels
from algo.data.lake import LocalLake
from algo.data.pipeline import run_partition
from algo.data.providers.nse_bhavcopy import NseBhavcopy, _text, file_date

ap = argparse.ArgumentParser()
ap.add_argument("--lake", required=True, type=Path)
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--date", required=True, type=date.fromisoformat)
ap.add_argument("--out", required=True, type=Path)
ap.add_argument("--benchmarks", default="1,2,4")
ap.add_argument("--incident", type=Path, help="JSON describing an incident to embed")
ap.add_argument("--load", action="store_true")
a = ap.parse_args()
if not a.db:
    raise SystemExit("error: pass --db or set ALGO_DB_URL")
lake, d = LocalLake(a.lake), a.date


MAIN = ("EQ", "BE", "BZ")  # the series the pipeline loads


def all_rows(raw: bytes) -> list[dict[str, str]]:
    rd = csv.DictReader(io.StringIO(_text(raw)))
    rd.fieldnames = [h.strip() for h in rd.fieldnames or []]
    return [{k: (v or "").strip() for k, v in r.items()} for r in rd]


def table(raw: bytes) -> dict[str, dict[str, str]]:
    """Main-board rows by symbol (a symbol is unique within EQ/BE/BZ on a day)."""
    return {r["SYMBOL"]: r for r in all_rows(raw) if r["SERIES"] in MAIN}


def neighbour(offset: int) -> tuple[date, bytes] | None:
    for k in range(1, 6):
        day = d + timedelta(days=k * offset)
        vs = lake.versions("nse", "bhav", day)
        if vs and day.weekday() < 5:
            raw = lake.get(vs[-1])
            if file_date(raw) == day:
                return day, raw
    return None


m = lake.versions("nse", "bhav", d)[0]  # the version as first retrieved
raw = lake.get(m)  # re-verifies the stored sha256
every = all_rows(raw)
rows = table(raw)
n = len(rows)
dates = {r["DATE1"] for r in every}
main_rows = [r for r in every if r["SERIES"] in MAIN]
dup_main = len(main_rows) - n  # duplicated symbols within EQ/BE/BZ (must be 0)
series: dict[str, int] = {}
for r in every:
    series[r["SERIES"]] = series.get(r["SERIES"], 0) + 1


def num(r: dict[str, str], k: str) -> Decimal | None:
    v = r.get(k, "")
    return None if v in ("", "-") else Decimal(v)


bad_ohlc, bad_turnover, nonpos, many_dp = [], [], [], []
for s, r in rows.items():
    o, h, lo, c, q = (
        num(r, k) for k in ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "TTL_TRD_QNTY")
    )
    if any(
        (v := num(r, k)) is not None and v.as_tuple().exponent < -4  # type: ignore[operator]
        for k in ("PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "AVG_PRICE")
    ):
        many_dp.append(s)
    if None in (o, h, lo, c, q):
        continue
    assert o is not None and h is not None and lo is not None and c is not None and q is not None
    if not (lo <= o <= h and lo <= c <= h):
        bad_ohlc.append(s)
    if min(o, h, lo, c) <= 0 or q < 0:
        nonpos.append(s)
    avg, turn = num(r, "AVG_PRICE"), num(r, "TURNOVER_LACS")
    if avg is not None and turn is not None and q > 0:
        expect = q * avg / Decimal(100000)
        if abs(expect - turn) > max(Decimal("0.02"), expect * Decimal("0.01")):
            bad_turnover.append(s)

report: dict = {
    "date": str(d), "source_url": m.url, "retrieved_at": m.fetched_at, "sha256": m.checksum,
    "raw_bytes": m.size, "raw_format": "xlsx (zip)" if raw[:2] == b"PK" else "csv",
    "rows_all_series": len(every), "rows_main_board": n,
    "series_counts": dict(sorted(series.items())), "distinct_date1_values": sorted(dates),
    "duplicate_symbols_within_main_board": dup_main, "ohlc_violations": sorted(bad_ohlc), "non_positive_or_negative_volume": sorted(nonpos),
    "turnover_vs_qty_x_avg_price_mismatch": sorted(bad_turnover),
    "prices_with_more_than_4_decimals": sorted(many_dp),
}  # fmt: skip
prev, nxt = neighbour(-1), neighbour(1)
chain: dict = {}
for label, nb, which in (("previous_session_close_vs_this_prev_close", prev, "prev"),
                         ("this_close_vs_next_session_prev_close", nxt, "next")):  # fmt: skip
    if nb is None:
        chain[label] = "no neighbouring file in the lake"
        continue
    day, nraw = nb
    t = table(nraw)
    pairs = []
    for s in rows.keys() & t.keys():
        if which == "prev":
            pairs.append((s, t[s].get("CLOSE_PRICE", ""), rows[s].get("PREV_CLOSE", "")))
        else:
            pairs.append((s, rows[s].get("CLOSE_PRICE", ""), t[s].get("PREV_CLOSE", "")))
    ok = [p for p in pairs if p[1] and p[2] and Decimal(p[1]) == Decimal(p[2])]
    miss = sorted(
        p[0] for p in pairs if p[0] and not (p[1] and p[2] and Decimal(p[1]) == Decimal(p[2]))
    )
    only_neighbour = sorted(t.keys() - rows.keys())
    only_here = sorted(rows.keys() - t.keys())
    chain[label] = {
        "neighbour": str(day), "symbols_in_both": len(pairs), "closes_equal": len(ok),
        "agreement": round(len(ok) / len(pairs), 4) if pairs else None,
        "mismatching_symbols_sample": miss[:40], "in_neighbour_not_here": len(only_neighbour),
        "in_here_not_neighbour": len(only_here),
    }  # fmt: skip
report["exchange_cross_checks"] = chain
if prev and nxt:
    both = (table(prev[1]).keys() & table(nxt[1]).keys()) - rows.keys()
    report["symbols_in_both_neighbours_but_missing_here"] = sorted(both)
moves = []
for r in rows.values():
    if r["SERIES"] == "EQ" and num(r, "PREV_CLOSE") and num(r, "CLOSE_PRICE"):
        moves.append(float(Decimal(r["CLOSE_PRICE"]) / Decimal(r["PREV_CLOSE"]) - 1))
report["median_eq_move"] = round(statistics.median(moves), 6) if moves else None
with psycopg.connect(a.db) as conn:
    bm = {}
    for i in a.benchmarks.split(","):
        lv = levels(conn, int(i), d - timedelta(days=7), d)
        days = sorted(lv)
        if d in lv and len(days) > 1:
            before = days[days.index(d) - 1]
            bm[i] = {"previous": str(before), "return": round(float(lv[d] / lv[before] - 1), 6)}
    report["benchmark_returns_same_day"] = bm
    report["benchmark_sign_agrees_with_median_stock_move"] = bool(
        bm and moves and all((v["return"] > 0) == (statistics.median(moves) > 0) for v in bm.values()))  # fmt: skip
    if a.load:

        class Recovered(NseBhavcopy):
            def fetch(self, dataset: str, day: date) -> bytes:
                return raw

            def url(self, dataset: str, day: date) -> str:
                return m.url

        conn.commit()
        conn.autocommit = True
        r = run_partition(
            conn,
            lake,
            Recovered(lambda _u: raw, __import__("algo.core.calendar", fromlist=["nse"]).nse()),
            "bhav",
            d,
            datetime.now(UTC),
        )
        report["pipeline"] = {"status": r.status, "rows": r.rows}
        report["bars_loaded"] = conn.execute(
            "SELECT count(*) FROM bar_1d WHERE ts::date=%s", (d,)
        ).fetchone()[0]  # type: ignore[index]
        alias = dict(conn.execute(
            "SELECT source_symbol, instrument_id FROM instrument_alias WHERE source='nse'"
            " AND valid_from<=%s AND (valid_to IS NULL OR %s<valid_to)", (d, d)).fetchall())  # fmt: skip
        loaded = {
            iid: (o, h, lo, c, v)
            for iid, o, h, lo, c, v in conn.execute(
                "SELECT instrument_id, open, high, low, close, volume FROM bar_1d"
                " WHERE ts::date=%s", (d,))
        }  # fmt: skip
        by_id: dict[int, str] = {}
        for sym in rows:
            if sym in alias:
                by_id[alias[sym]] = sym
        diffs = []
        for iid, v in loaded.items():
            r = rows.get(by_id.get(iid, ""))
            keys = ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "TTL_TRD_QNTY")
            if r is None or tuple(Decimal(x) for x in v) != tuple(Decimal(r[k]) for k in keys):
                diffs.append(by_id.get(iid, f"instrument {iid}"))
        ids_nb = [
            {x[0] for x in conn.execute("SELECT instrument_id FROM bar_1d WHERE ts::date=%s", (nb[0],))}
            if nb else set() for nb in (prev, nxt)
        ]  # fmt: skip
        no_instrument = sorted(s_ for s_ in rows if s_ not in alias)
        nb_unknown = [
            len(json.loads(x[0]).get("unknown_symbols", [])) for x in conn.execute(
                "SELECT detail::text FROM partition_load WHERE status='loaded' AND dataset='bhav'"
                " AND partition = ANY(%s) ORDER BY id", ([nb[0] for nb in (prev, nxt) if nb],))
        ]  # fmt: skip
        report["load_reconciliation"] = {
            "bars_loaded": len(loaded), "main_board_rows_in_file": n,
            "file_symbols_resolved_to_an_instrument": len(by_id),
            "file_symbols_without_an_instrument_count": len(no_instrument),
            "neighbour_days_symbols_without_an_instrument_count": nb_unknown,
            "loaded_bars_missing_or_different_vs_the_xlsx_row": sorted(diffs),
            "instruments_with_bars_on_both_neighbouring_days_but_not_loaded":
                sorted(ids_nb[0] & ids_nb[1] - loaded.keys()),
            "instruments_loaded_but_without_a_bar_on_either_neighbour":
                len(loaded.keys() - ids_nb[0] - ids_nb[1]),
            "neighbour_bar_counts": [len(x) for x in ids_nb],
        }  # fmt: skip
if a.incident:
    report["incident"] = json.loads(a.incident.read_text())
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
print(
    json.dumps(
        {
            k: v
            for k, v in report.items()
            if k not in ("ohlc_violations", "symbols_in_both_neighbours_but_missing_here")
        },
        indent=1,
        sort_keys=True,
    )[:6000]
)
print(
    "ohlc_violations",
    len(report["ohlc_violations"]),
    "missing_vs_neighbours",
    len(report.get("symbols_in_both_neighbours_but_missing_here", [])),
)
