"""The fault suite runs against a real Postgres like the integration tests, so it reuses their database fixtures."""

from tests.integration.conftest import _open_research_lock_file, conn, pg_url  # noqa: F401
