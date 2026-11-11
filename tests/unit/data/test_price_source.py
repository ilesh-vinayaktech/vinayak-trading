import pytest

from algo.data.price_source import price_source


def test_nothing_set_means_bhavcopy(tmp_path):
    assert price_source({}, tmp_path / "missing.env") == "bhavcopy"


def test_the_process_environment_beats_the_env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("ALGO_PRICE_SOURCE=kite\n")
    assert price_source({}, f) == "kite"
    assert price_source({"ALGO_PRICE_SOURCE": "bhavcopy"}, f) == "bhavcopy"


def test_value_is_trimmed_and_case_insensitive(tmp_path):
    assert price_source({"ALGO_PRICE_SOURCE": " Kite "}, tmp_path / "x") == "kite"


def test_an_unknown_value_is_refused_not_guessed(tmp_path):
    with pytest.raises(ValueError, match="kite or bhavcopy"):
        price_source({"ALGO_PRICE_SOURCE": "zerodha"}, tmp_path / "x")
