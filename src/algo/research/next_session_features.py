# ruff: noqa: E501
"""Features, exclusions and next-open entries for the next-session studies (scripts/study_next_session.py, scripts/study_reversal.py).

Moved out of the scripts so their causality can be TESTED, not inspected: every feature on day t uses bars of day t or earlier (tests/unit/research/test_next_session_features.py perturbs and truncates
the future and checks that nothing at or before t changes). The definitions are the ones the frozen study used; do not change them for a result. Research code: floats on purpose.
Inputs are date x stock panels (pandas DataFrames with the same index and columns); `NF` (Nifty 50 close) and `VX` (India VIX close) are Series on the same dates; `sec` is a Series of sector names per
stock column (NaN = none). Nothing here reads a database."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

FLAT = 0.001  # |next-session return| at or under 0.10% is FLAT (frozen before any model ran)
EXCL_KINDS = (
    "split",
    "bonus",
    "rights",
    "demerger",
    "merger",
    "arrangement",
    "arangement",
    "reduction",
    "other",
    "buy",
)
WINDOW_BEFORE, WINDOW_AFTER = 25, 22  # sessions dropped around a price-changing corporate action
GROUP_ORDER = ("A", "B", "C", "D0", "Dd", "E", "F", "G")


def corporate_action_masks(
    idx: NDArray[Any], columns: Sequence[int], actions: Iterable[tuple[int, Any, str, float | None]]
) -> tuple[NDArray[Any], NDArray[Any]]:
    """(DIV, bad). DIV[i, j] is the cash dividend whose ex-date is session i for stock column j (added back to that session's return). `bad` is True in the window around any price-changing action
    (split, bonus, rights, demerger, merger and the like) of that stock, which is dropped. An ex-date that is not a session maps to the next session."""
    col = {int(c): j for j, c in enumerate(columns)}
    T, S = len(idx), len(columns)
    div = np.zeros((T, S), dtype=np.float32)
    bad = np.zeros((T, S), dtype=bool)
    for iid, exd, kind, amt in actions:
        j = col.get(int(iid))
        if j is None:
            continue
        i = int(np.searchsorted(idx, np.datetime64(exd)))
        if i >= T:
            continue
        if kind == "dividend":
            if amt:
                div[i, j] += amt
        elif kind in EXCL_KINDS:
            bad[max(0, i - WINDOW_BEFORE) : min(T, i + WINDOW_AFTER), j] = True
    return div, bad


def next_session_return(C: pd.DataFrame, div: NDArray[Any]) -> NDArray[Any]:
    """(close[t+1] + dividend with ex-date t+1) / close[t] - 1: the frozen target, close to close. NaN when t+1 has no bar."""
    d = pd.DataFrame(div, index=C.index, columns=C.columns)
    return ((C.shift(-1) + d.shift(-1)) / C - 1).to_numpy(dtype=np.float32)


def _fwd_max(x: pd.DataFrame, h: int) -> pd.DataFrame:
    """The highest value over sessions t+1..t+h (NaN if any of them is missing)."""
    return x.rolling(h).max().shift(-h)


def _fwd_min(x: pd.DataFrame, h: int) -> pd.DataFrame:
    return x.rolling(h).min().shift(-h)


def next_open_entry(
    O: pd.DataFrame,  # noqa: E741
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    horizons: Sequence[int] = (1, 2, 3),
) -> dict[str, NDArray[Any]]:
    """Returns measured from the NEXT session's open (the first price an order placed after day t's close can get), for entries decided at the close of day t.
    entry[t] = open[t+1], valid only when it is a positive number inside that day's own [low, high] (a bad print is NaN, never repaired). ret{h}[t] = close[t+h] / entry - 1;
    mfe{h} / mae{h} = highest high / lowest low over sessions t+1..t+h against the entry (the long view; a short reads them the other way). `overnight` = entry / close[t] - 1, the gap that is
    already over before any order can fill. Everything is NaN when a needed bar is missing."""
    o1, h1, l1 = O.shift(-1), H.shift(-1), L.shift(-1)
    valid = (o1 > 0) & (o1 >= l1) & (o1 <= h1)
    entry = o1.where(valid)
    out: dict[str, NDArray[Any]] = {
        "entry": entry.to_numpy(dtype=np.float64),
        "valid": valid.to_numpy(),
        "overnight": (entry / C - 1).to_numpy(dtype=np.float64),
    }
    for h in horizons:
        out[f"ret{h}"] = (C.shift(-h) / entry - 1).to_numpy(dtype=np.float64)
        out[f"mfe{h}"] = (_fwd_max(H, h) / entry - 1).to_numpy(dtype=np.float64)
        out[f"mae{h}"] = (_fwd_min(L, h) / entry - 1).to_numpy(dtype=np.float64)
    return out


def build_features(
    O: pd.DataFrame,  # noqa: E741
    H: pd.DataFrame,
    L: pd.DataFrame,
    C: pd.DataFrame,
    V: pd.DataFrame,
    DQ: pd.DataFrame,
    NF: pd.Series,
    VX: pd.Series,
    sec: pd.Series,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """(F, aux): F[group][name] is a date x stock panel (or a broadcast array) of one feature, every one known at the close of its own date; aux carries the pieces the scripts also use."""
    T, S = C.shape

    def ema(x: pd.DataFrame, n: int) -> pd.DataFrame:
        return x.ewm(span=n, adjust=False, min_periods=n).mean()

    pc = C.shift(1)
    rng = (H - L).replace(0, np.nan)
    tr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    e20, e50 = ema(C, 20), ema(C, 50)
    dl = C.diff()
    rsi = 100 - 100 / (
        1
        + dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        / (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    )
    macd = ema(C, 12) - ema(C, 26)
    hist = (macd - macd.ewm(span=9, adjust=False).mean()) / C
    up_, dn_ = H.diff().clip(lower=0), (-L.diff()).clip(lower=0)
    pdi = 100 * up_.where(up_ > dn_, 0.0).ewm(alpha=1 / 14, adjust=False).mean() / atr
    mdi = 100 * dn_.where(dn_ > up_, 0.0).ewm(alpha=1 / 14, adjust=False).mean() / atr
    adx = (100 * (pdi - mdi).abs() / (pdi + mdi)).ewm(alpha=1 / 14, adjust=False).mean()
    vavg = V.rolling(20, min_periods=15).mean()
    ret = {k: C / C.shift(k) - 1 for k in (1, 2, 3, 5, 10, 20)}
    sgn = np.sign(ret[1].fillna(0).to_numpy())
    streak = np.zeros((T, S), dtype=np.float32)
    for t in range(1, T):
        same = sgn[t] == np.sign(streak[t - 1])
        streak[t] = np.where(sgn[t] == 0, 0, np.where(same, streak[t - 1] + sgn[t], sgn[t]))
    streak_c = np.clip(streak, -7, 7)
    gap = O / pc - 1
    intra = C / O - 1
    dper = DQ / V
    nr = {k: NF / NF.shift(k) - 1 for k in (1, 5, 20)}
    nsma50, nsma200 = NF.rolling(50, min_periods=50).mean(), NF.rolling(200, min_periods=200).mean()
    mk_up = (
        ((NF > nsma50) & (nsma50 > nsma50.shift(10)) & (nsma50 > nsma200)).fillna(False).to_numpy()
    )
    mk_dn = ((NF < nsma50) & (nsma50 < nsma50.shift(10))).fillna(False).to_numpy()
    vix_hi = (VX > VX.rolling(250, min_periods=120).median()).fillna(False).to_numpy()
    brd50 = (C > C.rolling(50, min_periods=50).mean()).where(C.notna()).mean(axis=1)
    brd_adv = (C > pc).where(C.notna() & pc.notna()).mean(axis=1)
    has_sec = sec.notna().to_numpy()
    sec_r = {k: ret[k].T.groupby(sec.to_numpy()).transform("median").T for k in (1, 5)}

    def colv(s: pd.Series) -> NDArray[Any]:
        return np.broadcast_to(s.to_numpy(dtype=np.float32)[:, None], (T, S))

    F: dict[str, dict[str, Any]] = {
        "A": {
            "ret1": ret[1],
            "ret2": ret[2],
            "ret3": ret[3],
            "ret5": ret[5],
            "ret10": ret[10],
            "gap": gap,
            "intraday": intra,
            "gap_reversal": ((gap > 0) & (intra < 0)).astype(float)
            - ((gap < 0) & (intra > 0)).astype(float),
            "streak": pd.DataFrame(streak_c, index=C.index, columns=C.columns),
        },
        "B": {
            "body": (C - O) / rng,
            "close_loc": (C - L) / rng,
            "upper_wick": (H - np.maximum(O, C)) / rng,
            "lower_wick": (np.minimum(O, C) - L) / rng,
            "c_vs_ph": C / H.shift(1) - 1,
            "c_vs_pl": C / L.shift(1) - 1,
            "gap_up": (O > H.shift(1)).astype(float),
            "gap_dn": (O < L.shift(1)).astype(float),
        },
        "C": {
            "rsi": rsi,
            "macd_hist": hist,
            "adx": adx,
            "e20_e50": e20 / e50 - 1,
            "e20_slope": e20 / e20.shift(5) - 1,
            "roc20": ret[20],
        },
        "D0": {
            "relvol": V / vavg,
            "vol_acc": V.rolling(3).mean() / vavg,
            "vol_vs5": V / V.rolling(5).mean(),
        },
        "Dd": {"dpct": dper, "dpct_vs20": dper / dper.rolling(20, min_periods=15).mean()},
        "E": {
            "n_ret1": colv(nr[1]),
            "n_ret5": colv(nr[5]),
            "n_ret20": colv(nr[20]),
            "n_regime": colv(pd.Series(mk_up.astype(float) - mk_dn.astype(float), index=C.index)),
            "n_vol20": colv(NF.pct_change().rolling(20).std()),
            "breadth50": colv(brd50),
            "adv_share": colv(brd_adv),
            "vix": colv(VX),
            "vix_chg": colv(VX.pct_change()),
            "vix_vs20": colv(VX / VX.rolling(20).mean()),
            "rel_n1": ret[1].sub(nr[1], axis=0),
            "rel_n5": ret[5].sub(nr[5], axis=0),
        },
        "F": {
            "sec_r1": sec_r[1],
            "sec_r5": sec_r[5],
            "sec_rel_n1": sec_r[1].sub(nr[1], axis=0),
            "sec_rel_n5": sec_r[5].sub(nr[5], axis=0),
            "stock_rel_sec1": ret[1] - sec_r[1],
            "stock_rel_sec5": ret[5] - sec_r[5],
        },
        "G": {
            "atr_pct": atr / C,
            "vol5_20": C.pct_change().rolling(5).std() / C.pct_change().rolling(20).std(),
            "tr_exp": tr / atr.shift(1),
            "ext_atr": (C - e20) / atr,
            "range10_atr": (H.rolling(10).max() - L.rolling(10).min()) / atr,
        },
    }
    turn = (C * V).rolling(
        20, min_periods=15
    ).mean() / 1e7  # 20-day mean turnover, Rs crore, known at the close of t
    aux = {
        "pc": pc,
        "atr": atr,
        "ret": ret,
        "nr": nr,
        "mk_up": mk_up,
        "mk_dn": mk_dn,
        "vix_hi": vix_hi,
        "has_sec": has_sec,
        "turn": turn,
    }
    return F, aux
