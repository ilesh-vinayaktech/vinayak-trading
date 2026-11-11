"""Which price feed the readers use, chosen in `.env` (or the process environment, which wins):
  ALGO_PRICE_SOURCE=kite       1-minute Kite bars rolled to days (the primary copy)
  ALGO_PRICE_SOURCE=bhavcopy   NSE bhavcopy daily bars (backup copy; default if unset)
Flip the value and restart: nothing else changes. An unknown value is refused, never guessed."""

from __future__ import annotations

import os
from collections.abc import Mapping
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
