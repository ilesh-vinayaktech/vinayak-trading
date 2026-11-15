import time

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

IMAGE = "timescale/timescaledb:2.17.2-pg16"


@pytest.fixture(autouse=True)
def _price_source_is_bhavcopy_unless_a_test_says_otherwise(monkeypatch):
    """The developer's .env may select Kite; tests must not depend on it."""
    monkeypatch.setenv("ALGO_PRICE_SOURCE", "bhavcopy")


@pytest.fixture(scope="session")
def pg_url():
    with PostgresContainer(IMAGE, driver=None) as pg:
        yield pg.get_connection_url()


@pytest.fixture
def conn(pg_url):
    """Fresh database state per test: drop and recreate the public schema."""
    with psycopg.connect(pg_url, autocommit=True) as c:
        for attempt in range(5):
            try:
                c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
                break
            except (
                psycopg.errors.DeadlockDetected
            ):  # a TimescaleDB background worker touched a table being dropped: the victim retries
                if attempt == 4:
                    raise
                time.sleep(0.5)
        yield c
