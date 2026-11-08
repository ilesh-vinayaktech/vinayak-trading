"""Every indicator against an independent longhand float implementation written straight from its
definition (Wilder, Pine, Wikipedia), on random data. The catalogue works in Decimal with shared
primitives; these references share nothing with it, so agreement is real evidence."""

import math
import random
from decimal import Decimal as D

import pytest

from algo.indicators.catalog import CATALOG, Bars, compute


def make(seed, n=220):
    rng = random.Random(seed)
    price, o, h, lo, c, v = 100.0, [], [], [], [], []
    for _ in range(n):
        o.append(price)
        price *= 1 + rng.uniform(-0.03, 0.03)
        c.append(price)
        h.append(max(o[-1], price) * (1 + rng.uniform(0, 0.01)))
        lo.append(min(o[-1], price) * (1 - rng.uniform(0, 0.01)))
        v.append(float(rng.randint(1000, 90000)))
    return o, h, lo, c, v


def dec(xs):
    return [D(repr(x)) for x in xs]


def ref_sma(x, n):
    return [None if i < n - 1 else sum(x[i - n + 1 : i + 1]) / n for i in range(len(x))]


def ref_ema(x, n, alpha=None):
    a = 2 / (n + 1) if alpha is None else alpha
    out = [None] * len(x)
    for i in range(n - 1, len(x)):
        out[i] = sum(x[:n]) / n if i == n - 1 else a * x[i] + (1 - a) * out[i - 1]
    return out


def ref_rma(x, n):
    return ref_ema(x, n, alpha=1 / n)


def ref_tr(h, lo, c):
    return [h[0] - lo[0]] + [
        max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))
    ]


def ref_rsi(c, n):
    up = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    dn = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    au, ad = ref_rma(up, n), ref_rma(dn, n)
    return [None] + [
        None if u is None else (100.0 if d == 0 else 100 - 100 / (1 + u / d))
        for u, d in zip(au, ad, strict=True)
    ]


def ref_macd(c, f, s, g):
    ef, es = ref_ema(c, f), ref_ema(c, s)
    line = [None if a is None or b is None else a - b for a, b in zip(ef, es, strict=True)]
    first = next(i for i, v in enumerate(line) if v is not None)
    sig = [None] * first + ref_ema(line[first:], g)
    return (
        line,
        sig,
        [None if a is None or b is None else a - b for a, b in zip(line, sig, strict=True)],
    )


def ref_bb(c, n, m):
    basis = ref_sma(c, n)
    sd = [
        None if i < n - 1 else math.sqrt(sum((v - basis[i]) ** 2 for v in c[i - n + 1 : i + 1]) / n)
        for i in range(len(c))
    ]
    return (
        basis,
        [None if b is None else b + m * s for b, s in zip(basis, sd, strict=True)],
        [None if b is None else b - m * s for b, s in zip(basis, sd, strict=True)],
    )


def ref_stoch(h, lo, c, k, d, sm):
    raw = [
        None
        if i < k - 1
        else 100
        * (c[i] - min(lo[i - k + 1 : i + 1]))
        / (max(h[i - k + 1 : i + 1]) - min(lo[i - k + 1 : i + 1]))
        for i in range(len(c))
    ]
    first = k - 1
    kk = [None] * first + ref_sma(raw[first:], sm)
    f2 = first + sm - 1
    return kk, [None] * f2 + ref_sma(kk[f2:], d)


def ref_adx(h, lo, c, n, sm):
    pdm, mdm = [0.0], [0.0]
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], lo[i - 1] - lo[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    tr = ref_rma(ref_tr(h, lo, c), n)
    p = [None] + ref_rma(pdm[1:], n)
    m = [None] + ref_rma(mdm[1:], n)
    pi = [None if t is None or a is None else 100 * a / t for t, a in zip(tr, p, strict=True)]
    mi = [None if t is None or a is None else 100 * a / t for t, a in zip(tr, m, strict=True)]
    dx = [None if a is None else abs(a - b) / (a + b) for a, b in zip(pi, mi, strict=True)]
    first = next(i for i, v in enumerate(dx) if v is not None)
    return (
        [None] * first + [100 * v if v is not None else None for v in ref_rma(dx[first:], sm)],
        pi,
        mi,
    )


def ref_cci(h, lo, c, n):
    tp = [(a + b + d) / 3 for a, b, d in zip(h, lo, c, strict=True)]
    out = [None] * len(c)
    for i in range(n - 1, len(c)):
        w = tp[i - n + 1 : i + 1]
        mean = sum(w) / n
        md = sum(abs(v - mean) for v in w) / n
        out[i] = (tp[i] - mean) / (0.015 * md)
    return out


def ref_willr(h, lo, c, n):
    return [
        None
        if i < n - 1
        else -100
        * (max(h[i - n + 1 : i + 1]) - c[i])
        / (max(h[i - n + 1 : i + 1]) - min(lo[i - n + 1 : i + 1]))
        for i in range(len(c))
    ]


def ref_obv(c, v):
    out, t = [0.0], 0.0
    for i in range(1, len(c)):
        t += v[i] if c[i] > c[i - 1] else -v[i] if c[i] < c[i - 1] else 0
        out.append(t)
    return out


def ref_psar(h, lo, c, start, inc, mx):
    """Wikipedia's algorithm, one trend at a time."""
    up = c[1] >= c[0]
    sar, ep, af = (lo[0], h[0], start) if up else (h[0], lo[0], start)
    out = [sar]
    for i in range(1, len(c)):
        nxt = sar + af * (ep - sar)
        if up:
            nxt = min(nxt, lo[i - 1], lo[i - 2] if i > 1 else lo[i - 1])
            if lo[i] < nxt:
                up, nxt, ep, af = False, ep, lo[i], start
            elif h[i] > ep:
                ep, af = h[i], min(af + inc, mx)
        else:
            nxt = max(nxt, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > nxt:
                up, nxt, ep, af = True, ep, h[i], start
            elif lo[i] < ep:
                ep, af = lo[i], min(af + inc, mx)
        sar = nxt
        out.append(sar)
    return out


def ref_supertrend(h, lo, c, n, m):
    atr = ref_rma(ref_tr(h, lo, c), n)
    up, down, fu, fl, trend = [None] * len(c), [None] * len(c), None, None, None
    for i, a in enumerate(atr):
        if a is None:
            continue
        mid = (h[i] + lo[i]) / 2
        bu, bl = mid + m * a, mid - m * a
        if fu is None:
            fu, fl, trend = bu, bl, "down"
        else:
            fu = bu if (bu < fu or c[i - 1] > fu) else fu
            fl = bl if (bl > fl or c[i - 1] < fl) else fl
            if trend == "down" and c[i] > fu:
                trend = "up"
            elif trend == "up" and c[i] < fl:
                trend = "down"
        (up if trend == "up" else down)[i] = fl if trend == "up" else fu
    return up, down


def agree(got, want, tol=1e-7):
    assert len(got) == len(want)
    for i, (g, w) in enumerate(zip(got, want, strict=True)):
        if w is None:
            assert g is None, (i, g)
        else:
            assert g is not None and abs(float(g) - w) <= tol * max(1.0, abs(w)), (i, g, w)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_indicators_agree_with_independent_references(seed):
    o, h, lo, c, v = make(seed)
    b = Bars(dec(o), dec(h), dec(lo), dec(c), dec(v))
    run = lambda spec: compute(spec, b)[2]  # noqa: E731
    agree(run("sma:20")["value"], ref_sma(c, 20))
    agree(run("ema:21")["value"], ref_ema(c, 21))
    wma = [
        None if i < 9 else sum(c[i - 9 + k] * (k + 1) for k in range(10)) / 55
        for i in range(len(c))
    ]
    agree(run("wma:10")["value"], wma)
    agree(run("rsi:14")["value"], ref_rsi(c, 14))
    agree(run("rsi:5")["value"], ref_rsi(c, 5))
    line, sig, hist = ref_macd(c, 12, 26, 9)
    r = run("macd")
    agree(r["macd"], line)
    agree(r["signal"], sig)
    agree(r["hist"], hist)
    basis, upper, lower = ref_bb(c, 20, 2.0)
    r = run("bb:20:2")
    agree(r["basis"], basis)
    agree(r["upper"], upper)
    agree(r["lower"], lower)
    kk, dd = ref_stoch(h, lo, c, 14, 3, 3)
    r = run("stoch")
    agree(r["k"], kk)
    agree(r["d"], dd)
    agree(run("atr:14")["value"], ref_rma(ref_tr(h, lo, c), 14))
    adx, plus, minus = ref_adx(h, lo, c, 14, 14)
    r = run("adx")
    agree(r["adx"], adx)
    agree(r["plus"], plus)
    agree(r["minus"], minus)
    agree(run("cci:20")["value"], ref_cci(h, lo, c, 20))
    agree(run("willr:14")["value"], ref_willr(h, lo, c, 14))
    agree(run("obv")["value"], ref_obv(c, v))
    agree(run("psar")["value"], ref_psar(h, lo, c, 0.02, 0.02, 0.2))
    agree(run("psar:0.03:0.05:0.3")["value"], ref_psar(h, lo, c, 0.03, 0.05, 0.3))
    up, down = ref_supertrend(h, lo, c, 10, 3.0)
    r = run("supertrend")
    agree(r["up"], up)
    agree(r["down"], down)
    up, down = ref_supertrend(h, lo, c, 4, 1.5)
    r = run("supertrend:4:1.5")
    agree(r["up"], up)
    agree(r["down"], down)


def test_the_parameter_table_is_pinned():
    """Defaults and limits are part of the contract with the UI; a silent change must fail."""
    want = {
        "sma": [("length", 20, 1, 500, True)],
        "ema": [("length", 20, 1, 500, True)],
        "wma": [("length", 20, 1, 500, True)],
        "bb": [("length", 20, 1, 500, True), ("mult", 2, "0.1", 10, False)],
        "supertrend": [("length", 10, 1, 200, True), ("mult", 3, "0.1", 20, False)],
        "psar": [
            ("start", "0.02", "0.001", 1, False),
            ("inc", "0.02", "0.001", 1, False),
            ("max", "0.2", "0.01", 1, False),
        ],
        "rsi": [("length", 14, 1, 200, True)],
        "macd": [
            ("fast", 12, 1, 200, True),
            ("slow", 26, 1, 400, True),
            ("signal", 9, 1, 200, True),
        ],
        "stoch": [("k", 14, 1, 200, True), ("d", 3, 1, 50, True), ("smooth", 3, 1, 50, True)],
        "atr": [("length", 14, 1, 200, True)],
        "adx": [("length", 14, 1, 200, True), ("smooth", 14, 1, 200, True)],
        "cci": [("length", 20, 1, 300, True)],
        "willr": [("length", 14, 1, 200, True)],
        "obv": [],
    }
    for name, params in want.items():
        got = [(p.key, p.default, p.lo, p.hi, p.integer) for p in CATALOG[name].params]
        assert got == [(k, D(str(a)), D(str(b)), D(str(c_)), i) for k, a, b, c_, i in params], name
    assert {n: (i.pane, i.group) for n, i in CATALOG.items()} == {
        "sma": ("overlay", "Trend"),
        "ema": ("overlay", "Trend"),
        "wma": ("overlay", "Trend"),
        "bb": ("overlay", "Volatility"),
        "supertrend": ("overlay", "Trend"),
        "psar": ("overlay", "Trend"),
        "rsi": ("pane", "Momentum"),
        "macd": ("pane", "Momentum"),
        "stoch": ("pane", "Momentum"),
        "atr": ("pane", "Volatility"),
        "adx": ("pane", "Trend"),
        "cci": ("pane", "Momentum"),
        "willr": ("pane", "Momentum"),
        "obv": ("pane", "Volume"),
    }
    assert [(o.key, o.kind) for o in CATALOG["macd"].outputs] == [
        ("hist", "histogram"),
        ("macd", "line"),
        ("signal", "line"),
    ]
    assert [(o.key, o.kind) for o in CATALOG["psar"].outputs] == [("value", "dots")]
    assert CATALOG["rsi"].levels == (D(30), D(70)) and CATALOG["stoch"].levels == (D(20), D(80))
