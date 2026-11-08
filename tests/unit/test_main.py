from pathlib import Path

import pytest

from algo.api.main import build


def test_the_app_is_built_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALGO_DB_URL", "postgresql://u@h/db")
    monkeypatch.setenv("ALGO_DOCS_DIR", "somewhere")
    monkeypatch.setenv("ALGO_CORS_ORIGINS", "http://a.example, http://b.example,")
    app = build()
    assert app.state.dsn == "postgresql://u@h/db"
    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_origins"] == ["http://a.example", "http://b.example"]
    assert Path("somewhere").name == "somewhere"


def test_defaults_allow_only_the_local_console(monkeypatch):
    monkeypatch.setenv("ALGO_DB_URL", "postgresql://u@h/db")
    monkeypatch.delenv("ALGO_DOCS_DIR", raising=False)
    monkeypatch.delenv("ALGO_CORS_ORIGINS", raising=False)
    cors = next(m for m in build().user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_origins"] == ["http://localhost:3000"]


def test_a_missing_connection_string_is_an_explicit_error(monkeypatch):
    monkeypatch.delenv("ALGO_DB_URL", raising=False)
    with pytest.raises(RuntimeError, match="ALGO_DB_URL is not set"):
        build()


def test_interactive_docs_need_an_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("ALGO_DB_URL", "postgresql://u@h/db")
    monkeypatch.delenv("ALGO_API_DOCS", raising=False)
    assert build().docs_url is None and build().openapi_url is None
    monkeypatch.setenv("ALGO_API_DOCS", "1")
    assert build().docs_url == "/docs"
    monkeypatch.setenv("ALGO_API_DOCS", "yes")
    assert build().docs_url is None  # only the exact value 1 turns them on
