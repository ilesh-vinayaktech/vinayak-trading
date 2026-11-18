# ruff: noqa: E501
"""Scoring stored headlines with the Laya model: only unscored recent ones, results stored beside the keyword reading, a broken scorer refused, the real subprocess runner's failure modes."""

import stat
from datetime import UTC, datetime, timedelta

import pytest

from algo.data.news_laya import MAX_TEXT, LayaError, node_runner, reading, score_pending, text_of
from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)


def put(conn, item_id, title, age_h=1.0, summary="", laya=None):
    conn.execute(
        "INSERT INTO news_item (item_id, source, title, summary, url, published_at, first_seen_at, sentiment, hits, symbols, laya_sentiment) VALUES (%s,'feed',%s,%s,%s,%s,%s,0.5,1,'{}',%s)",
        (
            item_id,
            title,
            summary,
            f"https://ex.com/{item_id}",
            NOW - timedelta(hours=age_h),
            NOW,
            laya,
        ),
    )


@pytest.fixture
def db(conn):
    migrate(conn)
    return conn


class Fake:
    def __init__(self, reply=None):
        self.asked, self.reply = [], reply

    def __call__(self, items):
        self.asked.append(list(items))
        return (
            self.reply
            if self.reply is not None
            else [{"id": i["id"], "sentiment": 0.5, "confidence": 0.8} for i in items]
        )


def test_text_joins_title_and_summary_and_is_cut_to_a_size_the_model_can_take():
    assert text_of("Title", None) == "Title" and text_of("Title", "More") == "Title. More"
    assert len(text_of("T" * 300, "S" * 300)) == MAX_TEXT


def test_only_recent_unscored_headlines_are_scored_newest_first_and_stored_beside_the_keyword_reading(
    db,
):
    put(db, "new", "Fresh news", age_h=1)
    put(db, "mid", "Earlier news", age_h=5, summary="detail")
    put(db, "done", "Already scored", age_h=2, laya=0.1)
    put(db, "old", "Eight days old", age_h=24 * 8)
    run = Fake()
    assert score_pending(db, run, NOW) == 2
    assert [i["id"] for i in run.asked[0]] == ["new", "mid"] and run.asked[0][1][
        "text"
    ] == "Earlier news. detail"
    rows = db.execute(
        "SELECT item_id, sentiment, laya_sentiment, laya_confidence, laya_scored_at FROM news_item ORDER BY item_id"
    ).fetchall()
    assert rows == [
        ("done", 0.5, pytest.approx(0.1), None, None),
        ("mid", 0.5, 0.5, pytest.approx(0.8), NOW),
        ("new", 0.5, 0.5, pytest.approx(0.8), NOW),
        ("old", 0.5, None, None, None),
    ]
    assert score_pending(db, Fake(), NOW) == 0  # nothing left: the scorer is not even asked


def test_nothing_to_score_does_not_start_the_scorer(db):
    run = Fake()
    assert score_pending(db, run, NOW) == 0 and run.asked == []


def test_the_limit_caps_one_run(db):
    for k in range(5):
        put(db, f"i{k}", f"Headline {k}", age_h=k + 1)
    assert score_pending(db, Fake(), NOW, limit=2) == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "new", "sentiment": 2.0, "confidence": 0.5},  # outside -1..1
        {"id": "new", "sentiment": 0.1, "confidence": 1.5},  # not a probability
        {"id": "new", "sentiment": None, "confidence": 0.5},
        {"id": "nobody", "sentiment": 0.1, "confidence": 0.5},  # not one we asked about
        {"id": "new", "sentiment": 0.1},  # no confidence
    ],
)
def test_a_broken_scorer_is_refused(db, bad):
    put(db, "new", "Fresh news")
    with pytest.raises(LayaError):
        score_pending(db, Fake([bad]), NOW)


def fake_node(tmp_path, body):
    script = tmp_path / "fakenode"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_the_node_runner_passes_headlines_in_as_json_and_reads_the_scores_out(tmp_path):
    node = fake_node(
        tmp_path, 'cat > /dev/null\necho \'[{"id":"a","sentiment":-0.5,"confidence":0.9}]\'\n'
    )
    assert node_runner(tmp_path, node=node)([{"id": "a", "text": "x"}]) == [
        {"id": "a", "sentiment": -0.5, "confidence": 0.9}
    ]


def test_the_node_runner_reports_a_crash_bad_output_a_wrong_shape_a_missing_program_and_a_timeout(
    tmp_path,
):
    with pytest.raises(LayaError, match="exit 3.*boom"):
        node_runner(tmp_path, node=fake_node(tmp_path, "echo boom >&2\nexit 3\n"))([])
    with pytest.raises(LayaError, match="not JSON"):
        node_runner(tmp_path, node=fake_node(tmp_path, "echo not json\n"))([])
    with pytest.raises(LayaError, match="not return a list"):
        node_runner(tmp_path, node=fake_node(tmp_path, "echo '{\"a\": 1}'\n"))([])
    with pytest.raises(LayaError, match="could not run"):
        node_runner(tmp_path, node="/no/such/node")([])
    with pytest.raises(LayaError, match="could not run"):
        node_runner(tmp_path, timeout=0.2, node=fake_node(tmp_path, "sleep 5\n"))([])


def test_a_headlines_reading_is_laya_where_it_has_one_else_the_keyword_list_else_nothing():
    assert reading(0.5, -0.6) == (
        "negative",
        -0.6,
        "laya",
    )  # Laya wins even against a cheerful keyword reading
    assert reading(None, 0.1) == ("mixed", 0.1, "laya")  # inside Laya's band of 0.3
    assert reading(0.2, None) == ("positive", 0.2, "words")  # the word list's band is 0.15
    assert reading(-0.1, None) == ("mixed", -0.1, "words")
    assert reading(None, None) == (None, None, None)
    assert (
        reading(0.0, 0.3)[0] == "positive" and reading(0.0, -0.3)[0] == "negative"
    )  # the band's edge counts
