# ruff: noqa: E501
"""Encryption of stored secrets (Kite keys and tokens, 2FA seeds): AES-256-GCM with a key ring.

A token is `<key id>.<base64(nonce + ciphertext)>`. The authenticated context (`aad`, e.g. "user:<id>:api_secret") is bound
into the ciphertext, so a value copied to another owner or field fails to decrypt. Keys live only in the environment:
ALGO_VAULT_KEYS="v1:<base64 32 bytes>,v2:<...>" and ALGO_VAULT_CURRENT="v2". Add a key, switch CURRENT, re-encrypt in the
background (`needs_rotation`), then retire the old one: no downtime."""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultError(Exception):
    pass


@dataclass(frozen=True)
class KeyRing:
    keys: Mapping[str, bytes]
    current: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> KeyRing:
        raw, current = env.get("ALGO_VAULT_KEYS", ""), env.get("ALGO_VAULT_CURRENT", "")
        keys: dict[str, bytes] = {}
        for item in filter(None, (p.strip() for p in raw.split(","))):
            kid, sep, b64 = item.partition(":")
            if not sep or not kid or kid in keys:
                raise VaultError("ALGO_VAULT_KEYS must be unique 'id:base64key' pairs")
            try:
                key = base64.b64decode(b64, validate=True)
            except binascii.Error as e:
                raise VaultError(f"vault key {kid} is not base64") from e
            if len(key) != 32:
                raise VaultError(f"vault key {kid} must be 32 bytes")
            keys[kid] = key
        if not keys or current not in keys:
            raise VaultError("ALGO_VAULT_CURRENT must name a key in ALGO_VAULT_KEYS")
        return cls(keys, current)

    def encrypt(self, plaintext: str | bytes, *, aad: str) -> str:
        data = plaintext.encode() if isinstance(plaintext, str) else plaintext
        nonce = os.urandom(12)
        body = AESGCM(self.keys[self.current]).encrypt(nonce, data, aad.encode())
        return f"{self.current}.{base64.b64encode(nonce + body).decode()}"

    def decrypt(self, token: str, *, aad: str) -> bytes:
        kid, sep, b64 = token.partition(".")
        if not sep or kid not in self.keys:
            raise VaultError("unknown key or malformed token")
        try:
            blob = base64.b64decode(b64, validate=True)
            return AESGCM(self.keys[kid]).decrypt(blob[:12], blob[12:], aad.encode())
        except (binascii.Error, InvalidTag, ValueError) as e:
            raise VaultError("secret could not be decrypted") from e

    def needs_rotation(self, token: str) -> bool:
        return token.partition(".")[0] != self.current
