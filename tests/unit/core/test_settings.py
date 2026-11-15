import pytest

from algo.core.settings import LIVE_CONFIRM, ConfigError, Settings

BASE = {"ALGO_DB_URL": "postgresql://u@h/db"}


def test_defaults_are_the_safe_ones_and_everything_is_read_from_the_environment():
    s = Settings.from_env(BASE)
    assert (s.mode, s.cookie_secure, s.trust_proxy, s.price_source) == (
        "research",
        True,
        False,
        "bhavcopy",
    )
    assert s.cors_origins == ("http://localhost:3000",) and s.live is False
    t = Settings.from_env({**BASE, "ALGO_MODE": "paper", "ALGO_COOKIE_SECURE": "0", "ALGO_TRUST_PROXY": "1",
                           "ALGO_CORS_ORIGINS": "https://a.example, https://b.example", "ALGO_PRICE_SOURCE": "kite"})  # fmt: skip
    assert (t.mode, t.cookie_secure, t.trust_proxy, t.price_source) == (
        "paper",
        False,
        True,
        "kite",
    )
    assert t.cors_origins == ("https://a.example", "https://b.example")


@pytest.mark.parametrize(
    ("env", "msg"),
    [
        ({}, "ALGO_DB_URL"),
        ({"ALGO_DB_URL": "mysql://x"}, "ALGO_DB_URL"),
        ({**BASE, "ALGO_MODE": "yolo"}, "ALGO_MODE"),
        ({**BASE, "ALGO_COOKIE_SECURE": "maybe"}, "ALGO_COOKIE_SECURE"),
        ({**BASE, "ALGO_PRICE_SOURCE": "nse"}, "ALGO_PRICE_SOURCE"),
        ({**BASE, "ALGO_CORS_ORIGINS": " , "}, "ALGO_CORS_ORIGINS"),
    ],
)
def test_invalid_configuration_is_rejected_naming_the_variable(env, msg):
    with pytest.raises(ConfigError, match=msg):
        Settings.from_env(env)


def test_live_mode_needs_the_exact_confirmation_and_nothing_else_turns_it_on():
    with pytest.raises(ConfigError, match="ALGO_LIVE_CONFIRM"):
        Settings.from_env({**BASE, "ALGO_MODE": "live"})
    with pytest.raises(ConfigError, match="ALGO_LIVE_CONFIRM"):
        Settings.from_env({**BASE, "ALGO_MODE": "live", "ALGO_LIVE_CONFIRM": "yes"})
    assert (
        Settings.from_env({**BASE, "ALGO_MODE": "live", "ALGO_LIVE_CONFIRM": LIVE_CONFIRM}).live
        is True
    )
    # a stray confirmation without live mode does not make it live
    assert Settings.from_env({**BASE, "ALGO_LIVE_CONFIRM": LIVE_CONFIRM}).live is False
