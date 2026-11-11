import pytest

from algo.portal.rbac import MFA_REQUIRED, PERMISSIONS, ROLES, can, permissions_of


def test_every_role_is_known_and_unknown_roles_and_permissions_get_nothing():
    assert set(ROLES) == {"ADMIN", "OPERATOR", "TRADER", "VIEWER"}
    assert permissions_of("NOBODY") == frozenset() and not can("NOBODY", "research:read")
    assert not can(
        "ADMIN", "made:up"
    )  # deny by default: a permission nobody declared is never granted


@pytest.mark.parametrize(
    "role,allowed,denied",
    [
        (
            "VIEWER",
            ["research:read", "tickets:own"],
            ["kite:own", "ops:read", "users:write", "crm:read", "audit:read"],
        ),
        (
            "TRADER",
            ["research:read", "kite:own", "strategy:own", "tickets:own"],
            ["ops:read", "ops:write", "users:read", "crm:write"],
        ),
        (
            "OPERATOR",
            ["research:read", "ops:read", "ops:write", "crm:read", "crm:write", "tickets:manage"],
            ["users:write", "roles:write", "audit:read", "system:settings", "strategy:own"],
        ),
        ("ADMIN", sorted(PERMISSIONS), []),
    ],
)
def test_the_role_matrix_matches_the_design(role, allowed, denied):
    assert all(can(role, p) for p in allowed) and not any(can(role, p) for p in denied)


def test_only_admin_and_operator_must_use_a_second_factor():
    assert MFA_REQUIRED == frozenset({"ADMIN", "OPERATOR"})
