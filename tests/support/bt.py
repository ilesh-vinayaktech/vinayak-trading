from datetime import UTC, date, datetime
from decimal import Decimal as D

from algo.backtest.costs.policy import CostModel
from algo.backtest.engine import BacktestConfig
from algo.data.corporate_actions import knowledge_time_for
from algo.data.review import resolve
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from tests.support.strategies import HoldParams, HoldWeights

DAYS = [date(2025, 6, d) for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]
ZERO = CostModel("zero", D(0), D(0), False)
REALISTIC = CostModel("realistic-test", D(0), D(1), False)  # no commission, 1 bps slippage
INGESTED = datetime(2026, 11, 6, tzinfo=UTC)
NOW = datetime(2026, 11, 7, tzinfo=UTC)


def cfg(**kw):
    base = dict(start=DAYS[0], end=DAYS[-1], initial_cash=D(10000), cost=ZERO)
    return BacktestConfig(**{**base, **kw})


def put_bars(conn, iid, prices, vol=10_000_000):
    """prices: {day: close} or {day: (open, close)}"""
    for d, p in prices.items():
        o, c = p if isinstance(p, tuple) else (p, p)
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,dataset_version,"
            "ingested_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'nse',1,%s)",
            (
                iid,
                datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC),
                o,
                max(o, c),
                min(o, c),
                c,
                vol,
                INGESTED,
            ),
        )


def flat(price, days=DAYS):
    return {d: D(price) for d in days}


def add_action(
    conn,
    iid,
    ex,
    kind,
    status="ok",
    num=None,
    den=None,
    amount=None,
    subject="t",
    ingested=INGESTED,
):
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,num,den,amount,reason,subject,"
        "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'r',%s,%s,'ex_date_proxy','nse','x',%s)",
        (iid, ex, kind, status, num, den, amount, subject, knowledge_time_for(ex), ingested),
    )


def make_env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = {}
    for sym in ("AAA", "BBB"):
        ids[sym] = repo.add_instrument(x, sym)
        repo.add_alias(ids[sym], "nse", sym, date(2000, 1, 1))
    return conn, ids["AAA"], ids["BBB"]


def hold(*pairs):
    return HoldWeights(
        HoldParams(ids=tuple(p[0] for p in pairs), weights=tuple(D(p[1]) for p in pairs))
    )


def provisional_demerger(conn, iid, ex):
    add_action(conn, iid, ex, "demerger", status="review", subject="Demerger")
    resolve(conn, symbol="AAA", ex_date=ex, kind="demerger", method="direct", params={"factor": D("0.9")},
            note="n", by="t", now=NOW)  # fmt: skip
