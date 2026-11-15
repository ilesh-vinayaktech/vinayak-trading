import pytest


@pytest.fixture(autouse=True)
def _open_research_lock_file(tmp_path, monkeypatch):
    """Integration tests read the research lock from a file with an open window far in the future (see tests/support/research_lock.py);
    a test that needs the lock in the database anchors it, a test of the lock itself patches the file again."""
    from algo.research import holdout_lock
    from tests.support.research_lock import write_lock_file

    monkeypatch.setattr(
        holdout_lock, "LOCK_FILE", write_lock_file(tmp_path / "research_holdout.json")
    )
