# ruff: noqa: E501
"""Swing-study features, grouped by meaning, each known at the CLOSE of its own day (arrays shaped (sessions, stocks)).

Nothing here looks at a later row: every value at row t uses rows <= t only (tested by truncation). A signal built from them can only be acted on at the
next open. Levels are never fed alone where a change is available: the momentum group carries the 3-day change of RSI and MACD histogram too.
`META` names every feature with its group, so ablations can switch groups on and off."""

from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

Arr = npt.NDArray[Any]

GROUPS = {
    "price": [
        "ret_1",
        "ret_2",
        "ret_3",
        "ret_5",
        "ret_10",
        "dist_high_20",
        "dist_low_20",
        "dist_ema20",
        "dist_ema50",
        "close_loc",
        "gap",
        "up_streak",
        "hh_hl_5",
    ],
    "momentum": ["rsi_14", "rsi_chg_3", "macd_hist", "macd_hist_chg_3", "roc_10", "mom_accel"],
    "volatility": ["atr_pct", "atr_chg_5", "vol_compress", "range_ratio", "vol_adj_mom_5"],
    "volume": ["rel_vol", "vol_accel", "vol_price_div"],
    "delivery": ["deliv_pct", "deliv_chg", "deliv_qty_chg"],
}
META = {name: group for group, names in GROUPS.items() for name in names}


def _df(a: Arr) -> pd.DataFrame:
    return pd.DataFrame(a)


def features(o: Arr, h: Arr, lo: Arr, c: Arr, v: Arr, dq: Arr) -> dict[str, Arr]:
    OP, H, L, C, V, D = (_df(x) for x in (o, h, lo, c, v, dq))
    prev = C.shift(1)

    def ret(n: int) -> pd.DataFrame:
        return C / C.shift(n) - 1

    up = (C > prev).astype(float).where(prev.notna())
    streak = up.copy()
    run: Arr = np.zeros(C.shape[1])
    for i in range(len(C)):  # consecutive up closes
        run = np.where(up.iloc[i].to_numpy() == 1, run + 1, 0)
        streak.iloc[i] = run

    def ema(n: int) -> pd.DataFrame:
        return C.ewm(span=n, adjust=False, min_periods=n).mean()

    d = C.diff()
    gain = d.clip(lower=0).rolling(14, min_periods=14).mean()
    loss = (-d.clip(upper=0)).rolling(14, min_periods=14).mean()
    rsi = (
        (100 - 100 / (1 + gain / loss.replace(0, np.nan)))
        .where(loss > 0, 100.0)
        .where(gain.notna())
    )
    macd = (
        C.ewm(span=12, adjust=False, min_periods=12).mean()
        - C.ewm(span=26, adjust=False, min_periods=26).mean()
    )
    hist = macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()
    tr = pd.concat([H - L, (H - prev).abs(), (L - prev).abs()]).groupby(level=0).max()
    atr14 = tr.rolling(14, min_periods=14).mean()
    atr_pct = atr14 / C
    rng = (H - L) / C
    av20 = V.rolling(20, min_periods=20).mean().shift(1)  # norm from earlier days only
    dp = D / V
    hh = ((H > H.shift(1)) & (L > L.shift(1))).astype(float).rolling(5).sum() / 5
    f = {
        "ret_1": ret(1),
        "ret_2": ret(2),
        "ret_3": ret(3),
        "ret_5": ret(5),
        "ret_10": ret(10),
        "dist_high_20": C / H.rolling(20, min_periods=20).max() - 1,
        "dist_low_20": C / L.rolling(20, min_periods=20).min() - 1,
        "dist_ema20": C / ema(20) - 1,
        "dist_ema50": C / ema(50) - 1,
        "close_loc": ((C - L) / (H - L).replace(0, np.nan)),
        "gap": OP / prev - 1,
        "up_streak": streak,
        "hh_hl_5": hh,
        "rsi_14": rsi,
        "rsi_chg_3": rsi - rsi.shift(3),
        "macd_hist": hist / C,
        "macd_hist_chg_3": (hist - hist.shift(3)) / C,
        "roc_10": ret(10),
        "mom_accel": ret(5) - (ret(10) - ret(5)),
        "atr_pct": atr_pct,
        "atr_chg_5": atr_pct / atr_pct.shift(5) - 1,
        "vol_compress": tr.rolling(5, min_periods=5).mean() / tr.rolling(20, min_periods=20).mean(),
        "range_ratio": rng / rng.rolling(20, min_periods=20).mean().shift(1),
        "vol_adj_mom_5": ret(5) / atr_pct,
        "rel_vol": V / av20,
        "vol_accel": V.rolling(3, min_periods=3).mean() / V.rolling(20, min_periods=20).mean(),
        "vol_price_div": np.sign(ret(5))
        * (np.log(V.rolling(5, min_periods=5).mean() / V.rolling(20, min_periods=20).mean()))
        * -1,
        "deliv_pct": dp,
        "deliv_chg": dp - dp.rolling(20, min_periods=20).mean().shift(1),
        "deliv_qty_chg": D / D.rolling(20, min_periods=20).mean().shift(1),
    }
    assert set(f) == set(META)
    return {k: x.to_numpy(dtype=float) for k, x in f.items()}
