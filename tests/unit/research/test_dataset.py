import copy

from algo.research.dataset import Dataset

BASE = {
    "price_source": "kite",
    "publish_lag_seconds": 0,
    "known_at": "2026-11-14T10:00:00+00:00",
    "freeze": {"id": "f1", "through": "2026-11-13", "items_sha256": "aaa"},
    "data_hash": "bbb",
    "universe": {"spec": {"segments": ["large"]}, "membership_sha256": "ccc", "instruments": 335},
    "window": {"start": "2019-10-01", "end": "2024-12-31"},
    "cost_schedules": [{"schedule_id": 1, "version": 3, "status": "verified"}],
}


def changed(path, value):
    m = copy.deepcopy(BASE)
    node = m
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = value
    return Dataset(m)


def test_the_dataset_hash_is_stable_and_changes_with_every_input():
    base = Dataset(copy.deepcopy(BASE)).sha256
    assert base == Dataset(copy.deepcopy(BASE)).sha256
    assert base == Dataset(dict(reversed(list(BASE.items())))).sha256  # key order does not matter
    for path, value in [
        (("price_source",), "bhavcopy"),
        (("publish_lag_seconds",), 5),
        (("known_at",), "2026-11-14T10:00:01+00:00"),
        (("freeze", "id"), "f2"),
        (("freeze", "items_sha256"), "zzz"),
        (("data_hash",), "other"),
        (("universe", "membership_sha256"), "other"),
        (("universe", "spec"), {"segments": ["mid"]}),
        (("window", "end"), "2024-12-30"),
        (("cost_schedules",), [{"schedule_id": 1, "version": 4, "status": "verified"}]),
    ]:
        assert changed(path, value).sha256 != base, path
