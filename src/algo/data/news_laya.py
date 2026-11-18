# ruff: noqa: E501
"""Score headlines with the Laya model (TODO 6.7 follow-up): a local ONNX decision model run by the Node script `tools/laya/score.mjs` (no API key, nothing leaves the machine).

`score_pending` takes the stored headlines that have no Laya reading yet (newest first, at most `limit`), asks the scorer for a sentiment from -1 to +1 and its confidence, and stores both
beside the keyword reading. The scorer is a function from a list of {id, text} to a list of {id, sentiment, confidence}, so tests use a fake and the real one is `node_runner`. A
failure to score (no Node, no model, a crash) leaves the headlines unscored and says so; the keyword reading stays and the next run tries again."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

Runner = Callable[[Sequence[dict[str, str]]], list[dict[str, Any]]]
LOOKBACK = timedelta(days=7)  # an older headline that was never scored is left alone
MAX_TEXT = 400  # characters of title and summary given to the model


LAYA_BAND, WORDS_BAND = (
    0.3,
    0.15,
)  # how far from zero a reading must be to count as positive or negative (Laya's readings are wider than the word list's)


class LayaError(Exception):
    pass


def reading(words: float | None, laya: float | None) -> tuple[str | None, float | None, str | None]:
    """(label, value, which model) of one headline: Laya's reading where it has one, else the keyword reading, else nothing. The label is positive, negative or mixed."""
    if laya is not None:
        value, band, model = float(laya), LAYA_BAND, "laya"
    elif words is not None:
        value, band, model = float(words), WORDS_BAND, "words"
    else:
        return None, None, None
    return (
        ("positive" if value >= band else "negative" if value <= -band else "mixed"),
        value,
        model,
    )


def text_of(title: str, summary: str | None) -> str:
    return (f"{title}. {summary}" if summary else title)[:MAX_TEXT]


def node_runner(tool_dir: Path, timeout: float = 1800.0, node: str = "node") -> Runner:
    """The real scorer: `node score.mjs` in `tool_dir`, headlines in as JSON on stdin and scores out as JSON on stdout."""

    def run(items: Sequence[dict[str, str]]) -> list[dict[str, Any]]:
        try:
            done = subprocess.run(  # noqa: S603
                [node, "score.mjs"],
                input=json.dumps(list(items)),
                capture_output=True,
                text=True,
                cwd=tool_dir,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise LayaError(f"could not run the scorer: {e}") from e
        if done.returncode != 0:
            raise LayaError(
                f"the scorer failed (exit {done.returncode}): {done.stderr.strip()[-300:]}"
            )
        try:
            out = json.loads(done.stdout)
        except ValueError as e:
            raise LayaError(
                f"the scorer printed something that is not JSON: {done.stdout[:100]!r}"
            ) from e
        if not isinstance(out, list):
            raise LayaError("the scorer did not return a list")
        return out

    return run


def score_pending(conn: psycopg.Connection, runner: Runner, now: datetime, limit: int = 200) -> int:
    """Score up to `limit` unscored headlines from the last week; returns how many were stored. Scores outside -1..1 or without a confidence are refused as a broken scorer."""
    rows = conn.execute(
        "SELECT item_id, title, summary FROM news_item WHERE laya_sentiment IS NULL AND published_at >= %s ORDER BY published_at DESC LIMIT %s",
        (now - LOOKBACK, limit),
    ).fetchall()
    if not rows:
        return 0
    scored = runner([{"id": i, "text": text_of(t, s)} for i, t, s in rows])
    known = {i for i, _, _ in rows}
    stored = 0
    for r in scored:
        s, c = r.get("sentiment"), r.get("confidence")
        if (
            r.get("id") not in known
            or not isinstance(s, int | float)
            or not isinstance(c, int | float)
            or not -1.0 <= s <= 1.0
            or not 0.0 <= c <= 1.0
        ):
            raise LayaError(f"the scorer returned an unusable row: {str(r)[:120]}")
        conn.execute(
            "UPDATE news_item SET laya_sentiment=%s, laya_confidence=%s, laya_scored_at=%s WHERE item_id=%s",
            (s, c, now, r["id"]),
        )
        stored += 1
    return stored
