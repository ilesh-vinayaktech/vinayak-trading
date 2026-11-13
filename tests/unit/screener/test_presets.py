from algo.screener.engine import FIELDS, validate
from algo.screener.presets import BY_ID, PRESETS


def test_every_preset_is_valid_and_sorts_on_a_real_field():
    assert len(BY_ID) == len(PRESETS) >= 20
    for p in PRESETS:
        assert p.conditions and p.sort in FIELDS, p.id
        for c in p.conditions:
            validate(c)


def test_there_are_fundamental_technical_and_combined_screens():
    assert {p.category for p in PRESETS} == {"fundamental", "technical", "combined"}
    for p in PRESETS:
        kinds = {FIELDS[c.field].kind for c in p.conditions} - {"profile"}
        want = {
            "fundamental": {"fundamental"},
            "technical": {"technical"},
            "combined": {"fundamental", "technical"},
        }
        assert kinds == want[p.category] or p.id == "large-cap-value", p.id
