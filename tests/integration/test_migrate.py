import pytest

from algo.data.store.migrate import migrate

pytestmark = pytest.mark.integration


def test_applies_once_and_is_idempotent(conn):
    first = migrate(conn)
    assert first and first[0].startswith("001_")
    assert migrate(conn) == []
    tables = {
        r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    }
    assert {"exchange", "instrument", "instrument_terms", "instrument_alias"} <= tables


def test_failed_migration_rolls_back(conn, tmp_path, monkeypatch):
    from algo.data.store import migrate as m

    (tmp_path / "001_bad.sql").write_text("CREATE TABLE t1(x int); SELECT 1/0;")
    monkeypatch.setattr(m, "MIGRATIONS", tmp_path)
    with pytest.raises(Exception, match="division"):
        m.migrate(conn)
    assert conn.execute("SELECT to_regclass('t1')").fetchone()[0] is None
    assert conn.execute("SELECT count(*) FROM schema_migration").fetchone()[0] == 0
