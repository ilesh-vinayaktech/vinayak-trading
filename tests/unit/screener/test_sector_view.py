from decimal import Decimal as D

from algo.screener import engine
from algo.screener.snapshot import add_sector_view


def rows():
    return [
        {"instrument_id": 1, "pe": D(10)},
        {"instrument_id": 2, "pe": D(20)},
        {"instrument_id": 3, "pe": D(30)},
        {"instrument_id": 4, "pe": D(40)},
        {"instrument_id": 5, "pe": D(5)},  # alone in its sector
        {"instrument_id": 6},  # no pe at all
    ]


SECT = {1: "IT", 2: "IT", 3: "IT", 4: "IT", 5: "Autos", 6: "IT"}


def test_each_stock_is_compared_with_the_median_of_its_other_sector_peers():
    out = {r["instrument_id"]: r for r in add_sector_view(rows(), SECT)}
    assert out[1]["sector"] == "IT" and out[1]["pe_sector_median"] == D(30)  # peers 20, 30, 40
    assert out[1]["pe_vs_sector"] == D(10) / D(30)
    assert out[4]["pe_sector_median"] == D(20)  # peers 10, 20, 30
    assert out[6]["pe_vs_sector"] is None and out[6]["pe_sector_median"] == D(
        25
    )  # no own pe: no relative value, but the sector's median is shown


def test_a_sector_with_too_few_peers_or_a_stock_without_a_sector_gets_no_median():
    r = rows() + [{"instrument_id": 7, "pe": D(9)}]
    out = {x["instrument_id"]: x for x in add_sector_view(r, SECT)}
    assert (
        out[5]["sector"] == "Autos"
        and out[5]["pe_sector_median"] is None
        and out[5]["pe_vs_sector"] is None
    )
    assert out[7]["sector"] is None and out[7]["pe_vs_sector"] is None


def test_the_new_fields_exist_for_the_screener_but_cannot_be_used_by_a_study():
    for key in ("sector", "pe_sector_median", "pe_vs_sector"):
        assert (
            engine.FIELDS[key].kind == "profile"
        )  # a study's fundamentals book does not carry them
    assert engine.FIELDS["sector"].unit == "text" and engine.FIELDS["pe_vs_sector"].unit == "x"
