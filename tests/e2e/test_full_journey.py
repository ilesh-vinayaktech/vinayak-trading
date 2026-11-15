# ruff: noqa: E501
"""TODO 5.8: the whole path on one synthetic market, from RAW files to decisions. ENGINEERING_TEST_ONLY: synthetic prices.

Raw bhavcopy text for every session -> the real provider and pipeline into the lake and `bar_1d` -> the completeness check -> a backtest of the
trend-pullback strategy -> the paper runner on the same stored bars. The final assertion is the one that matters: the backtest and the paper path
decide the same thing, and everything on the way left its evidence (raw files, partition loads)."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

import pytest

from algo.backtest.engine import BacktestConfig, run_backtest
from algo.core.calendar import nse
from algo.data.lake import LocalLake
from algo.data.pipeline import run_partition
from algo.data.providers.nse_bhavcopy import NseBhavcopy
from algo.data.quality.completeness import check
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate
from algo.data.universe import Interval
from algo.paper.runner import run_day
from algo.strategies.nifty200_momentum import IntervalMembership
from algo.strategies.trend_pullback import TrendPullback, TrendPullbackParams
from tests.integration.paper.test_runner import DAY, NOW, PARAMS, orders, put_list, user
from tests.integration.test_trend_pullback_engine import DAYS, UP, falling, sawtooth
from tests.support.bt import ZERO

pytestmark = pytest.mark.e2e
HEADER = "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
CENT = Decimal("0.01")


def raw_files() -> dict[date, bytes]:
    """One bhavcopy text per session for twenty symbols, in the exchange's own column layout (prices to the paisa)."""
    paths = {f"S{k:02d}": (sawtooth(k) if k < UP else falling()) for k in range(20)}
    out = {}
    for d in DAYS:
        rows = []
        for sym, path in paths.items():
            p = path[d].quantize(CENT, rounding=ROUND_HALF_EVEN)
            rows.append(
                f"{sym}, EQ, {d:%d-%b-%Y}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 10000000, 1.00, 1000, 5000000, 50.00"
            )
        out[d] = (HEADER + "\n".join(rows) + "\n").encode()
    return out


def test_raw_files_become_bars_pass_the_quality_checks_and_the_backtest_and_the_paper_path_decide_alike(
    conn, tmp_path
):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    ids = []
    for k in range(20):
        iid = repo.add_instrument(x, f"S{k:02d}")
        repo.add_alias(iid, "nse", f"S{k:02d}", date(2000, 1, 1))
        ids.append(iid)
    files = raw_files()
    provider = NseBhavcopy(
        lambda url: files[
            datetime.strptime(url.rsplit("_", 1)[1][:8], "%d%m%Y").replace(tzinfo=UTC).date()
        ],
        nse(),
    )
    lake = LocalLake(tmp_path / "lake")
    loaded_at = datetime.combine(DAYS[-1], datetime.min.time(), UTC) + timedelta(days=2)

    # ---- raw -> lake -> bars
    results = [run_partition(conn, lake, provider, "bhav", d, loaded_at) for d in DAYS]
    assert {r.status for r in results} == {"loaded"} and sum(r.rows for r in results) == 20 * len(
        DAYS
    )
    assert conn.execute("SELECT count(*) FROM bar_1d").fetchone() == (20 * len(DAYS),)
    assert conn.execute("SELECT count(*) FROM partition_load WHERE status='loaded'").fetchone() == (
        len(DAYS),
    )
    again = run_partition(conn, lake, provider, "bhav", DAYS[10], loaded_at)
    assert again.status == "noop"  # a rerun of a loaded day changes nothing

    # ---- data quality on what was loaded
    report = check(conn, DAYS[-30])
    assert (report.quarantined, report.missing_days, report.thin_days) == ([], [], [])

    # ---- the backtest on the stored bars, then the paper runner on the same bars
    put_list(tmp_path, DAY - timedelta(days=5))
    members = IntervalMembership([Interval(i, date(2000, 1, 1), None) for i in ids])
    strategy = TrendPullback(TrendPullbackParams(**PARAMS), members)
    cfg = BacktestConfig(
        start=DAY, end=DAYS[DAYS.index(DAY) + 1], initial_cash=Decimal(1_000_000), cost=ZERO
    )
    engine = {
        (t.instrument_id, t.side)
        for t in run_backtest(conn, strategy, cfg).trades
        if t.day == cfg.end
    }
    uid = user(conn)
    out = run_day(conn, uid, day=DAY, now=NOW, lake_root=tmp_path)
    paper = {(r[0], r[1]) for r in orders(conn, uid)}
    assert out.status == "PROPOSED" and paper, "the scenario must produce a decision to compare"
    assert engine == paper
