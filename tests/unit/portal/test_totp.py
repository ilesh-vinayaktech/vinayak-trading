from datetime import UTC, datetime

from algo.portal.totp import (
    code_at,
    hash_recovery,
    new_recovery_codes,
    new_secret,
    provisioning_uri,
    verify,
)

RFC = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # RFC 6238 test secret "12345678901234567890"


def at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


def test_codes_match_the_rfc_6238_test_vectors():
    # RFC 6238 appendix B (SHA-1), last six digits of the 8-digit values
    for t, expected in [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
    ]:
        assert code_at(RFC, t // 30) == expected


def test_a_code_is_accepted_in_its_step_and_one_step_either_side_but_not_replayed():
    step = 1111111109 // 30
    assert verify(RFC, "081804", at(1111111109), last_step=None) == step
    assert (
        verify(RFC, "081804", at(1111111109 + 30), last_step=None) == step
    )  # a slow typist, one step later
    assert verify(RFC, "081804", at(1111111109 + 90), last_step=None) is None  # too old
    assert verify(RFC, "081804", at(1111111109), last_step=step) is None  # the same code twice
    assert verify(RFC, "081804", at(1111111109), last_step=step - 1) == step


def test_malformed_or_wrong_codes_are_rejected():
    for bad in ("", "12345", "1234567", "abcdef", " 081804", "081805"):
        assert verify(RFC, bad, at(1111111109), last_step=None) is None


def test_new_secrets_are_random_base32_and_the_uri_names_issuer_and_account():
    a, b = new_secret(), new_secret()
    assert a != b and len(a) == 32 and set(a) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    uri = provisioning_uri(a, "jane@example.com", "Vinayak Trading")
    assert (
        uri.startswith("otpauth://totp/Vinayak%20Trading:jane%40example.com?")
        and f"secret={a}" in uri
        and "issuer=Vinayak%20Trading" in uri
    )


def test_recovery_codes_are_unique_readable_and_stored_only_as_hashes():
    codes = new_recovery_codes()
    assert (
        len(codes) == 10
        and len(set(codes)) == 10
        and all(len(c) == 11 and c[5] == "-" for c in codes)
    )
    assert (
        hash_recovery(codes[0])
        == hash_recovery(codes[0].upper().replace("-", " "))
        != hash_recovery(codes[1])
    )  # case and separators do not matter
    assert codes[0] not in hash_recovery(codes[0])
