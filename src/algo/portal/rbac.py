# ruff: noqa: E501
"""Roles and permissions: a fixed table, deny by default. docs/portal/DESIGN.md section 3 is the reference."""

from __future__ import annotations

from types import MappingProxyType

ROLES = ("ADMIN", "OPERATOR", "TRADER", "VIEWER")
PERMISSIONS = frozenset(
    "research:read kite:own strategy:own ops:read ops:write users:read users:write roles:write crm:read crm:write "
    "tickets:own tickets:manage audit:read system:settings holdout:read".split()  # holdout:read: ADMIN only, the owner (docs/holdout-policy-v3.md section 5)
)
_VIEWER = {"research:read", "tickets:own"}
_TRADER = _VIEWER | {"kite:own", "strategy:own"}
_OPERATOR = _VIEWER | {
    "kite:own",
    "ops:read",
    "ops:write",
    "crm:read",
    "crm:write",
    "tickets:manage",
}
ROLE_PERMISSIONS = MappingProxyType(
    {
        "VIEWER": frozenset(_VIEWER),
        "TRADER": frozenset(_TRADER),
        "OPERATOR": frozenset(_OPERATOR),
        "ADMIN": PERMISSIONS,
    }
)
MFA_REQUIRED = frozenset({"ADMIN", "OPERATOR"})


def permissions_of(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def can(role: str, permission: str) -> bool:
    return permission in permissions_of(role)
