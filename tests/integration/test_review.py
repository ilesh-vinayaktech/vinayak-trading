import json
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from algo.data.adjust.factors import build_adjustments
from algo.data.corporate_actions import _replace, knowledge_time_for, records_for
from algo.data.quality.continuity import continuity_issues
from algo.data.reader import BarReader, UnadjustableError
from algo.data.review import (
    ResolveError,
    evidence_class,
    resolve,
    review_queue,
    stale_resolutions,
    verify,
)
from algo.data.store.instruments import InstrumentRepo
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 7, tzinfo=UTC)
INGESTED = datetime(2026, 11, 6, tzinfo=UTC)
DAYS = [
    date(2025, 6, 9),
    date(2025, 6, 10),
    date(2025, 6, 11),
    date(2025, 6, 12),
    date(2025, 6, 13),
]
EX = DAYS[3]
CLOSES = [D(1000), D(1010), D(1020), D(918), D(920)]  # demerger on 12 Jun: ~10% drop


def ts(d):
    return datetime(d.year, d.month, d.day, 3, 45, tzinfo=UTC)


def add_review(conn, iid, ex, kind, subject="Demerger", reason="no ratio/price in feed"):
    conn.execute(
        "INSERT INTO corporate_action (instrument_id,ex_date,kind,status,reason,subject,"
        "knowledge_time,knowledge_time_source,source,raw_checksum,ingested_at) "
        "VALUES (%s,%s,%s,'review',%s,%s,%s,'ex_date_proxy','nse','x',%s)",
        (iid, ex, kind, reason, subject, knowledge_time_for(ex), INGESTED),
    )


@pytest.fixture
def env(conn):
    migrate(conn)
    repo = InstrumentRepo(conn)
    x = repo.add_exchange("XNSE", "IN", "Asia/Kolkata", "INR", "NSE")
    iid = repo.add_instrument(x, "XYZ")
    repo.add_alias(iid, "nse", "XYZ", date(2000, 1, 1))
    for d, c in zip(DAYS, CLOSES, strict=True):
        conn.execute(
            "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,"
            "dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,100,'nse',1,%s)",
            (iid, ts(d), c, c, c, c, INGESTED),
        )
    add_review(conn, iid, EX, "demerger")
    return conn, iid


def do_resolve(conn, **kw):
    base = dict(symbol="XYZ", ex_date=EX, kind="demerger", note="n", by="tester", now=NOW)
    return resolve(conn, **{**base, **kw})


def demerger(conn, price=D(102)):
    return do_resolve(
        conn, method="demerger", params={"child_per_parent": D(1), "child_price": price}
    )


def test_queue_shows_the_item_with_price_context(env):
    conn, _ = env
    (it,) = review_queue(conn)
    assert (it.symbol, it.ex_date, it.kind, it.subjects) == ("XYZ", EX, "demerger", ["Demerger"])
    assert (it.prev_close, it.ex_close) == (D(1020), D(918)) and it.observed_ratio == D("0.9")
    assert it.resolution is None


def test_queue_filters_and_hides_resolved_unless_asked(env):
    conn, iid = env
    add_review(conn, iid, DAYS[1], "buy", "Buy Back")
    assert {i.kind for i in review_queue(conn)} == {"demerger", "buy"}
    assert [i.kind for i in review_queue(conn, kinds=["buy"])] == ["buy"]
    assert review_queue(conn, symbols=["NOPE"]) == []
    do_resolve(conn, method="ignore", kind="buy", ex_date=DAYS[1])
    assert [i.kind for i in review_queue(conn)] == ["demerger"]
    both = review_queue(conn, include_resolved=True)
    assert next(i for i in both if i.kind == "buy").resolution.treatment == "ignore"


def test_queue_context_is_none_when_there_are_no_bars(env):
    conn, iid = env
    add_review(conn, iid, date(2025, 1, 1), "demerger")  # before the first bar
    item = next(i for i in review_queue(conn) if i.ex_date == date(2025, 1, 1))
    assert item.prev_close is None and item.observed_ratio is None


def test_demerger_adjusts_prices_but_not_volume_and_clears_the_warning(env):
    conn, iid = env
    r = demerger(conn)
    assert r.factor == D("0.9") and r.warning is None
    h = BarReader(conn).history(iid, DAYS[0], DAYS[4], adjust="split")
    assert [b.close for b in h.bars] == [D(900), D(909), D(918), D(918), D(920)]
    assert [b.volume for b in h.bars] == [D(100)] * 5  # a demerger does not change share count
    assert h.unapplied == []
    raw = [(d, c) for d, c in zip(DAYS, CLOSES, strict=True)]
    adj = build_adjustments(records_for(conn, iid), lambda d: D(1)).adjustments
    assert continuity_issues(raw, adj) == []  # the ex-date move is now explained


def test_rights_uses_the_theoretical_ex_rights_price(env):
    conn, iid = env
    add_review(conn, iid, DAYS[1], "rights", "Rights 1:15 @ Premium Rs 748/-")
    r = do_resolve(conn, kind="rights", ex_date=DAYS[1], method="rights",
                   params={"new": D(1), "held": D(15), "subscription_price": D(800)})  # fmt: skip
    assert r.factor == D("0.9875")  # prev close 1000: (15*1000 + 800) / 16 / 1000


def test_ignore_means_no_adjustment_and_no_warning(env):
    conn, iid = env
    add_review(conn, iid, DAYS[1], "buy", "Buy Back")
    do_resolve(conn, kind="buy", ex_date=DAYS[1], method="ignore")
    h = BarReader(conn).history(iid, DAYS[0], DAYS[1], adjust="split")
    assert [b.close for b in h.bars] == [D(1000), D(1010)]
    assert [u.kind for u in h.unapplied] == ["demerger"]  # only the still-unresolved item remains


def test_direct_factor_far_from_the_observed_move_warns_but_is_stored(env):
    conn, _ = env
    r = do_resolve(conn, method="direct", params={"factor": D("0.5")})
    assert r.factor == D("0.5") and "observed" in r.warning
    assert do_resolve(conn, method="direct", params={"factor": D("0.9")}).warning is None


def test_latest_resolution_wins_and_history_is_kept(env):
    conn, iid = env
    demerger(conn, D(102))
    demerger(conn, D(204))  # corrected input: child worth 204 => factor 0.8
    h = BarReader(conn).history(iid, DAYS[0], DAYS[0], adjust="split")
    assert h.bars[0].close == D(800)
    n = conn.execute("SELECT count(*) FROM action_resolution").fetchone()[0]
    assert n == 2


SRC = dict(source_type="company_filing", source_url="https://example.org/scheme.pdf")


def do_verify(conn, **kw):
    base = dict(symbol="XYZ", ex_date=EX, kind="demerger", by="owner", now=NOW, **SRC)
    return verify(conn, **{**base, **kw})


def test_provisional_is_applied_in_research_but_listed_and_refused_in_strict(env):
    conn, iid = env
    demerger(conn)  # provisional by default
    rd = BarReader(conn)
    h = rd.history(iid, DAYS[0], DAYS[4], adjust="split")
    assert h.bars[0].close == D(900)  # research mode applies it ...
    assert [p.kind for p in h.provisional] == ["resolved"] and not h.clean  # ... visibly
    with pytest.raises(UnadjustableError, match="demerger"):
        rd.history(iid, DAYS[0], DAYS[4], adjust="split", strict=True)


def test_verified_factor_is_applied_in_strict_mode_and_the_history_is_clean(env):
    conn, iid = env
    demerger(conn)
    do_verify(conn)
    h = BarReader(conn).history(iid, DAYS[0], DAYS[4], adjust="split", strict=True)
    assert h.bars[0].close == D(900) and h.unapplied == [] and h.provisional == [] and h.clean


def test_verify_appends_an_audit_row_and_a_new_resolution_must_be_verified_again(env):
    conn, iid = env
    demerger(conn)
    do_verify(conn)
    assert conn.execute("SELECT count(*) FROM action_resolution").fetchone()[0] == 2
    row = conn.execute(
        "SELECT status, source_type, source_url, confirmed_by FROM action_resolution "
        "ORDER BY id DESC"
    ).fetchone()
    assert row == ("verified", "company_filing", "https://example.org/scheme.pdf", "owner")
    demerger(conn, D(204))  # changed after verification => provisional again
    with pytest.raises(UnadjustableError):
        BarReader(conn).history(iid, DAYS[0], DAYS[4], adjust="split", strict=True)


def test_gap_estimates_can_never_be_verified(env):
    conn, iid = env
    add_peers(conn)
    do_resolve(conn, method="gap", min_peers=3)
    with pytest.raises(ResolveError, match="gap"):
        do_verify(conn)
    with pytest.raises(ResolveError, match="gap"):
        do_resolve(conn, method="gap", min_peers=3, status="verified", **SRC)


@pytest.mark.parametrize("missing", ["source_type", "source_url"])
def test_verification_needs_evidence(env, missing):
    conn, _ = env
    demerger(conn)
    with pytest.raises(ResolveError, match="source"):
        do_verify(conn, **{missing: None})
    assert conn.execute("SELECT count(*) FROM action_resolution").fetchone()[0] == 1


def test_resolving_directly_as_verified_needs_evidence_and_records_who(env):
    conn, iid = env
    with pytest.raises(ResolveError, match="source"):
        do_resolve(conn, method="direct", params={"factor": D("0.9")}, status="verified")
    do_resolve(conn, method="direct", params={"factor": D("0.9")}, status="verified", **SRC)
    h = BarReader(conn).history(iid, DAYS[0], DAYS[0], adjust="split", strict=True)
    assert h.bars[0].close == D(900) and h.clean


def test_cost_allocation_method_uses_the_official_parent_share(env):
    conn, iid = env
    r = do_resolve(conn, method="cost_allocation", params={"parent_share": D("0.957")},
                   status="verified", **SRC)  # fmt: skip
    assert r.factor == D("0.957")
    for bad in (D(0), D("1.2")):
        with pytest.raises(ResolveError, match="parent_share"):
            do_resolve(conn, method="cost_allocation", params={"parent_share": bad})


def test_documented_exclusions_are_not_applied_and_do_not_block_strict(env):
    conn, iid = env
    do_resolve(conn, method="ignore", status="ignored_with_reason")
    h = BarReader(conn).history(iid, DAYS[0], DAYS[4], adjust="split", strict=True)
    assert h.bars[0].close == D(1000) and h.unapplied == [] and h.clean  # decided: no adjustment


def test_no_adjustment_verified_needs_evidence_and_rejected_is_allowed(env):
    conn, iid = env
    with pytest.raises(ResolveError, match="source"):
        do_resolve(conn, method="ignore", status="no_adjustment_verified")
    do_resolve(conn, method="ignore", status="no_adjustment_verified", **SRC)
    do_resolve(conn, method="ignore", status="rejected")  # event was a mis-detection
    assert BarReader(conn).history(iid, DAYS[0], DAYS[4], adjust="split", strict=True).clean


@pytest.mark.parametrize(
    ("kw", "msg"),
    [
        (dict(method="ignore", status="verified"), "status"),  # verified needs a factor
        (dict(method="direct", params={"factor": D("0.9")}, status="rejected"), "status"),
        (dict(method="direct", params={"factor": D("0.9")}, status="made_up"), "status"),
    ],
)
def test_status_must_match_the_treatment(env, kw, msg):
    conn, _ = env
    with pytest.raises(ResolveError, match=msg):
        do_resolve(conn, **kw, **SRC)


def test_database_itself_refuses_a_verified_row_without_evidence(env):
    import psycopg

    conn, iid = env
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO action_resolution (instrument_id,ex_date,kind,treatment,factor,method,"
            "note,resolved_by,resolved_at,status) VALUES (%s,%s,'demerger','factor',0.9,'direct',"
            "'n','x',%s,'verified')",
            (iid, EX, NOW),
        )


def test_adjustment_version_is_stable_and_changes_when_any_input_changes(env):
    conn, iid = env
    rd = BarReader(conn)
    v_none = rd.history(iid, DAYS[0], DAYS[4], adjust="split").adjustment_version
    demerger(conn)
    v1 = rd.history(iid, DAYS[0], DAYS[4], adjust="split").adjustment_version
    assert v1 == rd.history(iid, DAYS[0], DAYS[4], adjust="split").adjustment_version  # stable
    assert v1 != v_none
    demerger(conn, D(204))
    assert rd.history(iid, DAYS[0], DAYS[4], adjust="split").adjustment_version != v1
    do_verify(conn)
    v_verified = rd.history(iid, DAYS[0], DAYS[4], adjust="split").adjustment_version
    assert v_verified != v1  # provisional -> verified is a different dataset version
    assert rd.history(iid, DAYS[0], DAYS[4], adjust="total_return").adjustment_version != v_verified


def test_resolution_survives_a_rebuild_of_the_derived_table(env):
    """corporate_action is rebuilt from raw NSE JSON on every re-ingest / re-parse."""
    conn, iid = env
    demerger(conn)
    row = {"symbol": "XYZ", "series": "EQ", "subject": "Demerger", "exDate": "12-Jun-2025"}
    raw = json.dumps([{**row, "recDate": "12-Jun-2025", "isin": "INE000A01010"}]).encode()
    res = _replace(conn, iid, raw, "sum", NOW)
    assert res.replaced == 1 and res.inserted == 1  # old derived row deleted, new one inserted
    h = BarReader(conn).history(iid, DAYS[0], DAYS[0], adjust="split")
    assert h.bars[0].close == D(900) and h.unapplied == []


def test_stale_resolution_is_reported_when_the_parser_later_prices_the_action(env):
    conn, iid = env
    demerger(conn)
    assert stale_resolutions(conn) == []
    conn.execute("UPDATE corporate_action SET status='ok', kind='split', num=2, den=1")
    stale = stale_resolutions(conn)
    assert [(s.symbol, s.ex_date, s.kind) for s in stale] == [("XYZ", EX, "demerger")]


@pytest.mark.parametrize(
    ("kw", "msg"),
    [
        (dict(symbol="NOPE", method="ignore"), "unknown symbol"),
        (dict(kind="rights", method="ignore"), "no review action"),
        (dict(ex_date=date(2024, 1, 1), method="ignore"), "no review action"),
        (dict(method="magic"), "unknown method"),
        (dict(method="demerger", params={"child_price": D(1)}), "child_per_parent"),
        (dict(method="rights", params={"new": D(1)}), "held"),
        (dict(method="direct", params={}), "factor"),
        (dict(method="direct", params={"factor": D(0)}), "positive"),
        (
            dict(method="demerger", params={"child_per_parent": D(1), "child_price": D(99999)}),
            "below",
        ),
    ],
)
def test_bad_requests_are_rejected_with_a_clear_message(env, kw, msg):
    conn, _ = env
    with pytest.raises(ResolveError, match=msg):
        do_resolve(conn, **kw)
    assert conn.execute("SELECT count(*) FROM action_resolution").fetchone()[0] == 0


def test_demerger_with_no_bar_before_the_ex_date_cannot_be_priced(env):
    conn, iid = env
    add_review(conn, iid, date(2025, 1, 1), "demerger")
    with pytest.raises(ResolveError, match="no bar before"):
        do_resolve(conn, ex_date=date(2025, 1, 1), method="demerger",
                   params={"child_per_parent": D(1), "child_price": D(10)})  # fmt: skip


def test_verify_needs_a_provisional_resolution_to_promote(env):
    conn, _ = env
    with pytest.raises(ResolveError, match="nothing to verify"):
        do_verify(conn)
    demerger(conn)
    do_verify(conn)
    with pytest.raises(ResolveError, match="nothing to verify"):
        do_verify(conn)  # already verified
    with pytest.raises(ResolveError, match="unknown symbol"):
        do_verify(conn, symbol="NOPE")


def test_ignored_with_reason_can_be_promoted_to_no_adjustment_verified(env):
    conn, _ = env
    do_resolve(conn, method="ignore", status="ignored_with_reason")
    do_verify(conn)
    st = conn.execute("SELECT status FROM action_resolution ORDER BY id DESC").fetchone()[0]
    assert st == "no_adjustment_verified"


def test_direct_factor_with_no_bars_around_the_ex_date_has_nothing_to_compare_so_no_warning(env):
    conn, iid = env
    add_review(conn, iid, date(2025, 1, 1), "demerger")  # before the first bar
    r = do_resolve(conn, ex_date=date(2025, 1, 1), method="direct", params={"factor": D("0.9")})
    assert r.factor == D("0.9") and r.warning is None


# ---- method "gap": observed ex-date move divided by the median move of Nifty 200 peers ---------
def add_peers(conn, n=3, up=D("1.01"), ex_action_for=None):
    repo = InstrumentRepo(conn)
    x = conn.execute("SELECT exchange_id FROM exchange").fetchone()[0]
    ids = []
    for i in range(n):
        pid = repo.add_instrument(x, f"PEER{i}")
        ids.append(pid)
        for d, c in ((DAYS[2], D(100)), (DAYS[3], D(100) * up)):
            conn.execute(
                "INSERT INTO bar_1d (instrument_id,ts,open,high,low,close,volume,source,"
                "dataset_version,ingested_at) VALUES (%s,%s,%s,%s,%s,%s,100,'nse',1,%s)",
                (pid, ts(d), c, c, c, c, INGESTED),
            )
        conn.execute("INSERT INTO index_snapshot VALUES ('NIFTY200', %s, %s)", (NOW.date(), pid))
    return ids


def test_gap_method_strips_the_market_move_from_the_observed_drop(env):
    conn, iid = env
    add_peers(conn)  # every peer +1% that day
    r = do_resolve(conn, method="gap", min_peers=3)
    assert r.factor == pytest.approx(D("0.9") / D("1.01"), rel=D("1e-12"))  # 918/1020 / 1.01
    assert "approximate" in r.warning
    inputs = conn.execute("SELECT inputs FROM action_resolution").fetchone()[0]
    assert inputs["peers"] == "3" and D(inputs["market_median"]) == D("1.01")


def test_gap_method_uses_the_median_so_one_wild_peer_does_not_matter(env):
    conn, iid = env
    ids = add_peers(conn, n=3)
    conn.execute(
        "UPDATE bar_1d SET close=1 WHERE instrument_id=%s AND ts=%s", (ids[0], ts(DAYS[3]))
    )
    r = do_resolve(conn, method="gap", min_peers=3)
    assert r.factor == pytest.approx(D("0.9") / D("1.01"), rel=D("1e-12"))


def test_gap_method_excludes_peers_with_their_own_action_that_day(env):
    conn, iid = env
    ids = add_peers(conn, n=4)
    conn.execute(
        "UPDATE bar_1d SET close=50 WHERE instrument_id=%s AND ts=%s", (ids[0], ts(DAYS[3]))
    )
    add_review(conn, ids[0], EX, "demerger")  # that peer has its own corporate action
    r = do_resolve(conn, method="gap", min_peers=3)
    assert r.factor == pytest.approx(D("0.9") / D("1.01"), rel=D("1e-12"))


def test_gap_method_needs_enough_peers_and_an_actual_price_drop(env):
    conn, iid = env
    add_peers(conn, n=2)
    with pytest.raises(ResolveError, match="peers"):
        do_resolve(conn, method="gap", min_peers=3)
    add_peers_more = add_peers(conn, n=1)  # 3 peers now
    assert add_peers_more
    conn.execute("UPDATE bar_1d SET close=1100 WHERE instrument_id=%s AND ts=%s", (iid, ts(EX)))
    with pytest.raises(ResolveError, match="drop"):
        do_resolve(conn, method="gap", min_peers=3)
    assert conn.execute("SELECT count(*) FROM action_resolution").fetchone()[0] == 0


def test_gap_method_without_bars_around_the_ex_date_cannot_be_priced(env):
    conn, iid = env
    add_review(conn, iid, date(2025, 1, 1), "demerger")
    with pytest.raises(ResolveError, match="no bar"):
        do_resolve(conn, ex_date=date(2025, 1, 1), method="gap")


# ---- exchange-determined adjusted base price (priority 1 evidence for demergers) -----------------
def test_exchange_adjusted_price_factor_is_base_price_over_previous_cum_close(env):
    conn, iid = env  # previous close (11 Jun) = 1020
    r = do_resolve(conn, method="exchange_adjusted_price", params={"base_price": D(918)},
                   status="verified", **SRC)  # fmt: skip
    assert r.factor == D("0.9")
    h = BarReader(conn).history(iid, DAYS[0], DAYS[4], adjust="split", strict=True)
    assert [b.close for b in h.bars][:3] == [D(900), D(909), D(918)] and h.clean
    inputs = conn.execute("SELECT inputs FROM action_resolution").fetchone()[0]
    assert inputs["base_price"] == "918" and inputs["prev_close"] == "1020"


@pytest.mark.parametrize("base", [D(0), D(-5), D(1020), D(1500)])
def test_exchange_adjusted_price_must_be_a_positive_price_below_the_cum_close(env, base):
    conn, _ = env
    with pytest.raises(
        ResolveError, match="^base_price must be positive and below the previous close$"
    ):
        do_resolve(conn, method="exchange_adjusted_price", params={"base_price": base})
    assert conn.execute("SELECT count(*) FROM action_resolution").fetchone()[0] == 0


def test_exchange_adjusted_price_needs_a_previous_close_and_its_parameter(env):
    conn, iid = env
    with pytest.raises(ResolveError, match="base_price"):
        do_resolve(conn, method="exchange_adjusted_price", params={})
    add_review(conn, iid, date(2025, 1, 1), "demerger")
    with pytest.raises(ResolveError, match="no bar before"):
        do_resolve(conn, ex_date=date(2025, 1, 1), method="exchange_adjusted_price",
                   params={"base_price": D(5)})  # fmt: skip


@pytest.mark.parametrize(
    ("status", "method", "expected"),
    [
        (None, None, "UNRESOLVED"),
        ("provisional", "gap", "PROVISIONAL_GAP_ESTIMATE"),
        ("provisional", "exchange_adjusted_price", "PROVISIONAL_EXCHANGE_DERIVED"),
        ("provisional", "rights", "PROVISIONAL_FROM_TERMS"),
        ("provisional", "direct", "PROVISIONAL_FROM_TERMS"),
        ("verified", "exchange_adjusted_price", "VERIFIED"),
        ("no_adjustment_verified", "ignore", "NO_ADJUSTMENT_VERIFIED"),
        ("ignored_with_reason", "ignore", "IGNORED_WITH_REASON"),
        ("rejected", "ignore", "REJECTED"),
    ],
)
def test_evidence_class_never_lets_a_gap_estimate_look_like_exchange_evidence(
    status, method, expected
):
    assert evidence_class(status, method) == expected
