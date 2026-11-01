"""NV-026 phase A: isolated local identity and credential-backed principals."""

import os
import socket
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from novera.authorization import (
    MembershipStatus,
    Permission,
    Role,
    evaluate,
    require_permission,
)
from novera.identity import (
    APPLICATION_ID,
    SCHEMA_VERSION,
    AuthenticatedContext,
    AuthenticationError,
    IdentityError,
    IdentityStore,
    SessionGrant,
)

NOW = [1_800_000_000]
PHRASE = "correct horse battery!2026"
ROTATED_PHRASE = "a new independent passphrase!2026"


@pytest.fixture
def store():
    NOW[0] = 1_800_000_000
    with IdentityStore.memory(now=lambda: NOW[0]) as db:
        yield db


@pytest.fixture
def configured(store):
    store.create_user("analyst-a", PHRASE)
    store.set_membership("analyst-a", "company-a", Role.ANALYST, frozenset({"research", "demo"}))
    return store


def test_fresh_store_has_no_default_accounts_or_sessions(store):
    with pytest.raises(AuthenticationError, match="invalid credentials"):
        store.issue_session("admin", "admin-password", "company-a")
    assert store.resolve("invalid", tenant="company-a", entitlement="research") is None


def test_hash_uses_argon2id_strong_params_with_unique_salt(configured):
    row = configured._db.execute(
        "SELECT password_hash FROM users WHERE subject=?", ("analyst-a",)
    ).fetchone()
    assert row["password_hash"].startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert PHRASE not in row["password_hash"]
    assert PasswordHasher().verify(row["password_hash"], PHRASE)
    assert (
        configured._db.execute(
            "SELECT password_hash FROM users WHERE subject='unlisted'"
        ).fetchone()
        is None
    )
    configured.create_user("analyst-b", PHRASE)
    second = configured._db.execute(
        "SELECT password_hash FROM users WHERE subject='analyst-b'"
    ).fetchone()["password_hash"]
    assert second != row["password_hash"]


def test_valid_password_issues_secret_that_is_not_stored_in_plaintext(configured):
    grant = configured.issue_session("analyst-a", PHRASE, "company-a", ttl_seconds=120)
    assert type(grant) is SessionGrant
    assert len(grant.token) == 43
    assert grant.expires_at == NOW[0] + 120
    assert grant.token not in repr(grant)
    assert PHRASE not in repr(grant)
    rows = configured._db.execute("SELECT * FROM sessions").fetchall()
    assert len(rows) == 1
    assert len(rows[0]["token_digest"]) == 64
    assert rows[0]["token_digest"] != grant.token
    assert grant.token not in str(tuple(rows[0]))


def test_verified_session_yields_precise_tenant_rbac_context(configured):
    grant = configured.issue_session("analyst-a", PHRASE, "company-a")
    context = configured.resolve(grant.token, tenant="company-a", entitlement="research")
    assert type(context) is AuthenticatedContext
    assert context.principal.role is Role.ANALYST
    assert context.principal.subject == "analyst-a"
    assert context.principal.tenant == "company-a"
    assert context.scope.tenant == "company-a"
    assert context.scope.credential_revision == context.principal.credential_revision
    assert context.principal.entitlements == frozenset({"research", "demo"})
    require_permission(context.principal, context.scope, Permission.VIEW_RESEARCH, synthetic=True)
    assert (
        evaluate(
            context.principal, context.scope, Permission.EXPORT_RESEARCH, synthetic=False
        ).allowed
        is False
    )


@pytest.mark.parametrize("token", ["", "x", " " * 43, "a" * 44, 1234, None, "a" * 42 + "="])
def test_untrusted_or_invalid_bearer_secret_never_authenticates(configured, token):
    assert configured.resolve(token, tenant="company-a", entitlement="research") is None


@pytest.mark.parametrize(
    ("tenant", "entitlement"),
    [
        ("company-b", "research"),
        ("company-a", "premium"),
        ("company-b", "demo"),
        ("company-a", "research' OR 1=1 --"),
        ("company-a", ""),
    ],
)
def test_cross_tenant_or_outside_entitlement_is_not_authorized(configured, tenant, entitlement):
    grant = configured.issue_session("analyst-a", PHRASE, "company-a")
    assert configured.resolve(grant.token, tenant=tenant, entitlement=entitlement) is None


def test_same_user_multiple_tenants_have_independent_sessions(configured):
    configured.set_membership("analyst-a", "company-b", Role.VIEWER, frozenset({"research"}))
    token_a = configured.issue_session("analyst-a", PHRASE, "company-a")
    token_b = configured.issue_session("analyst-a", PHRASE, "company-b")
    ctx_a = configured.resolve(token_a.token, tenant="company-a", entitlement="research")
    ctx_b = configured.resolve(token_b.token, tenant="company-b", entitlement="research")
    assert ctx_a.principal.role is Role.ANALYST
    assert ctx_b.principal.role is Role.VIEWER
    assert configured.resolve(token_a.token, tenant="company-b", entitlement="research") is None
    assert configured.resolve(token_b.token, tenant="company-a", entitlement="research") is None


@pytest.mark.parametrize("password", ["not-the-passphrase", "", "other", "x" * 1025])
def test_wrong_password_generic_failure(configured, password):
    with pytest.raises(AuthenticationError, match="invalid credentials"):
        configured.issue_session("analyst-a", password, "company-a")


def test_unknown_user_error_is_not_an_account_enumeration_oracle(configured):
    with pytest.raises(AuthenticationError) as known:
        configured.issue_session("analyst-a", "bad credentials", "company-a")
    with pytest.raises(AuthenticationError) as unknown:
        configured.issue_session("unknown-a", "bad credentials", "company-a")
    assert str(known.value) == str(unknown.value) == "invalid credentials"
    assert PHRASE not in str(known.value)


def test_session_expiry_and_explicit_revocation(configured):
    token = configured.issue_session("analyst-a", PHRASE, "company-a", ttl_seconds=60)
    NOW[0] += 59
    assert configured.resolve(token.token, tenant="company-a", entitlement="demo") is not None
    NOW[0] += 1
    assert configured.resolve(token.token, tenant="company-a", entitlement="demo") is None
    next_token = configured.issue_session("analyst-a", PHRASE, "company-a")
    configured.revoke_session(next_token.token)
    configured.revoke_session(next_token.token)
    configured.revoke_session("invalid")
    assert configured.resolve(next_token.token, tenant="company-a", entitlement="demo") is None


def test_session_limit_retires_oldest_session_deterministically(configured):
    grants = []
    for _ in range(10):
        grants.append(configured.issue_session("analyst-a", PHRASE, "company-a"))
        NOW[0] += 1
    assert configured.resolve(grants[0].token, tenant="company-a", entitlement="demo") is None
    assert configured.resolve(grants[1].token, tenant="company-a", entitlement="demo") is None
    assert configured.resolve(grants[-1].token, tenant="company-a", entitlement="demo")


@pytest.mark.parametrize("ttl", [-1, 0, 59, 86401, True, None, 1.0])
def test_invalid_session_ttl_is_rejected(configured, ttl):
    with pytest.raises(IdentityError, match="session policy"):
        configured.issue_session("analyst-a", PHRASE, "company-a", ttl_seconds=ttl)


def test_membership_role_change_revokes_old_session_before_new_role_applies(configured):
    old = configured.issue_session("analyst-a", PHRASE, "company-a")
    configured.set_membership("analyst-a", "company-a", Role.OWNER, frozenset({"research"}))
    assert configured.resolve(old.token, tenant="company-a", entitlement="research") is None
    new = configured.issue_session("analyst-a", PHRASE, "company-a")
    context = configured.resolve(new.token, tenant="company-a", entitlement="research")
    assert context.principal.role is Role.OWNER
    assert evaluate(
        context.principal, context.scope, Permission.MANAGE_USERS, synthetic=True
    ).allowed


def test_suspended_membership_rejects_new_and_existing_sessions(configured):
    old = configured.issue_session("analyst-a", PHRASE, "company-a")
    configured.set_membership(
        "analyst-a",
        "company-a",
        Role.ANALYST,
        frozenset({"research"}),
        status=MembershipStatus.SUSPENDED,
    )
    assert configured.resolve(old.token, tenant="company-a", entitlement="research") is None
    with pytest.raises(AuthenticationError):
        configured.issue_session("analyst-a", PHRASE, "company-a")


def test_entitlement_revocation_fails_closed(configured):
    grant = configured.issue_session("analyst-a", PHRASE, "company-a")
    configured.set_membership("analyst-a", "company-a", Role.ANALYST, frozenset({"demo"}))
    assert configured.resolve(grant.token, tenant="company-a", entitlement="research") is None
    new = configured.issue_session("analyst-a", PHRASE, "company-a")
    assert configured.resolve(new.token, tenant="company-a", entitlement="research") is None
    assert configured.resolve(new.token, tenant="company-a", entitlement="demo") is not None


def test_disable_user_revokes_all_tenants_and_rejects_reauthentication(configured):
    configured.set_membership("analyst-a", "company-b", Role.VIEWER, frozenset({"demo"}))
    a = configured.issue_session("analyst-a", PHRASE, "company-a")
    b = configured.issue_session("analyst-a", PHRASE, "company-b")
    configured.set_disabled("analyst-a", disabled=True)
    assert configured.resolve(a.token, tenant="company-a", entitlement="demo") is None
    assert configured.resolve(b.token, tenant="company-b", entitlement="demo") is None
    with pytest.raises(AuthenticationError):
        configured.issue_session("analyst-a", PHRASE, "company-a")
    configured.set_disabled("analyst-a", disabled=False)
    assert configured.resolve(a.token, tenant="company-a", entitlement="demo") is None


def test_password_change_rotates_revision_and_invalidates_all_old_tokens(configured):
    a = configured.issue_session("analyst-a", PHRASE, "company-a")
    old = configured.resolve(a.token, tenant="company-a", entitlement="research")
    configured.change_password("analyst-a", PHRASE, ROTATED_PHRASE)
    assert configured.resolve(a.token, tenant="company-a", entitlement="research") is None
    with pytest.raises(AuthenticationError):
        configured.issue_session("analyst-a", PHRASE, "company-a")
    b = configured.issue_session("analyst-a", ROTATED_PHRASE, "company-a")
    new = configured.resolve(b.token, tenant="company-a", entitlement="research")
    assert new.principal.credential_revision != old.principal.credential_revision
    assert new.scope.credential_revision == new.principal.credential_revision


def test_wrong_old_password_never_changes_hash_or_revokes_valid_session(configured):
    grant = configured.issue_session("analyst-a", PHRASE, "company-a")
    with pytest.raises(AuthenticationError):
        configured.change_password("analyst-a", "incorrect", ROTATED_PHRASE)
    assert configured.resolve(grant.token, tenant="company-a", entitlement="demo") is not None


@pytest.mark.parametrize("new", ["short", "", " " * 2, "a" * 129, "foo\nbar long enough"])
def test_weak_or_invalid_new_password_is_rejected(configured, new):
    with pytest.raises(IdentityError):
        configured.change_password("analyst-a", PHRASE, new)


def test_provision_uses_strict_immutable_membership_and_no_sql_injection(store):
    store.create_user("someone", PHRASE)
    with pytest.raises(IdentityError):
        store.set_membership("someone", "company-a", "owner", frozenset({"demo"}))
    with pytest.raises(IdentityError):
        store.set_membership("someone", "company-a", Role.OWNER, {"demo"})
    store.set_membership("someone", "company-a", Role.VIEWER, frozenset({"demo"}))
    with pytest.raises(IdentityError):
        store.create_user("someone", PHRASE)
    with pytest.raises(IdentityError):
        store.set_membership("unknown", "company-a", Role.OWNER, frozenset({"demo"}))
    with pytest.raises(AuthenticationError):
        store.issue_session("someone'OR'1'='1", PHRASE, "company-a")
    assert store.issue_session("someone", PHRASE, "company-a")


@pytest.mark.parametrize(
    "subject", ["", " ", " leading", "trailing ", "line\nbreak", "a" * 129, 42]
)
def test_invalid_subjects_never_provision_users(store, subject):
    with pytest.raises(IdentityError):
        store.create_user(subject, PHRASE)
    assert store._db.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_create_exclusive_reopen_and_idempotent_session_lookup(tmp_path):
    path = (tmp_path / "identity.sqlite3").absolute()
    with IdentityStore.local(path, create=True, now=lambda: NOW[0]) as first:
        first.create_user("analyst-a", PHRASE)
        first.set_membership("analyst-a", "company-a", Role.ANALYST, frozenset({"demo"}))
        token = first.issue_session("analyst-a", PHRASE, "company-a")
        assert first._db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert first._db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    with IdentityStore.local(path, now=lambda: NOW[0]) as reopened:
        assert reopened.resolve(token.token, tenant="company-a", entitlement="demo")
        reopened.revoke_session(token.token)
        assert reopened.resolve(token.token, tenant="company-a", entitlement="demo") is None
    with pytest.raises(FileExistsError):
        IdentityStore.local(path, create=True)


def test_no_implicit_creation_and_unknown_schema_is_rejected(tmp_path):
    path = (tmp_path / "identity.sqlite3").absolute()
    with pytest.raises(IdentityError):
        IdentityStore.local(path)
    assert not path.exists()
    with IdentityStore.local(path, create=True):
        pass
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE surprise(x)")
    with pytest.raises(IdentityError, match="schema"):
        IdentityStore.local(path)


@pytest.mark.parametrize("mutation", ["PRAGMA user_version=999", "PRAGMA application_id=1"])
def test_schema_version_or_application_id_tamper_is_rejected(tmp_path, mutation):
    path = (tmp_path / "identity.sqlite3").absolute()
    with IdentityStore.local(path, create=True):
        pass
    with sqlite3.connect(path) as db:
        db.execute(mutation)
    with pytest.raises(IdentityError):
        IdentityStore.local(path)


def test_linked_or_relative_paths_cannot_be_used_for_identity_database(tmp_path):
    with pytest.raises(IdentityError, match="absolute"):
        IdentityStore.local(Path("identity.sqlite3"), create=True)
    actual = tmp_path / "actual.sqlite3"
    with IdentityStore.local(actual, create=True):
        pass
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(actual)
    with pytest.raises(IdentityError, match="linked"):
        IdentityStore.local(alias)


@pytest.mark.skipif(os.name != "posix", reason="POSIX only")
def test_world_readable_database_file_is_refused(tmp_path):
    path = tmp_path / "identity.sqlite3"
    with IdentityStore.local(path, create=True):
        pass
    assert path.stat().st_mode & 0o077 == 0
    path.chmod(0o644)
    with pytest.raises(IdentityError, match="permissions"):
        IdentityStore.local(path)
    path.chmod(0o600)


def test_sqlite_does_not_write_plaintext_passwords_or_bearer_tokens(configured):
    token = configured.issue_session("analyst-a", PHRASE, "company-a")
    dump = "\n".join(configured._db.iterdump())
    assert PHRASE not in dump
    assert token.token not in dump
    assert "$argon2id$" in dump


def test_revoked_digest_cannot_be_replayed_and_context_cannot_be_mutated(configured):
    grant = configured.issue_session("analyst-a", PHRASE, "company-a")
    context = configured.resolve(grant.token, tenant="company-a", entitlement="demo")
    with pytest.raises(FrozenInstanceError):
        context.scope = None
    configured.revoke_session(grant.token)
    assert configured.resolve(grant.token, tenant="company-a", entitlement="demo") is None


def test_offline_security_boundary_has_no_network_calls(configured, monkeypatch):
    def no_connect(*args, **kwargs):
        raise AssertionError("external socket attempted")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    grant = configured.issue_session("analyst-a", PHRASE, "company-a")
    assert configured.resolve(grant.token, tenant="company-a", entitlement="demo")
    configured.revoke_session(grant.token)
