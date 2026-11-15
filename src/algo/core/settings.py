# ruff: noqa: E501
"""Validated process configuration, read from the environment in one place. Invalid values are refused naming the variable.
Real orders need ALGO_MODE=live AND ALGO_LIVE_CONFIRM set to the exact phrase: one typo or a stray variable can never switch them on.
(`algo.api.main` still reads its variables directly; moving it onto Settings is a separate, small change.)"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

LIVE_CONFIRM = "I-ACCEPT-REAL-ORDERS"
MODES = ("research", "paper", "live")
PRICE_SOURCES = ("kite", "bhavcopy")


class ConfigError(ValueError):
    pass


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    if raw not in ("0", "1"):
        raise ConfigError(f"{name} must be 0 or 1, got {raw!r}")
    return raw == "1"


def _choice(env: Mapping[str, str], name: str, allowed: tuple[str, ...], default: str) -> str:
    value = env.get(name, default)
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {allowed}, got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    db_url: str
    mode: str
    price_source: str
    cookie_secure: bool
    trust_proxy: bool
    public_url: str
    cors_origins: tuple[str, ...]

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        db = env.get("ALGO_DB_URL", "")
        if not db.startswith(("postgresql://", "postgres://")):
            raise ConfigError("ALGO_DB_URL must be a postgresql:// URL")
        mode = _choice(env, "ALGO_MODE", MODES, "research")
        if mode == "live" and env.get("ALGO_LIVE_CONFIRM") != LIVE_CONFIRM:
            raise ConfigError(f"ALGO_MODE=live needs ALGO_LIVE_CONFIRM={LIVE_CONFIRM}")
        origins = tuple(
            o.strip()
            for o in env.get("ALGO_CORS_ORIGINS", "http://localhost:3000").split(",")
            if o.strip()
        )
        if not origins:
            raise ConfigError("ALGO_CORS_ORIGINS must list at least one origin")
        return cls(
            db, mode, _choice(env, "ALGO_PRICE_SOURCE", PRICE_SOURCES, "bhavcopy"),
            _flag(env, "ALGO_COOKIE_SECURE", True), _flag(env, "ALGO_TRUST_PROXY", False),
            env.get("ALGO_PUBLIC_URL", "http://localhost:3000"), origins,
        )  # fmt: skip
