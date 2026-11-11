import pytest


@pytest.fixture(autouse=True)
def _price_source_is_bhavcopy_unless_a_test_says_otherwise(monkeypatch):
    """The developer's .env may select Kite; tests must not depend on it."""
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "bhavcopy")
