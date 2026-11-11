# ruff: noqa: E501
"""Password hashing (Argon2id) and the password policy. Plain passwords never leave this module's callers' stack frames:
nothing here logs or stores them."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH, MAX_LENGTH = 12, 128
# the most reused passwords that still satisfy a length rule; a real breach-list check can replace this later
COMMON = frozenset(
    "password1234 password12345 123456789012 qwertyuiop12 qwerty123456 letmein12345 welcome12345 iloveyou1234 "
    "administrator admin1234567 changeme1234 passw0rd1234 abcdefghijkl 111111111111 000000000000 trading12345".split()
)


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str, *, email: str = "", display_name: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"use at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"use at most {MAX_LENGTH} characters")
    if len(set(password)) < 4:
        raise PasswordPolicyError("a single repeated character is not a password")
    low = password.lower()
    if low in COMMON:
        raise PasswordPolicyError("this password is too common")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in low:
        raise PasswordPolicyError("the password must not contain your email name")
    name = display_name.strip().lower()
    if len(name) >= 4 and name in low:
        raise PasswordPolicyError("the password must not contain your name")


class Hasher:
    """Argon2id. The defaults follow the OWASP minimum (19 MiB, 2 passes) raised to 64 MiB / 3 passes."""

    def __init__(self, time_cost: int = 3, memory_cost: int = 65536, parallelism: int = 4) -> None:
        self._ph = PasswordHasher(
            time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism
        )
        self._dummy = self._ph.hash("dummy-password-for-timing")

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, stored: str, password: str) -> bool:
        try:
            return bool(self._ph.verify(stored, password))
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, stored: str) -> bool:
        return bool(self._ph.check_needs_rehash(stored))

    def burn(self, password: str) -> bool:
        """Spend the time of a real check for an unknown account, so response time does not reveal who exists."""
        self.verify(self._dummy, password)
        return False
