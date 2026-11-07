import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

IMAGE = "timescale/timescaledb:2.17.2-pg16"


@pytest.fixture(scope="session")
def pg_url():
    with PostgresContainer(IMAGE, driver=None) as pg:
        yield pg.get_connection_url()


@pytest.fixture
def conn(pg_url):
    """Fresh database state per test: drop and recreate the public schema."""
    with psycopg.connect(pg_url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        yield c
