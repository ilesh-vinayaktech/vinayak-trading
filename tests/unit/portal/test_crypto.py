import base64

import pytest

from algo.portal.crypto import KeyRing, VaultError

K1, K2 = base64.b64encode(b"1" * 32).decode(), base64.b64encode(b"2" * 32).decode()


def ring(current="v1"):
    return KeyRing.from_env({"ALGO_VAULT_KEYS": f"v1:{K1},v2:{K2}", "ALGO_VAULT_CURRENT": current})


def test_a_secret_round_trips_and_the_ciphertext_hides_it():
    r = ring()
    token = r.encrypt("kite-secret", aad="user:1:api_secret")
    assert token.startswith("v1.") and "kite-secret" not in token
    assert r.decrypt(token, aad="user:1:api_secret") == b"kite-secret"
    assert r.encrypt("kite-secret", aad="user:1:api_secret") != token  # fresh nonce every time


def test_the_context_is_bound_to_the_ciphertext():
    r = ring()
    token = r.encrypt("x", aad="user:1:api_key")
    with pytest.raises(VaultError):
        r.decrypt(token, aad="user:2:api_key")  # moved to another owner or field


def test_tampering_and_unknown_keys_are_refused():
    r = ring()
    token = r.encrypt("x", aad="a")
    head, _, body = token.partition(".")
    flipped = base64.b64decode(body)
    flipped = bytes([flipped[0] ^ 1]) + flipped[1:]
    with pytest.raises(VaultError):
        r.decrypt(f"{head}.{base64.b64encode(flipped).decode()}", aad="a")
    with pytest.raises(VaultError):
        r.decrypt(f"v9.{body}", aad="a")
    for junk in ("nodot", "v1.%%%not-base64", "v1.AAAA"):
        with pytest.raises(VaultError):
            r.decrypt(junk, aad="a")


def test_rotation_new_writes_use_the_current_key_and_old_tokens_still_open():
    old = ring("v1").encrypt("x", aad="a")
    r = ring("v2")
    assert r.encrypt("y", aad="a").startswith("v2.")
    assert (
        r.decrypt(old, aad="a") == b"x"
        and r.needs_rotation(old)
        and not r.needs_rotation(r.encrypt("y", aad="a"))
    )


def test_the_key_ring_configuration_is_validated():
    for env in (
        {},  # nothing configured
        {"ALGO_VAULT_KEYS": f"v1:{K1}"},  # no current key named
        {"ALGO_VAULT_KEYS": f"v1:{K1}", "ALGO_VAULT_CURRENT": "v2"},  # current not in the ring
        {"ALGO_VAULT_KEYS": "v1:short", "ALGO_VAULT_CURRENT": "v1"},  # not base64
        {
            "ALGO_VAULT_KEYS": "v1:" + base64.b64encode(b"x" * 16).decode(),
            "ALGO_VAULT_CURRENT": "v1",
        },  # 16 bytes
        {"ALGO_VAULT_KEYS": "v1", "ALGO_VAULT_CURRENT": "v1"},  # malformed entry
        {"ALGO_VAULT_KEYS": f"v1:{K1},v1:{K2}", "ALGO_VAULT_CURRENT": "v1"},  # duplicate id
    ):
        with pytest.raises(VaultError):
            KeyRing.from_env(env)
