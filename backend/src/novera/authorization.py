"""Pure, deny-by-default tenant RBAC policy. Not authentication or user storage.

A Principal MUST be assembled by a future trusted identity/session service
after verified login and membership lookup. Never create one directly from
client-controlled HTTP fields. A decision does NOT certify provider data rights.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from novera.storage import StorageScope

POLICY_VERSION = "tenant-rbac-v1"


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    OWNER = "owner"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Permission(StrEnum):
    VIEW_PRODUCTS = "view_products"
    VIEW_RESEARCH = "view_research"
    EXPORT_RESEARCH = "export_research"
    MANAGE_PRODUCTS = "manage_products"
    MANAGE_USERS = "manage_users"
    MANAGE_ENTITLEMENTS = "manage_entitlements"


class DecisionCode(StrEnum):
    ALLOW = "allow"
    INVALID_CONTEXT = "invalid_context"
    UNAUTHENTICATED = "unauthenticated"
    INACTIVE_MEMBERSHIP = "inactive_membership"
    WRONG_SCOPE = "wrong_scope"
    NO_ENTITLEMENT = "no_entitlement"
    INSUFFICIENT_ROLE = "insufficient_role"
    UNVERIFIED_EXPORT_RIGHTS = "unverified_export_rights"


_GRANTS = {
    Role.VIEWER: frozenset({Permission.VIEW_PRODUCTS, Permission.VIEW_RESEARCH}),
    Role.ANALYST: frozenset(
        {Permission.VIEW_PRODUCTS, Permission.VIEW_RESEARCH, Permission.EXPORT_RESEARCH}
    ),
    Role.OWNER: frozenset(Permission),
}


def _identifier(value: str) -> bool:
    """Opaque, bounded and non-whitespace IDs only; never credentials."""
    return (
        type(value) is str
        and 0 < len(value) <= 256
        and value == value.strip()
        and all(32 < ord(char) < 127 for char in value)
    )


@dataclass(frozen=True, slots=True)
class Principal:
    """Trusted identity claim, NOT proof that anyone actually logged in."""

    subject: str = field(repr=False)
    tenant: str = field(repr=False)
    credential_revision: str = field(repr=False)
    role: Role
    status: MembershipStatus
    entitlements: frozenset[str]

    def __post_init__(self) -> None:
        if not all(
            _identifier(value)
            for value in (self.subject, self.tenant, self.credential_revision)
        ):
            raise ValueError("invalid principal identifiers")
        if type(self.role) is not Role or type(self.status) is not MembershipStatus:
            raise ValueError("validated role and membership status required")
        if type(self.entitlements) is not frozenset or not all(
            _identifier(value) for value in self.entitlements
        ):
            raise ValueError("validated immutable entitlement set required")


@dataclass(frozen=True, slots=True)
class Decision:
    """Internal audit decision. Never echo the reason to untrusted callers."""

    allowed: bool
    code: DecisionCode
    policy_version: str = POLICY_VERSION


class AccessDenied(PermissionError):
    """Sanitized exception; no tenant IDs, user IDs or entitlements disclosed."""


def evaluate(
    principal: Principal | None,
    scope: StorageScope,
    permission: Permission,
    *,
    synthetic: bool,
) -> Decision:
    """Authorization only; caller must verify the Principal's authenticity.

    Same-tenant and session-revision matches are mandatory even for owners.
    Exporting live/third-party financial research is NEVER authorized by this
    policy, independently of role, until data rights have a separate design.
    """
    if (
        type(scope) is not StorageScope
        or type(permission) is not Permission
        or type(synthetic) is not bool
    ):
        return Decision(False, DecisionCode.INVALID_CONTEXT)
    if type(principal) is not Principal:
        return Decision(False, DecisionCode.UNAUTHENTICATED)
    if principal.status is not MembershipStatus.ACTIVE:
        return Decision(False, DecisionCode.INACTIVE_MEMBERSHIP)
    if (
        principal.tenant != scope.tenant
        or principal.credential_revision != scope.credential_revision
    ):
        return Decision(False, DecisionCode.WRONG_SCOPE)
    if scope.entitlement not in principal.entitlements:
        return Decision(False, DecisionCode.NO_ENTITLEMENT)
    if permission not in _GRANTS[principal.role]:
        return Decision(False, DecisionCode.INSUFFICIENT_ROLE)
    if permission is Permission.EXPORT_RESEARCH and synthetic is False:
        return Decision(False, DecisionCode.UNVERIFIED_EXPORT_RIGHTS)
    return Decision(True, DecisionCode.ALLOW)


def require_permission(
    principal: Principal | None,
    scope: StorageScope,
    permission: Permission,
    *,
    synthetic: bool,
) -> None:
    """Fail closed with a deliberately generic message at service boundaries."""
    decision = evaluate(principal, scope, permission, synthetic=synthetic)
    if not decision.allowed:
        raise AccessDenied("access denied")
