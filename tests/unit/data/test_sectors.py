from decimal import Decimal as D

from algo.data import sectors


def test_the_median_of_an_odd_and_an_even_group_and_peers_exclude_the_stock_itself():
    ratios = {1: D(10), 2: D(20), 3: D(40), 4: D(50), 5: D(7)}
    sect = {1: "IT", 2: "IT", 3: "IT", 4: "Banks", 5: "Banks"}
    m = sectors.peer_median(ratios, sect, 1)  # peers of 1 in IT: 20 and 40
    assert (m.median, m.peers, m.sector) == (D(30), 2, "IT")
    assert sectors.peer_median(ratios, sect, 4).median == D(7)  # one peer: its own value
    assert sectors.peer_median(ratios, sect, 2).median == D(25)  # peers 10 and 40


def test_missing_values_are_skipped_and_too_few_peers_or_no_sector_give_no_median():
    ratios = {1: D(10), 2: None, 3: D(30)}
    sect = {1: "IT", 2: "IT", 3: "IT", 4: "Autos"}
    assert (
        sectors.peer_median(ratios, sect, 1).median == D(30)
        and sectors.peer_median(ratios, sect, 1).peers == 1
    )
    assert (
        sectors.peer_median(ratios, sect, 4).median is None
        and sectors.peer_median(ratios, sect, 4).peers == 0
    )
    assert sectors.peer_median(ratios, sect, 99).sector is None  # no sector known
    assert (
        sectors.peer_median(ratios, sect, 1, min_peers=2).median is None
    )  # a median of one name is not a sector view


def test_relative_value_is_the_ratio_over_the_peer_median_and_none_without_a_median_or_with_zero():
    assert sectors.relative(D(15), sectors.Peer("IT", D(30), 2)) == D("0.5")
    assert sectors.relative(D(15), sectors.Peer("IT", None, 0)) is None
    assert sectors.relative(None, sectors.Peer("IT", D(30), 2)) is None
    assert sectors.relative(D(15), sectors.Peer("IT", D(0), 2)) is None


def test_parse_reads_symbol_isin_and_industry_and_skips_blank_industries():
    text = "Company Name,Industry,Symbol,Series,ISIN Code\nA Ltd.,Financial Services,AAA,EQ,INE000000001\nB Ltd.,,BBB,EQ,INE000000002\n"
    assert sectors.parse(text.encode("utf-8-sig")) == [
        ("AAA", "INE000000001", "Financial Services")
    ]
