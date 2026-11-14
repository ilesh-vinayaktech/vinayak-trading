from datetime import date

from algo.data.universe import Interval
from algo.sandbox.adapters import membership, membership_spec, restore_audit
from algo.sandbox.protocol import dumps, loads
from algo.strategies.nifty200_momentum import IntervalMembership

D1, D2, D3 = date(2026, 1, 1), date(2026, 6, 1), date(2026, 9, 1)


def test_a_membership_survives_the_trip_to_the_worker_and_answers_the_same():
    original = IntervalMembership(
        [Interval(1, D1, None), Interval(2, D1, D2), Interval(3, D2, D3)], {D2: "evidence missing"}
    )
    travelled = membership(loads(dumps(membership_spec(original))))
    for day in (date(2025, 12, 31), D1, date(2026, 3, 1), D2, D3, date(2026, 12, 1)):
        assert travelled.on(day) == original.on(day) and travelled.unusable_reason(
            day
        ) == original.unusable_reason(day)
    assert travelled.ever() == original.ever() == [1, 2, 3] and travelled.first_day() == D1


def test_an_empty_membership_travels_too():
    empty = membership(loads(dumps(membership_spec(IntervalMembership([])))))
    assert empty.ever() == [] and empty.first_day() is None


def test_audit_rows_get_their_integer_keys_back_after_json():
    row = {"day": "2026-11-12", "exits": {7: "over_limit", 9: "trend"}, "entries": [3], "n": 2}
    back = restore_audit(loads(dumps(row)))
    assert back == row and all(isinstance(k, int) for k in back["exits"])
    assert restore_audit({"skipped": "strict"}) == {
        "skipped": "strict"
    }  # a row without exits is left alone
