"""Tenant RBAC contract matrix: no authentication/HTTP/database involved."""

from dataclasses import replace

import pytest

from novera.authorization import (
    POLICY_VERSION,
    AccessDenied,
    DecisionCode,
    MembershipStatus,
    Permission,
    Principal,
    Role,
    evaluate,
    require_permission,
)
from novera.storage import StorageScope

SCOPE = StorageScope("company-a", "research-basic", "session-v1")


def member(role=Role.VIEWER, *, status=MembershipStatus.ACTIVE):
    return Principal(
        subject="user-a",
        tenant="company-a",
        credential_revision="session-v1",
        role=role,
        status=status,
        entitlements=frozenset({"research-basic", "demo"}),
    )


@pytest.mark.parametrize(
    ("role", "permission", "expected"),
    [
        (Role.VIEWER, Permission.VIEW_PRODUCTS, True),
        (Role.VIEWER, Permission.VIEW_RESEARCH, True),
        (Role.VIEWER, Permission.EXPORT_RESEARCH, False),
        (Role.VIEWER, Permission.MANAGE_PRODUCTS, False),
        (Role.VIEWER, Permission.MANAGE_USERS, False),
        (Role.VIEWER, Permission.MANAGE_ENTITLEMENTS, False),
        (Role.ANALYST, Permission.VIEW_PRODUCTS, True),
        (Role.ANALYST, Permission.VIEW_RESEARCH, True),
        (Role.ANALYST, Permission.EXPORT_RESEARCH, True),
        (Role.ANALYST, Permission.MANAGE_PRODUCTS, False),
        (Role.ANALYST, Permission.MANAGE_USERS, False),
        (Role.ANALYST, Permission.MANAGE_ENTITLEMENTS, False),
        (Role.OWNER, Permission.VIEW_PRODUCTS, True),
        (Role.OWNER, Permission.VIEW_RESEARCH, True),
        (Role.OWNER, Permission.EXPORT_RESEARCH, True),
        (Role.OWNER, Permission.MANAGE_PRODUCTS, True),
        (Role.OWNER, Permission.MANAGE_USERS, True),
        (Role.OWNER, Permission.MANAGE_ENTITLEMENTS, True),
    ],
)
def test_explicit_role_permission_matrix_for_synthetic_records(role, permission, expected):
    result = evaluate(member(role), SCOPE, permission, synthetic=True)
    assert result.allowed is expected
    assert result.code is (DecisionCode.ALLOW if expected else DecisionCode.INSUFFICIENT_ROLE)
    assert result.policy_version == POLICY_VERSION


@pytest.mark.parametrize(
    "role",
    [Role.VIEWER, Role.ANALYST, Role.OWNER],
)
def test_real_export_never_allowed_even_for_owner(role):
    result = evaluate(member(role), SCOPE, Permission.EXPORT_RESEARCH, synthetic=False)
    assert not result.allowed
    assert result.code in (
        DecisionCode.UNVERIFIED_EXPORT_RIGHTS,
        DecisionCode.INSUFFICIENT_ROLE,
    )


def test_anonymous_or_fake_claim_does_not_gain_tenant_resource_access():
    assert evaluate(None, SCOPE, Permission.VIEW_PRODUCTS, synthetic=True).code is (
        DecisionCode.UNAUTHENTICATED
    )
    assert evaluate("owner", SCOPE, Permission.VIEW_RESEARCH, synthetic=True).allowed is False
    with pytest.raises(AccessDenied, match="access denied"):
        require_permission(None, SCOPE, Permission.VIEW_RESEARCH, synthetic=True)


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (StorageScope("company-b", "research-basic", "session-v1"), DecisionCode.WRONG_SCOPE),
        (StorageScope("company-a", "research-basic", "session-v2"), DecisionCode.WRONG_SCOPE),
        (StorageScope("company-a", "advanced", "session-v1"), DecisionCode.NO_ENTITLEMENT),
    ],
)
def test_tenant_entitlement_and_session_revision_must_match(scope, expected):
    decision = evaluate(member(Role.OWNER), scope, Permission.MANAGE_USERS, synthetic=True)
    assert decision.code is expected
    assert not decision.allowed


def test_revoked_entitlement_is_fail_closed():
    principal = replace(member(Role.OWNER), entitlements=frozenset({"demo"}))
    assert evaluate(
        principal, SCOPE, Permission.MANAGE_USERS, synthetic=True
    ).code is DecisionCode.NO_ENTITLEMENT


@pytest.mark.parametrize(
    "role",
    [Role.VIEWER, Role.ANALYST, Role.OWNER],
)
def test_suspended_membership_blocks_even_read_only_access(role):
    principal = member(role, status=MembershipStatus.SUSPENDED)
    assert evaluate(
        principal, SCOPE, Permission.VIEW_PRODUCTS, synthetic=True
    ).code is DecisionCode.INACTIVE_MEMBERSHIP


def test_require_permission_never_echoes_tenant_or_user_identifiers():
    principal = replace(member(Role.VIEWER), tenant="company-b")
    with pytest.raises(AccessDenied) as caught:
        require_permission(
            principal, SCOPE, Permission.VIEW_RESEARCH, synthetic=True
        )
    assert str(caught.value) == "access denied"
    assert "company-a" not in str(caught.value)
    assert "company-b" not in str(caught.value)


@pytest.mark.parametrize(
    "subject",
    ["", " ", " leading", "trailing ", "break\nline", "x" * 257],
)
def test_invalid_principal_identifiers_rejected_on_construction(subject):
    with pytest.raises(ValueError):
        replace(member(), subject=subject)


@pytest.mark.parametrize(
    "entitlements",
    [
        {"research-basic"},
        frozenset({""}),
        frozenset({"\t"}),
        frozenset({"n" * 257}),
        frozenset({99}),
    ],
)
def test_non_immutable_or_invalid_entitlement_sets_rejected(entitlements):
    with pytest.raises(ValueError):
        replace(member(), entitlements=entitlements)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "owner"),
        ("status", "active"),
        ("role", None),
        ("status", True),
    ],
)
def test_forged_role_or_status_literals_rejected(field, value):
    with pytest.raises(ValueError):
        replace(member(), **{field: value})


def test_invalid_permission_or_synthetic_flag_fail_closed():
    principal = member(Role.OWNER)
    assert evaluate(principal, SCOPE, "manage_users", synthetic=True).code is (
        DecisionCode.INVALID_CONTEXT
    )
    assert evaluate(principal, SCOPE, Permission.VIEW_RESEARCH, synthetic="true").code is (
        DecisionCode.INVALID_CONTEXT
    )
    assert evaluate(principal, "company-a", Permission.VIEW_RESEARCH, synthetic=True).code is (
        DecisionCode.INVALID_CONTEXT
    )


def test_mutated_frozen_principal_or_scope_are_revalidated_each_time():
    principal = member(Role.OWNER)
    object.__setattr__(principal, "role", "owner")
    assert evaluate(
        principal, SCOPE, Permission.MANAGE_USERS, synthetic=True
    ).code is DecisionCode.INVALID_CONTEXT

    scope = StorageScope("company-a", "research-basic", "session-v1")
    object.__setattr__(scope, "tenant", "")
    assert evaluate(
        member(Role.OWNER), scope, Permission.VIEW_PRODUCTS, synthetic=True
    ).code is DecisionCode.INVALID_CONTEXT


def test_evaluate_is_deterministic_pure_policy_and_never_grants_cross_tenant_owner():
    owner = member(Role.OWNER)
    wrong_tenant = StorageScope("company-c", "demo", "session-v1")
    assert evaluate(owner, wrong_tenant, Permission.MANAGE_ENTITLEMENTS, synthetic=False) == (
        evaluate(owner, wrong_tenant, Permission.MANAGE_ENTITLEMENTS, synthetic=False)
    )
    assert not evaluate(owner, wrong_tenant, Permission.MANAGE_ENTITLEMENTS, synthetic=False).allowed


def test_positive_require_permission_return_has_no_authentication_side_effects():
    assert require_permission(member(Role.ANALYST), SCOPE, Permission.VIEW_RESEARCH,
                              synthetic=True) is None
