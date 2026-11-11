# ruff: noqa: E501
"""Outgoing mail behind an interface. Development uses the console mailer (it only remembers and logs what would be sent);
a real SMTP or provider mailer is a drop-in for deployment. Message bodies carry links, never passwords."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger("algo.portal.mail")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


@dataclass
class Message:
    to: str
    subject: str
    body: str


class ConsoleMailer:
    def __init__(self) -> None:
        self.sent: list[Message] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append(Message(to, subject, body))
        log.info("mail to %s: %s", to, subject)  # the body (a link) is not logged
