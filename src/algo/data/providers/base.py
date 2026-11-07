"""Provider contract. parse() is pure and offline so it can be re-run on old raw files."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol, runtime_checkable

from algo.data.bars import Bar, Freq


class ParseError(Exception):
    pass


class NotPublishedError(Exception):
    """Provider has no file for this partition (holiday, or an incident on a trading day)."""


@runtime_checkable
class DataProvider(Protocol):
    name: str

    def supports_corrections(self) -> bool: ...
    def freq(self, dataset: str) -> Freq: ...
    def url(self, dataset: str, d: date) -> str: ...
    def fetch(self, dataset: str, d: date) -> bytes: ...
    def parse(self, dataset: str, d: date, raw: bytes) -> Iterable[Bar]: ...
