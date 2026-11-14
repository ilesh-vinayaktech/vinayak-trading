import time

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

IMAGE = "timescale/timescaledb:2.17.2-pg16"


@pytest.fixture(autouse=True)
def _open_research_lock_file(tmp_path, monkeypatch):
    """Integration tests read the research lock from a file with an open window far in the future (see tests/support/research_lock.py);
    a test that needs the lock in the database anchors it, a test of the lock itself patches the file again."""
    from algo.research import holdout_lock
    from tests.support.research_lock import write_lock_file

    monkeypatch.setattr(
        holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "research_holdout.json")
    )


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
