import pytest

from algo.portal.passwords import Hasher, PasswordPolicyError, check_policy

FAST = Hasher(
    time_cost=1, memory_cost=8, parallelism=1
)  # tests only: the real defaults are deliberately slow


def test_hashes_are_argon2id_salted_and_verify_only_the_right_password():
    h = FAST.hash("correct horse battery staple")
    assert h.startswith("$argon2id$") and h != FAST.hash("correct horse battery staple")  # salted
    assert FAST.verify(h, "correct horse battery staple") is True
    assert FAST.verify(h, "Correct horse battery staple") is False
    assert FAST.verify("not a hash", "x") is False  # a corrupt stored value never authenticates


def test_a_hash_made_with_weaker_settings_is_flagged_for_upgrade():
    weak = Hasher(time_cost=1, memory_cost=8, parallelism=1).hash("a long enough password 1")
    strong = Hasher(time_cost=2, memory_cost=16, parallelism=1)
    assert strong.needs_rehash(weak) and not strong.needs_rehash(
        strong.hash("a long enough password 1")
    )


def test_the_dummy_check_for_unknown_users_costs_a_real_hash_and_is_always_false():
    assert FAST.burn("anything at all") is False


@pytest.mark.parametrize(
    "password,why",
    [
        ("short1!", "at least 12"),
        ("x" * 129, "at most 128"),
        ("aaaaaaaaaaaaaaaa", "single repeated"),
        ("password1234", "too common"),
        ("jane.doe-2026-ok", "email"),
        ("Priya Sharma 99!", "name"),
    ],
)
def test_weak_passwords_are_refused_with_a_reason(password, why):
    with pytest.raises(PasswordPolicyError, match=why):
        check_policy(
            password,
            email="jane.doe@example.com",
            display_name="Priya Sharma" if "Priya" in password else "",
        )


def test_a_long_unique_passphrase_is_accepted():
    check_policy("violet-harbor-lantern-42", email="jane.doe@example.com", display_name="Jane")
