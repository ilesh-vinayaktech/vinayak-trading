# ruff: noqa: E501
import csv
from datetime import date

import pytest

from algo.data.membership_load import BASELINE, load_reconstruction
from algo.data.universe import UniverseError, intervals
from tests.support.bt import NOW, make_env

pytestmark = pytest.mark.integration
D = date
IV = [
    "entity",
    "symbol",
    "instrument_id",
    "tradable",
    "kind",
    "start",
    "end_exclusive",
    "start_basis",
]
EV = [
    "effective_from",
    "entity",
    "symbol",
    "event_type",
    "announcement_date",
    "tradable",
    "source_docs",
    "source_hashes",
]


def write(path, header, rows):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def doc(conn, doc_id):
    conn.execute(
        "INSERT INTO index_release_document (doc_id,parser_version,announced,source_url,source_hash,kind,sections,notes,parsed_at,classification)"
        " VALUES (%s,1,'2019-01-01','https://x/'||%s,'h','K','[]','[]',now(),'PARSED')",
        (doc_id, doc_id),
    )


@pytest.fixture
def world(conn, tmp_path):
    _, a, b = make_env(conn)
    doc(conn, "rel1")
    write(tmp_path / "membership_intervals.csv", IV, [
        [f"i:{a}", "AAA", a, "True", "INSTRUMENT", "2018-04-02", "2019-03-29", "WINDOW_START_BACKWARD_WALK"],
        [f"i:{b}", "BBB", b, "True", "INSTRUMENT", "2019-03-29", "", "EVENT"],
        ["p:DUMMYX", "DUMMYX", "", "False", "PLACEHOLDER", "2019-03-29", "", "EVENT"],
        ["s:ZZZ", "ZZZ", "", "False", "UNMAPPED_SYMBOL", "2019-03-29", "", "EVENT"],
    ])  # fmt: skip
    write(tmp_path / "membership_events.csv", EV, [
        ["2019-03-29", f"i:{a}", "AAA", "REMOVE", "2019-02-20", "True", "rel1", "dochash"],
        ["2019-03-29", f"i:{b}", "BBB", "ADD", "2019-02-20", "True", "rel1", "dochash"],
        ["2019-03-29", "p:DUMMYX", "DUMMYX", "ADD", "2019-02-20", "False", "rel1", "dochash"],
    ])  # fmt: skip
    return conn, a, b, tmp_path


def run(conn, d):
    return load_reconstruction(conn, directory=d, index_id="NIFTY200", covered_from=D(2018, 4, 2),
                               covered_until=D(2026, 11, 7), basis="test reconstruction", now=NOW)  # fmt: skip


def test_instrument_intervals_become_provisional_events_with_their_release_source(world):
    conn, a, b, d = world
    r = run(conn, d)
    assert (r.added, r.existing) == (
        3,
        0,
    )  # AAA add (window start) and remove, BBB add; the placeholder and unmapped symbol are skipped
    rows = conn.execute(
        "SELECT instrument_id, event_type, announcement_date, effective_from, source_url, source_hash, verified_status"
        " FROM index_membership_event ORDER BY instrument_id, effective_from"
    ).fetchall()
    assert rows[1] == (
        a,
        "REMOVE",
        D(2019, 2, 20),
        D(2019, 3, 29),
        "https://x/rel1",
        "dochash",
        "PROVISIONAL",
    )
    assert rows[0][4].startswith(BASELINE) and rows[0][2] == D(
        2018, 4, 2
    )  # window start: no release, announced on its own day
    assert [(i.instrument_id, i.start, i.end) for i in intervals(conn, "NIFTY200", strict=False)] == [
        (a, D(2018, 4, 2), D(2019, 3, 29)), (b, D(2019, 3, 29), None),
    ]  # fmt: skip


def test_coverage_is_declared_provisional_and_loading_twice_changes_nothing(world):
    conn, _, _, d = world
    first = run(conn, d)
    again = run(conn, d)
    assert (
        again.added == 0
        and again.existing == first.added
        and again.coverage_id == first.coverage_id
    )
    assert conn.execute(
        "SELECT verified_status, covered_from, covered_until FROM index_membership_coverage"
    ).fetchall() == [("PROVISIONAL", D(2018, 4, 2), D(2026, 11, 7))]
    assert conn.execute(
        "SELECT count(*) FROM index_membership_event WHERE verified_status<>'PROVISIONAL'"
    ).fetchone() == (0,)


def test_an_event_citing_an_unknown_document_is_refused(world):
    conn, _, _, d = world
    conn.execute("DELETE FROM index_release_document")
    with pytest.raises(UniverseError, match="not in index_release_document"):
        run(conn, d)


def test_a_tradable_event_no_interval_explains_is_refused(world):
    conn, a, _, d = world
    with (d / "membership_events.csv").open("a", newline="") as f:
        csv.writer(f).writerow(
            ["2020-01-01", f"i:{a}", "AAA", "ADD", "2019-12-01", "True", "rel1", "dochash"]
        )
    with pytest.raises(UniverseError, match="match no interval boundary"):
        run(conn, d)


def test_a_release_event_naming_another_instrument_of_the_same_symbol_still_lands_on_the_listed_one(
    world,
):
    conn, a, b, d = world
    text = (
        (d / "membership_events.csv").read_text().replace(f"i:{b},BBB,ADD", f"i:{a},BBB,ADD")
    )  # event entity differs, symbol and date agree
    (d / "membership_events.csv").write_text(text)
    run(conn, d)
    assert conn.execute(
        "SELECT announcement_date FROM index_membership_event WHERE instrument_id=%s", (b,)
    ).fetchone() == (D(2019, 2, 20),)


def test_an_event_announced_after_its_effective_date_is_stored_effective_on_the_announcement_day(
    world,
):
    conn, a, b, d = world
    text = (
        (d / "membership_events.csv")
        .read_text()
        .replace(
            "2019-02-20,True,rel1,dochash\n2019-03-29,p:",
            "2019-04-05,True,rel1,dochash\n2019-03-29,p:",
            1,
        )
    )
    (d / "membership_events.csv").write_text(
        text.replace(f"2019-03-29,i:{b},BBB,ADD,2019-02-20", f"2019-03-29,i:{b},BBB,ADD,2019-04-05")
    )
    r = run(conn, d)
    assert r.clamped == 1
    assert conn.execute(
        "SELECT effective_from FROM index_membership_event WHERE instrument_id=%s", (b,)
    ).fetchone() == (D(2019, 4, 5),)
    assert run(conn, d).added == 0  # idempotent with the clamped date too
