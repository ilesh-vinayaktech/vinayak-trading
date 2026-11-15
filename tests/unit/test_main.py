from pathlib import Path

import pytest

from algo.api.main import build
from algo.portal.crypto import VaultError


@pytest.fixture(autouse=True)
def _vault_keys(monkeypatch):
    monkeypatch.setenv("ALGO_VAULT_KEYS", "v1:" + "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")
    monkeypatch.setenv("ALGO_VAULT_CURRENT", "v1")


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


def test_the_app_will_not_start_without_a_key_ring(monkeypatch):
    monkeypatch.setenv("ALGO_DB_URL", "postgresql://u@h/db")
    monkeypatch.delenv("ALGO_VAULT_KEYS")
    with pytest.raises(VaultError):
        build()


def test_cookie_and_proxy_settings_default_to_the_safe_choice(monkeypatch):
    monkeypatch.setenv("ALGO_DB_URL", "postgresql://u@h/db")
    monkeypatch.delenv("ALGO_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("ALGO_TRUST_PROXY", raising=False)
    st = build().state.portal
    assert (
        st.cookie_secure is True and st.trust_proxy is False and st.cookie_name == "__Host-session"
    )
    monkeypatch.setenv("ALGO_COOKIE_SECURE", "0")
    monkeypatch.setenv("ALGO_TRUST_PROXY", "1")
    st = build().state.portal
    assert st.cookie_secure is False and st.trust_proxy is True and st.cookie_name == "session"


def test_an_invalid_setting_stops_the_app_naming_the_variable(monkeypatch):
    from algo.core.settings import ConfigError

    monkeypatch.setenv("ALGO_DB_URL", "postgresql://u@h/db")
    monkeypatch.setenv("ALGO_COOKIE_SECURE", "maybe")
    with pytest.raises(ConfigError, match="ALGO_COOKIE_SECURE"):
        build()
    monkeypatch.setenv("ALGO_COOKIE_SECURE", "1")
    monkeypatch.setenv("ALGO_MODE", "live")  # no confirmation phrase
    with pytest.raises(ConfigError, match="ALGO_LIVE_CONFIRM"):
        build()
