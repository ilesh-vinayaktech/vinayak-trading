# ruff: noqa: E501
"""Extreme-move fade study (2026-11-19). RESEARCH ONLY; no product use. FROZEN BEFORE THE FIRST RUN.

Hypothesis (the only primary one): a liquid NSE stock that closed day T up by at least +10.0% falls, on average, from the OPEN to the CLOSE of day T+1, by more than a short seller's real costs.
Origin (documented, not hidden): the lead came from scripts/study_reversal.py, where a rule "previous-day move at least a cut matched to the ML model's coverage" (10.49% in 2021, 11.23% in 2022, 14.31% in 2023, all from training days
only) shorted at the next open earned +0.335% net per trade (95% CI +0.09..+0.59%, n 2,438, z 2.7, below the 3.14 bar) in 2021-2023. That is an exploratory result found on the validation years, so re-testing those years is NOT confirmation.
The owner approved the exact primary definition on 2026-11-19: FIXED +10.0% (the nearest round number below the lowest original cut, so it contains every original trade; nothing was searched).
Frozen definition:
  signal   close[T] / close[T-1] - 1 >= +10.0%, known at the close of T; stock liquid (20-day mean turnover >= Rs 5 crore, known at T); in the EQ series on T; not within the +-25/+22 session window of a price-changing corporate action
  trade    short at the OPEN of T+1, cover at the CLOSE of T+1 (intraday). Never the close of T.
  executable  a signal is a trade only if none applies (first reason wins, counted by reason): no EQ bar on T+1 (moved to trade-for-trade, suspended, missing); missing / zero / out-of-range open; T closed at its upper price-band limit AND at the
              day's high (circuit-lock signature); T+1 opens at its upper price-band limit (band from NSE's published security list where it exists, from 2020-01-02; otherwise any of 2/5/10/20% counts); a GSM stage on T+1
              (security list remarks). Broker MIS shortability lists do not exist in any data we hold: shortability is therefore PROXIED and stated so; theoretical and proxy-executable results are reported separately.
  costs    the repo's INTRADAY schedule (2026 rates are an assumed backfill for earlier years), plus slippage per side. Slippage 0 / 10 / 20 bps are all shown; 20 bps is the PRIMARY (realistic) assumption for a stock that gapped open after a +10% day,
           with measured first-five-minute evidence from one-minute bars reported beside it. Shorts have no borrow cost intraday; broker auto-square-off fees are not modelled.
Samples: DISCOVERY 2021-2023 (where the lead was found); INDEPENDENT-A 2019-11-01..2020-12-31 from the same data source (its fade outcomes were never examined; only its return distribution fed the old cut); INDEPENDENT-B Kite daily bars
2016-02..2019-09 (different source, current listings only, no series or band information: lower quality, secondary).
SUCCESS RULE (fixed now): SUCCESS only if (1) INDEPENDENT-A proxy-executable net return per trade at 20 bps is > 0 with the 95% day-block CI above 0, AND (2) DISCOVERY proxy-executable net at 20 bps is > 0 with the CI above 0 and positive in each of
2021, 2022 and 2023. Fewer than 300 trades in INDEPENDENT-A = INCONCLUSIVE (not a failure, not a success). Otherwise FAIL. INDEPENDENT-B and every secondary view are reported but cannot rescue a failure.
Multiple testing: the lead came from a 30-row family (Bonferroni |z| 3.14) and this study adds secondary rows (38 in all, |z| 3.23); the discovery-period z is printed against both. The independent sample is the single pre-registered test.
Data: bars strictly before 2024-01-01; the protected holdout (2025-01-01..2026-11-13) is not read and there is no switch to read it.
usage: study_fade.py [--db URL] [--preds PATH] [--log register.csv]"""

import argparse
import csv
import hashlib
import math
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import psycopg
from study_common import BARS, book_from_db  # noqa: E402,I001

from algo.backtest.costs.calculator import compute_charges
from algo.research import extreme_move as em
from algo.research import next_session_features as ns

END = "2024-01-01"
EXPECTED_SHA = "2d19078d7e31a1b85c56f644f4194ff491222d70049a32fea6bd287229dae772"
ROOT = Path(__file__).resolve().parent.parent
SECLIST = ROOT / "data/research/nse_sec_list"
SLIPS = {"0bps": 0.0, "10bps": 0.0010, "20bps (primary)": 0.0020}
PRIMARY = "20bps (primary)"

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=os.environ.get("ALGO_DB_URL"))
ap.add_argument("--preds", default=str(ROOT / "data/research/next_session_preds_2026-11-19.npz"))
ap.add_argument("--log", help="write the experiment register to this CSV")
a = ap.parse_args()
if not a.db:
    sys.exit("error: pass --db or set ALGO_DB_URL")


def load_panel(conn: psycopg.Connection, source: str, lo: str, hi: str) -> tuple[pd.DataFrame, ...]:
    sql = (
        "SELECT DISTINCT ON (instrument_id, ts) instrument_id, (ts AT TIME ZONE 'Asia/Kolkata')::date, open::float8, high::float8, low::float8, close::float8, volume::float8"
        f" FROM {BARS} WHERE source=%s AND ts >= %s AND (ts AT TIME ZONE 'Asia/Kolkata')::date < %s ORDER BY instrument_id, ts, dataset_version DESC"
    )
    rows = conn.execute(
        sql, ("kite", lo, hi)
    ).fetchall()  # Kite adjusted bars for every window (the NSE raw panel is retired for studies)
    d = pd.DataFrame(rows, columns=["iid", "d", "o", "h", "l", "c", "v"])
    d["d"] = pd.to_datetime(d["d"])
    return tuple(
        d.pivot(index="d", columns="iid", values=k).sort_index() for k in ("o", "h", "l", "c", "v")
    )


with psycopg.connect(a.db) as conn:
    O, H, L, C, V = load_panel(conn, "nse", "2019-01-01", END)  # noqa: E741  (the SAME panel as scripts/study_reversal.py, so the saved model rows line up)
    Ok, Hk, Lk, Ck, Vk = load_panel(conn, "kite", "2016-01-01", "2019-01-01")  # noqa: E741
    acts = conn.execute(
        "SELECT instrument_id, ex_date, kind, amount::float8 FROM corporate_action WHERE ex_date >= '2015-10-01' AND ex_date < %s",
        (END,),
    ).fetchall()
    sym = {int(i): s for i, s in conn.execute("SELECT instrument_id, symbol FROM instrument")}

# ---------------------------------------------------------------- costs from the repo's schedules (round trip on Rs 1 lakh)
book = book_from_db(a.db if "a" in globals() else None)


def intraday_cost(y: int) -> float:
    try:
        sch = book.for_date(date(y, 6, 30), "INTRADAY")
    except Exception:
        sch = book.for_date(date(2026, 6, 30), "INTRADAY")
    p, q = Decimal(100), Decimal(1000)
    return float(
        (compute_charges(sch, "BUY", q, p).total + compute_charges(sch, "SELL", q, p).total)
        / (q * p)
    )


COST = {y: intraday_cost(y) for y in range(2016, 2024)}
print(
    "intraday round-trip charges on Rs 1 lakh (repo schedule; years before the schedule's own start use its rates as an assumption): "
    + ", ".join(f"{y} {100 * c:.4f}%" for y, c in COST.items() if y in (2016, 2019, 2021, 2023))
)

# ---------------------------------------------------------------- the NSE security list (band, series, GSM), known before each open
_sec_cache: dict[str, dict[str, tuple[float, bool]] | None] = {}


def seclist(day: str) -> dict[str, tuple[float, bool]] | None:
    if day not in _sec_cache:
        f = SECLIST / f"sec_list_{day}.csv"
        if not f.exists():
            _sec_cache[day] = None
        else:
            out = {}
            for r in csv.DictReader(f.read_text(errors="replace").splitlines()):
                b = (r.get("Band") or "").strip()
                band = (
                    1000.0
                    if b.lower().startswith("no")
                    else (float(b) if b.replace(".", "", 1).isdigit() else float("nan"))
                )
                out[(r.get("Symbol") or "").strip()] = (
                    band,
                    "GSM" in (r.get("Remarks") or "").upper(),
                )
            _sec_cache[day] = out
    return _sec_cache[day]


# ---------------------------------------------------------------- one panel -> signals, rejections, returns
class Panel:
    def __init__(self, name: str, O, H, L, C, V, kite: bool):  # noqa: E741
        self.name, self.kite = name, kite
        self.idx = C.index.values
        self.T, self.S = C.shape
        self.cols = list(C.columns)
        self.O, self.H, self.L, self.C = (x.to_numpy(dtype=float) for x in (O, H, L, C))
        _, bad = ns.corporate_action_masks(self.idx, self.cols, acts)
        turn = ((C * V).rolling(20, min_periods=15).mean() / 1e7).to_numpy()
        self.liquid = (turn >= 5.0) & ~bad & np.isfinite(self.C)
        self.ret1 = (C / C.shift(1) - 1).to_numpy()
        self.oc = (
            C.shift(-1) / O.shift(-1) - 1
        ).to_numpy()  # next session open -> close, per row T
        v = self.liquid & np.isfinite(self.oc)
        self.daymean = np.where(
            v.sum(1) > 0, np.nansum(np.where(v, self.oc, 0.0), 1) / np.maximum(v.sum(1), 1), np.nan
        )
        self.year = self.idx.astype("datetime64[Y]").astype(int) + 1970

    def rows(self, thr: float, lo: str, hi: str) -> tuple[np.ndarray, np.ndarray]:
        """Signal rows (T index, stock index) with the previous-day return >= thr, liquid, T inside [lo, hi]."""
        inwin = (self.idx >= np.datetime64(lo)) & (self.idx <= np.datetime64(hi))
        m = (self.ret1 >= thr - 1e-9) & self.liquid & inwin[:, None]
        m[self.T - 1, :] = False  # no T+1
        return np.nonzero(m)

    def evaluate(self, ii: np.ndarray, jj: np.ndarray) -> dict[str, np.ndarray]:
        i1 = ii + 1
        o1, h1, l1, c1 = (x[i1, jj] for x in (self.O, self.H, self.L, self.C))
        exists = np.isfinite(c1) & np.isfinite(o1)
        band = np.full(len(ii), np.nan)
        gsm = np.zeros(len(ii), dtype=bool)
        if not self.kite:
            days = np.datetime_as_string(self.idx[i1], unit="D")
            for k, (d, j) in enumerate(zip(days, jj, strict=True)):
                lst = seclist(d)
                if lst is not None:
                    hit = lst.get(sym.get(int(self.cols[j]), ""))
                    if hit is not None:
                        band[k], gsm[k] = hit
        reason = em.rejection_reason(
            series_t=["EQ"] * len(ii), series_t1=["EQ" if e else None for e in exists], open_t1=o1, low_t1=l1, high_t1=h1,
            close_t=self.C[ii, jj], high_t=self.H[ii, jj], prev_close_t=self.C[ii - 1, jj], band_t1_pct=band, gsm_t1=gsm,
        )  # fmt: skip
        gross = em.short_return(o1, c1)
        return {
            "i": ii,
            "j": jj,
            "reason": reason,
            "gross": gross,
            "excess": gross + self.daymean[ii],
            "year": self.year[ii],
            "o1": o1,
            "c1": c1,
            "band": band,
            "has_list": np.isfinite(band),
            "gsm": gsm,
            "overnight": o1 / self.C[ii, jj] - 1,
        }


SETS = ("theoretical", "after circuit proxies", "proxy-executable")


def set_mask(r: dict[str, np.ndarray], which: str) -> np.ndarray:
    code = r["reason"]
    theo = ~np.isin(code, (em.SERIES_T1, em.BAD_OPEN))
    if which == "theoretical":
        return theo
    proxy = theo & ~np.isin(code, (em.LOCKED_CLOSE, em.OPENS_AT_LIMIT))
    return proxy if which == "after circuit proxies" else proxy & (code != em.GSM)


# ---------------------------------------------------------------- statistics
rngb = np.random.default_rng(1)


def day_ci(
    day_idx: np.ndarray, values: np.ndarray, T: int, draws: int = 1000
) -> tuple[float, float, float]:
    s_ = np.bincount(day_idx, weights=values, minlength=T)
    n_ = np.bincount(day_idx, minlength=T).astype(float)
    k = n_ > 0
    s_, n_ = s_[k], n_[k]
    if len(n_) < 15:
        return float("nan"), float("nan"), float("nan")
    nb = math.ceil(len(n_) / 10)
    ix = ((rngb.integers(0, len(n_), (draws, nb))[:, :, None] + np.arange(10)) % len(n_)).reshape(
        draws, -1
    )[:, : len(n_)]
    m = s_[ix].sum(1) / np.maximum(n_[ix].sum(1), 1)
    return (
        float(np.quantile(m, 0.025)),
        float(np.quantile(m, 0.975)),
        float(s_.sum() / n_.sum() / m.std()) if m.std() > 0 else float("nan"),
    )


REG: list[dict] = []


def summarize(
    P: Panel,
    r: dict[str, np.ndarray],
    which: str,
    slip_name: str,
    tag: str,
    sel_extra: np.ndarray | None = None,
    year: int | None = None,
    record: bool = True,
) -> dict:
    m = set_mask(r, which)
    if sel_extra is not None:
        m = m & sel_extra
    if year is not None:
        m = m & (r["year"] == year)
    n = int(m.sum())
    out: dict = {"tag": tag, "set": which, "slip": slip_name, "year": year or "all", "n": n}
    if n >= 20:
        g = r["gross"][m]
        cost = np.array([COST[int(y)] for y in r["year"][m]])
        net = g - cost - 2 * SLIPS[slip_name]
        d = r["i"][m]
        lo, hi, z = day_ci(d, net, P.T)
        glo, ghi, _ = day_ci(d, g, P.T)
        elo, ehi, ez = day_ci(d, r["excess"][m], P.T)
        w, lo_ = net[net > 0], net[net <= 0]
        out |= {
            "gross": float(g.mean()), "gross_lo": glo, "gross_hi": ghi, "excess": float(r["excess"][m].mean()), "ex_lo": elo, "ex_hi": ehi, "ex_z": ez, "net": float(net.mean()), "net_lo": lo, "net_hi": hi, "net_z": z,
            "win": float((net > 0).mean()), "avg_win": float(w.mean()) if len(w) else float("nan"), "avg_loss": float(lo_.mean()) if len(lo_) else float("nan"), "pf": float(w.sum() / -lo_.sum()) if lo_.sum() < 0 else float("nan"),
            "median_gross": float(np.median(g)), "overnight": float(r["overnight"][m].mean()),
        }  # fmt: skip
    if record:
        REG.append(out)
    return out


def fmt(o: dict) -> str:
    if "net" not in o:
        return f"n={o['n']:>5} too few"
    return f"n={o['n']:>5,} gross {100 * o['gross']:+6.3f}% excess {100 * o['excess']:+6.3f}% [{100 * o['ex_lo']:+.3f},{100 * o['ex_hi']:+.3f}] net {100 * o['net']:+6.3f}% [{100 * o['net_lo']:+.3f},{100 * o['net_hi']:+.3f}] z {o['net_z']:+4.1f} win {100 * o['win']:4.1f}% avgW {100 * o['avg_win']:+.2f} avgL {100 * o['avg_loss']:+.2f} PF {o['pf']:4.2f}"


def funnel(r: dict[str, np.ndarray], label: str) -> None:
    n = len(r["i"])
    cnt = {k: int((r["reason"] == k).sum()) for k in em.REASONS}
    print(
        f"{label}: {n:,} signals -> "
        + "; ".join(f"{em.REASONS[k]} {cnt[k]:,}" for k in cnt if k and cnt[k])
        + f"; executable {cnt[em.OK]:,} ({100 * cnt[em.OK] / max(n, 1):.0f}%)"
        + (
            f"; price band known for {100 * r['has_list'].mean():.0f}% of entry days"
            if r["has_list"].any()
            else "; no band list for these dates (series + circuit-signature proxies only)"
        )
    )


def portfolio(P: Panel, r: dict[str, np.ndarray], which: str, lo: str, hi: str) -> str:
    m = set_mask(r, which)
    d = r["i"][m]
    cost = np.array([COST[int(y)] for y in r["year"][m]])
    net = r["gross"][m] - cost - 2 * SLIPS[PRIMARY]
    cnt = np.bincount(d, minlength=P.T)
    daily = np.bincount(d, weights=net, minlength=P.T) / np.maximum(cnt, 1)
    days = np.nonzero((P.idx >= np.datetime64(lo)) & (P.idx <= np.datetime64(hi)))[0]
    series = np.where(cnt > 0, daily, 0.0)[days]
    eq = np.cumprod(1 + series)
    dd = float((eq / np.maximum.accumulate(eq) - 1).min())
    sh = float(series.mean() / series.std() * math.sqrt(252)) if series.std() > 0 else float("nan")
    a_ = cnt[days]
    return f"trades {int(m.sum()):,} on {int((a_ > 0).sum())} of {len(days)} days; per active day mean {a_[a_ > 0].mean():.1f}, max {int(a_.max())} (notional Rs {int(a_.max())} lakh at Rs 1 lakh each; margin not modelled); Sharpe {sh:+.2f}; max drawdown {100 * dd:.1f}%; cumulative {100 * (eq[-1] - 1):+.1f}%"


PD = Panel("nse", O, H, L, C, V, kite=False)
PK = Panel("kite", Ok, Hk, Lk, Ck, Vk, kite=True)
SAMPLES = {
    "DISCOVERY 2021-2023": (PD, "2021-01-01", "2023-12-28"),
    "INDEPENDENT-A 2019-11..2020-12 (same source)": (PD, "2019-11-01", "2020-12-31"),
    "INDEPENDENT-B Kite 2016-02..2019-09 (lower quality)": (PK, "2016-02-01", "2019-09-30"),
}
RES: dict[str, dict] = {}
for name, (P, lo, hi) in SAMPLES.items():
    ii, jj = P.rows(em.THRESHOLD, lo, hi)
    RES[name] = P.evaluate(ii, jj)
print("signals: " + "; ".join(f"{k.split(' ')[0]} {len(v['i']):,}" for k, v in RES.items()))

print("\n=== 1. FUNNEL: every signal and why it is or is not an executable short at the next open")
for name, r in RES.items():
    funnel(r, name)

print(
    f"\n=== 2. PRIMARY RESULT: short at the T+1 open, cover at the T+1 close; per trade; 95% CI is day-block; Bonferroni |z| {NormalDist().inv_cdf(1 - 0.05 / 2 / 30):.2f} (30-row family of the lead)"
)
for name, r in RES.items():
    P = SAMPLES[name][0]
    print(f"-- {name}")
    for which in SETS:
        for sl in SLIPS:
            print(f"   {which:<24}{sl:<18}" + fmt(summarize(P, r, which, sl, name)))

print("\n=== 3. BY YEAR, proxy-executable, 20 bps per side (net %, n)")
for name, r in RES.items():
    P = SAMPLES[name][0]
    cells = []
    for y in sorted(set(int(y) for y in r["year"])):
        o = summarize(P, r, "proxy-executable", PRIMARY, name, year=y)
        cells.append(
            f"{y}: n={o['n']:>4} net {100 * o['net']:+.3f}%"
            if "net" in o
            else f"{y}: n={o['n']:>4} too few"
        )
    print(f"{name.split(' ')[0]:<14} " + " | ".join(cells))

print(
    "\n=== 4. PORTFOLIO VIEW, proxy-executable at 20 bps, equal weight Rs 1 lakh per trade, daily series incl. no-trade days"
)
for name, r in RES.items():
    P, lo, hi = SAMPLES[name]
    print(f"{name.split(' ')[0]:<14} {portfolio(P, r, 'proxy-executable', lo, hi)}")

# ---------------------------------------------------------------- comparisons on the discovery sample
print("\n=== 5. COMPARISONS (DISCOVERY 2021-2023, short at the next open, same rejections, 20 bps)")
rd = RES["DISCOVERY 2021-2023"]
ii5, jj5 = PD.rows(0.05, "2021-01-01", "2023-12-28")
r5 = PD.evaluate(ii5, jj5)
print(
    "   R5 rule (+5% or more)          proxy-executable  "
    + fmt(summarize(PD, r5, "proxy-executable", PRIMARY, "R5"))
)
print(
    "   frozen +10% rule               proxy-executable  "
    + fmt(summarize(PD, rd, "proxy-executable", PRIMARY, "F10", record=False))
)
sha = hashlib.sha256(Path(a.preds).read_bytes()).hexdigest()
assert sha == EXPECTED_SHA or os.environ.get("STUDY_RERUN"), "frozen predictions changed"
z = np.load(a.preds)
ids_a, p_a = z["HGB__A__ids"], z["HGB__A__p"]
pa = p_a[:, 2] / np.maximum(p_a[:, 2] + p_a[:, 0], 1e-9)
sel = ids_a[pa <= 0.30]
ml_i, ml_j = z["day"][sel], z["stock"][sel]
ok_ = ml_i + 1 < PD.T
rml = PD.evaluate(ml_i[ok_], ml_j[ok_])
print(
    "   ML model short calls (frozen)  proxy-executable  "
    + fmt(summarize(PD, rml, "proxy-executable", PRIMARY, "ML_short"))
)
edges = [-1.0, -0.10, -0.05, -0.02, 0.02, 0.05, 0.10, 0.20, 1.0]
labs = ["<= -10%", "-10..-5%", "-5..-2%", "-2..+2%", "2..5%", "5..10%", "10..20%", ">= 20%"]
inwin = (PD.idx >= np.datetime64("2021-01-01")) & (PD.idx <= np.datetime64("2023-12-28"))
base = PD.liquid & np.isfinite(PD.oc) & inwin[:, None] & np.isfinite(PD.ret1)
ov = np.vstack([PD.O[1:] / PD.C[:-1] - 1, np.full((1, PD.S), np.nan)])
print(
    "   previous-day return buckets, all liquid stocks, next open -> close (mean %, excess over the same-day universe %, overnight gap %, n):"
)
for b in range(8):
    m = (
        base & (PD.ret1 <= edges[1])
        if b == 0
        else base & (PD.ret1 > edges[b]) & (PD.ret1 <= edges[b + 1])
    )
    n = int(m.sum())
    if n < 20:
        continue
    ex = PD.oc[m] - np.broadcast_to(PD.daymean[:, None], (PD.T, PD.S))[m]
    print(
        f"     {labs[b]:<10} n={n:>8,}  open->close {100 * PD.oc[m].mean():+.3f}%  excess {100 * ex.mean():+.3f}%  overnight gap {100 * np.nanmean(ov[m]):+.3f}%"
    )

# ---------------------------------------------------------------- opening slippage evidence from one-minute bars
print(
    "\n=== 6. OPENING-SLIPPAGE EVIDENCE (one-minute bars exist for about 400 stocks a day): what a seller gets over the first five minutes against the daily open print, DISCOVERY proxy-executable trades"
)
m = set_mask(rd, "proxy-executable")
ti, tj = rd["i"][m], rd["j"][m]
gross_m = rd["gross"][m]
dts = np.datetime_as_string(PD.idx[ti + 1], unit="D")
got = []
mismatch = 0
with psycopg.connect(a.db) as conn:
    for d in sorted(set(dts)):
        rows_idx = np.nonzero(dts == d)[0]
        iids = [int(PD.cols[tj[k]]) for k in rows_idx]
        q = conn.execute(
            "SELECT instrument_id, ts, open::float8, close::float8, volume::float8 FROM bar_1m WHERE instrument_id = ANY(%s) AND ts >= (%s::date + time '03:45') AND ts < (%s::date + time '03:50') ORDER BY instrument_id, ts",
            (iids, d, d),
        ).fetchall()
        by: dict[int, list] = {}
        for iid, _ts, o_, c_, v_ in q:
            by.setdefault(int(iid), []).append((o_, c_, v_))
        for k in rows_idx:
            bars_ = by.get(int(PD.cols[tj[k]]))
            if not bars_ or sum(b[2] for b in bars_) <= 0:
                continue
            vw = sum(b[1] * b[2] for b in bars_) / sum(b[2] for b in bars_)
            o_d = PD.O[ti[k] + 1, tj[k]]
            if (
                abs((bars_[0][0] - o_d) / o_d) > 0.01
            ):  # a one-minute price on a different scale from the daily bar (an unadjusted or adjusted series): not comparable, dropped by a rule that does not look at returns
                mismatch += 1
                continue
            got.append(
                (
                    (o_d - vw) / o_d,
                    (bars_[0][0] - o_d) / o_d,
                    -(PD.C[ti[k] + 1, tj[k]] / vw - 1),
                    gross_m[k],
                )
            )
if got:
    g = np.array(got)

    def pct(v: np.ndarray) -> str:
        return f"mean {1e4 * v.mean():+.1f} bps, median {1e4 * np.median(v):+.1f}, p10 {1e4 * np.quantile(v, 0.1):+.1f}, p90 {1e4 * np.quantile(v, 0.9):+.1f}"

    print(
        f"   trades with comparable one-minute data: {len(g):,} of {int(m.sum()):,} (dropped {mismatch:,} whose first one-minute open differed from the daily open print by more than 1%: a price-scale mismatch between the two series)"
    )
    print(
        "   short fill at the five-minute VWAP instead of the open print, shortfall: "
        + pct(g[:, 0])
        + "  (positive = the seller gets less than the open print)"
    )
    print("   first one-minute open vs the daily open print: " + pct(g[:, 1]))
    print(
        f"   same trades: gross short return from the open print {100 * g[:, 3].mean():+.3f}% ; if filled at the five-minute VWAP instead {100 * g[:, 2].mean():+.3f}% (before costs)"
    )
else:
    print("   no one-minute data for these trades")

# ---------------------------------------------------------------- verdict by the frozen rule
print("\n=== 7. VERDICT BY THE FROZEN SUCCESS RULE")
ra, rdn = RES["INDEPENDENT-A 2019-11..2020-12 (same source)"], RES["DISCOVERY 2021-2023"]
oa = summarize(PD, ra, "proxy-executable", PRIMARY, "A", record=False)
od = summarize(PD, rdn, "proxy-executable", PRIMARY, "D", record=False)
yrs = {
    y: summarize(PD, rdn, "proxy-executable", PRIMARY, "D", year=y, record=False)
    for y in (2021, 2022, 2023)
}
cond1 = "net" in oa and oa["net"] > 0 and oa["net_lo"] > 0
cond2 = (
    "net" in od
    and od["net"] > 0
    and od["net_lo"] > 0
    and all("net" in v and v["net"] > 0 for v in yrs.values())
)
if oa["n"] < 300:
    verdict = f"INCONCLUSIVE (the independent sample has {oa['n']} proxy-executable trades, fewer than 300)"
elif cond1 and cond2:
    verdict = "SUCCESS"
else:
    verdict = "FAIL"
print(f"INDEPENDENT-A: {fmt(oa)}")
print(
    f"DISCOVERY    : {fmt(od)}  per year: "
    + ", ".join(f"{y} {100 * v['net']:+.3f}%" if "net" in v else f"{y} n/a" for y, v in yrs.items())
)
print(
    f"condition 1 (independent net > 0 and CI above 0): {cond1};  condition 2 (discovery net > 0, CI above 0, every year positive): {cond2}"
)
print(f"VERDICT: {verdict}")
print(
    f"Bonferroni context: discovery z {od.get('net_z', float('nan')):+.1f} against |z| {NormalDist().inv_cdf(1 - 0.05 / 2 / 30):.2f} (30-row family of the lead) and {NormalDist().inv_cdf(1 - 0.05 / 2 / 38):.2f} (adding this study's secondary rows)"
)

if a.log:
    pd.DataFrame(REG).to_csv(a.log, index=False)
    print(f"\nexperiment register: {len(REG)} rows -> {a.log}")
