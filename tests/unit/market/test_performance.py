from datetime import date, timedelta

from algo.market.performance import by_zone, gift_buckets

D0 = date(2026, 1, 1)


def day(i):
    return D0 + timedelta(days=i)


def test_each_scored_day_is_put_in_its_zone_and_its_forward_return_averaged():
    closes = [(day(i), 100.0 * (1.01**i)) for i in range(80)]  # a steady 1% a day
    scores = [(day(0), 10.0), (day(1), 40.0), (day(2), 60.0), (day(3), 90.0), (day(4), 90.0)]
    rows = {r["zone"]: r for r in by_zone(scores, closes)}
    assert [rows[z]["days"] for z in ("Extreme fear", "Fear", "Greed", "Extreme greed")] == [
        1,
        1,
        1,
        2,
    ]
    f5 = rows["Extreme fear"]["forward"][0]
    assert (
        f5["horizon"] == 5
        and round(f5["avg_pct"], 3) == round(100 * (1.01**5 - 1), 3)
        and f5["up_pct"] == 100.0
    )
    assert rows["All days"]["days"] == 80


def test_a_horizon_beyond_the_data_is_none_and_nothing_scored_is_empty():
    closes = [(day(i), 100.0 + i) for i in range(10)]
    row = by_zone([(day(0), 10.0)], closes)[0]
    assert row["forward"][2] == {"horizon": 60, "avg_pct": None, "up_pct": None}
    assert by_zone([], closes) == [] and by_zone([(day(0), 10.0)], []) == []


def test_falling_days_are_not_counted_as_up():
    closes = [(day(i), 100.0 - i) for i in range(30)]
    assert by_zone([(day(0), 80.0)], closes)[3]["forward"][0]["up_pct"] == 0.0


def test_gift_indications_are_bucketed_with_how_often_the_day_closed_higher():
    rows = {
        r["label"]: r
        for r in gift_buckets([(0.5, 0.8), (0.4, -0.2), (0.1, 0.1), (-0.5, -1.0), (0.0, 0.3)])
    }
    assert (
        rows["Up more than 0.3%"]["days"] == 2
        and rows["Up more than 0.3%"]["up_pct"] == 50.0
        and round(rows["Up more than 0.3%"]["avg_pct"], 2) == 0.3
    )
    assert rows["Up up to 0.3%"]["days"] == 2  # +0.1 and exactly 0.0, which counts as up
    assert rows["Down more than 0.3%"]["up_pct"] == 0.0
    assert rows["Down up to 0.3%"] == {
        "label": "Down up to 0.3%",
        "days": 0,
        "up_pct": None,
        "avg_pct": None,
    }
