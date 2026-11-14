"""Which price feed the readers use, chosen in `.env` (or the process environment, which wins):
  ALGO_PRICE_SOURCE=kite       1-minute Kite bars rolled to days (the primary copy)
  ALGO_PRICE_SOURCE=bhavcopy   NSE bhavcopy daily bars (backup copy; default if unset)
  ALGO_PRICE_CUTOFF=YYYY-MM-DD with bhavcopy: Kite's bars up to and including that day, bhavcopy
                               after it (the switch-over when Kite is stopped)
Flip the value and restart: nothing else changes. An unknown value is refused, never guessed."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from algo.data.providers.kite_session import load_env

KEY = "ALGO_PRICE_SOURCE"
CHOICES = ("kite", "bhavcopy")


def price_source(env: Mapping[str, str] | None = None, env_file: Path = Path(".env")) -> str:
    env = os.environ if env is None else env
    value = (env.get(KEY) or load_env(env_file).get(KEY) or "bhavcopy").strip().lower()
    if value not in CHOICES:
        raise ValueError(f"{KEY} must be kite or bhavcopy, got {value!r}")
    return value


CUTOFF_KEY = "ALGO_PRICE_CUTOFF"


def price_cutoff(
    env: Mapping[str, str] | None = None, env_file: Path = Path(".env")
) -> date | None:
    env = os.environ if env is None else env
    value = (env.get(CUTOFF_KEY) or load_env(env_file).get(CUTOFF_KEY) or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{CUTOFF_KEY} must be YYYY-MM-DD, got {value!r}") from None
