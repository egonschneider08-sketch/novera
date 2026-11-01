"""Local identity and revocable sessions for Novera (NV-026, phase A).

Trust boundary: only a trusted local operator may create users or change
memberships. This module does NOT expose HTTP login, cookies, public sign-up,
an authentication middleware or a multi-tenant SaaS. The result of resolve()
is the only context this module derives from a *verified* session record.
Never build a Principal from arbitrary HTTP fields.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from novera.authorization import MembershipStatus, Principal, Role
from novera.storage import StorageScope

APPLICATION_ID = 0x4E4F5649  # NOVI, distinct from ObservationStore (NOVR).
SCHEMA_VERSION = 1
SESSION_TTL_SECONDS = 3600
MAX_SESSION_TTL_SECONDS = 86400
MAX_ACTIVE_SESSIONS = 8
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

_SCHEMA = (
    """CREATE TABLE users (
        subject TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        credential_revision TEXT NOT NULL,
        disabled INTEGER NOT NULL CHECK(disabled IN (0, 1))
    )""",
    """CREATE TABLE memberships (
        subject TEXT NOT NULL,
        tenant TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('viewer','analyst','owner')),
        status TEXT NOT NULL CHECK(status IN ('active','suspended')),
        PRIMARY KEY(subject,tenant),
        FOREIGN KEY(subject) REFERENCES users(subject) ON DELETE RESTRICT
    )""",
    """CREATE TABLE entitlements (
        subject TEXT NOT NULL,
        tenant TEXT NOT NULL,
        entitlement TEXT NOT NULL,
        PRIMARY KEY(subject,tenant,entitlement),
        FOREIGN KEY(subject,tenant) REFERENCES memberships(subject,tenant) ON DELETE CASCADE
    )""",
    """CREATE TABLE sessions (
        token_digest TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        tenant TEXT NOT NULL,
        credential_revision TEXT NOT NULL,
        issued_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL CHECK(expires_at > issued_at),
        revoked INTEGER NOT NULL CHECK(revoked IN (0, 1)),
        FOREIGN KEY(subject,tenant) REFERENCES memberships(subject,tenant) ON DELETE CASCADE
    )""",
    """CREATE INDEX sessions_by_member
        ON sessions(subject,tenant,revoked,expires_at,issued_at)""",
)


class IdentityError(RuntimeError):
    """Generic persistence / validation failure: no sensitive content in messages."""


class AuthenticationError(IdentityError):
    """Generic credential failure: never disclose whether an account exists."""


@dataclass(frozen=True, slots=True)
class SessionGrant:
    """Bearer secret is deliberately excluded from repr and str."""

    token: str = field(repr=False)
    expires_at: int


@dataclass(frozen=True, slots=True)
class AuthenticatedContext:
    """Created from a verified, non-revoked server-side session record only."""

    principal: Principal
    scope: StorageScope


def _identifier(value: object) -> str:
    if (
        type(value) is not str
        or not 0 < len(value) <= 128
        or value != value.strip()
        or any(not 32 < ord(char) < 127 for char in value)
    ):
        raise IdentityError("invalid identity context")
    return value


def _password(value: object) -> str:
    # Never normalize, truncate or log passwords: a different secret must
    # never accidentally verify as the same one.
    if (
        type(value) is not str
        or not 12 <= len(value) <= 128
        or len(value.encode("utf-8")) > 1024
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise IdentityError("password does not meet local requirements")
    return value


def _digest(token: object) -> str | None:
    if type(token) is not str or not _TOKEN.fullmatch(token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _dummy_hash() -> str:
    # Hash once per Python process to reduce account-enumeration timing
    # differences. This is not a replacement for HTTP rate limiting.
    if not hasattr(_dummy_hash, "_cached"):
        _dummy_hash._cached = _HASHER.hash("internal-non-account-password-only")
    return _dummy_hash._cached


class IdentityStore:
    """One SQLite connection per thread. Trust creation/membership calls only.

    Never open user-controlled database paths; use trusted local absolute paths
    and a filesystem ACL restricted to the service account. On POSIX this
    implementation rejects an existing file readable by group/others.
    """

    def __init__(self, connection: sqlite3.Connection, *, now: Callable[[], int] = None):
        self._db = connection
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA synchronous=FULL")
        self._now = now if now is not None else lambda: int(time.time())
        if not callable(self._now):
            self._db.close()
            raise IdentityError("invalid clock")

    @classmethod
    def memory(cls, *, now: Callable[[], int] = None) -> IdentityStore:
        store = cls(sqlite3.connect(":memory:", isolation_level=None), now=now)
        store._initialize()
        return store

    @classmethod
    def local(
        cls,
        path: Path,
        *,
        create: bool = False,
        now: Callable[[], int] = None,
    ) -> IdentityStore:
        path = Path(path)
        if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
            raise IdentityError("absolute local database path required")
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise IdentityError("linked identity database paths are not supported")
        if create:
            # Atomic exclusive create with owner-only permissions on POSIX.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise IdentityError("identity database permissions are too broad")
        try:
            connection = sqlite3.connect(
                path.as_uri() + "?mode=rw",
                uri=True,
                isolation_level=None,
                timeout=5,
            )
        except sqlite3.Error:
            raise IdentityError("identity database unavailable") from None
        store = cls(connection, now=now)
        try:
            if create:
                store._initialize()
            store._check_schema()
            return store
        except Exception:
            store.close()
            raise IdentityError("unsupported or invalid identity database") from None

    def __enter__(self) -> IdentityStore:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def _initialize(self) -> None:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            for statement in _SCHEMA:
                self._db.execute(statement)
            self._db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def _check_schema(self) -> None:
        app = self._db.execute("PRAGMA application_id").fetchone()[0]
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        actual = {
            row[0]
            for row in self._db.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        if app != APPLICATION_ID or version != SCHEMA_VERSION or actual != set(_SCHEMA):
            raise IdentityError("unsupported identity database schema")

    def _clock(self) -> int:
        stamp = self._now()
        if type(stamp) is not int or stamp < 0:
            raise IdentityError("invalid clock")
        return stamp

    def create_user(self, subject: str, password: str) -> None:
        """Trusted-operator provision only; no anonymous public sign-up."""
        subject = _identifier(subject)
        password = _password(password)
        digest = _HASHER.hash(password)
        revision = secrets.token_hex(16)
        try:
            with self._db:
                self._db.execute(
                    "INSERT INTO users VALUES (?,?,?,0)", (subject, digest, revision)
                )
        except sqlite3.Error:
            raise IdentityError("unable to provision identity") from None

    def set_membership(
        self,
        subject: str,
        tenant: str,
        role: Role,
        entitlements: frozenset[str],
        *,
        status: MembershipStatus = MembershipStatus.ACTIVE,
    ) -> None:
        """Trusted-operator update; revokes every prior session for this tenant."""
        subject, tenant = _identifier(subject), _identifier(tenant)
        if type(role) is not Role or type(status) is not MembershipStatus:
            raise IdentityError("invalid membership")
        if (
            type(entitlements) is not frozenset
            or not entitlements
            or any(_identifier(value) != value for value in entitlements)
        ):
            raise IdentityError("invalid entitlements")
        try:
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute(
                "INSERT INTO memberships(subject,tenant,role,status) VALUES (?,?,?,?) "
                "ON CONFLICT(subject,tenant) DO UPDATE SET role=excluded.role, "
                "status=excluded.status",
                (subject, tenant, role.value, status.value),
            )
            self._db.execute(
                "DELETE FROM entitlements WHERE subject=? AND tenant=?", (subject, tenant)
            )
            self._db.executemany(
                "INSERT INTO entitlements VALUES (?,?,?)",
                [(subject, tenant, item) for item in sorted(entitlements)],
            )
            self._db.execute(
                "UPDATE sessions SET revoked=1 WHERE subject=? AND tenant=?",
                (subject, tenant),
            )
            self._db.commit()
        except sqlite3.Error:
            self._db.rollback()
            raise IdentityError("unable to update membership") from None

    def set_disabled(self, subject: str, *, disabled: bool) -> None:
        """Trusted-operator suspension revokes all sessions across all tenants."""
        subject = _identifier(subject)
        if type(disabled) is not bool:
            raise IdentityError("invalid identity state")
        try:
            with self._db:
                cursor = self._db.execute(
                    "UPDATE users SET disabled=? WHERE subject=?", (int(disabled), subject)
                )
                if cursor.rowcount != 1:
                    raise IdentityError("identity not found")
                self._db.execute("UPDATE sessions SET revoked=1 WHERE subject=?", (subject,))
        except sqlite3.Error:
            raise IdentityError("unable to update identity") from None

    def issue_session(
        self,
        subject: str,
        password: str,
        tenant: str,
        *,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> SessionGrant:
        """Verify Argon2id secret and active tenant membership before issuing.

        This internal method has no network-facing rate limit. Do not expose it
        over HTTP until a separate anti-bruteforce and abuse-control layer exists.
        """
        subject, tenant = _identifier(subject), _identifier(tenant)
        if type(password) is not str or len(password.encode("utf-8")) > 1024:
            raise AuthenticationError("invalid credentials")
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= MAX_SESSION_TTL_SECONDS:
            raise IdentityError("invalid session policy")
        row = self._db.execute(
            "SELECT u.password_hash,u.credential_revision,u.disabled,m.status "
            "FROM users u LEFT JOIN memberships m ON m.subject=u.subject AND m.tenant=? "
            "WHERE u.subject=?",
            (tenant, subject),
        ).fetchone()
        try:
            _HASHER.verify(row["password_hash"] if row is not None else _dummy_hash(), password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            raise AuthenticationError("invalid credentials") from None
        if row is None or row["disabled"] or row["status"] != MembershipStatus.ACTIVE:
            raise AuthenticationError("invalid credentials")

        now = self._clock()
        token = secrets.token_urlsafe(32)
        digest = _digest(token)
        if digest is None:
            raise IdentityError("session generation failed")
        try:
            self._db.execute("BEGIN IMMEDIATE")
            # Concurrent membership/password changes are rechecked under the
            # SQLite writer lock, after password verification.
            valid = self._db.execute(
                "SELECT 1 FROM users u JOIN memberships m ON m.subject=u.subject "
                "WHERE u.subject=? AND m.tenant=? AND m.status='active' "
                "AND u.disabled=0 AND u.credential_revision=?",
                (subject, tenant, row["credential_revision"]),
            ).fetchone()
            if valid is None:
                raise AuthenticationError("invalid credentials")
            self._db.execute(
                "UPDATE sessions SET revoked=1 WHERE subject=? AND tenant=? AND expires_at<=?",
                (subject, tenant, now),
            )
            self._db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,0)",
                (digest, subject, tenant, row["credential_revision"], now, now + ttl_seconds),
            )
            # Bound the number of active sessions on a user+tenant.
            active = self._db.execute(
                "SELECT token_digest FROM sessions WHERE subject=? AND tenant=? "
                "AND revoked=0 ORDER BY issued_at DESC, rowid DESC",
                (subject, tenant),
            ).fetchall()
            for older in active[MAX_ACTIVE_SESSIONS:]:
                self._db.execute(
                    "UPDATE sessions SET revoked=1 WHERE token_digest=?",
                    (older["token_digest"],),
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise AuthenticationError("invalid credentials") from None
        return SessionGrant(token=token, expires_at=now + ttl_seconds)

    def resolve(
        self,
        token: str,
        *,
        tenant: str,
        entitlement: str,
    ) -> AuthenticatedContext | None:
        """Derive server-side authorization context from a live session.

        Tenant/entitlement MUST be the trusted resource scope, not unverified
        claims sent by a browser. Returns None on *any* failed check.
        """
        digest = _digest(token)
        try:
            tenant, entitlement = _identifier(tenant), _identifier(entitlement)
            now = self._clock()
        except IdentityError:
            return None
        if digest is None:
            return None
        row = self._db.execute(
            "SELECT s.subject,s.tenant,s.credential_revision,s.expires_at,"
            "u.credential_revision AS current_revision,u.disabled,"
            "m.role,m.status "
            "FROM sessions s JOIN users u ON u.subject=s.subject "
            "JOIN memberships m ON m.subject=s.subject AND m.tenant=s.tenant "
            "WHERE s.token_digest=? AND s.tenant=? AND s.revoked=0",
            (digest, tenant),
        ).fetchone()
        if (
            row is None
            or row["expires_at"] <= now
            or row["disabled"] != 0
            or row["credential_revision"] != row["current_revision"]
            or row["status"] != MembershipStatus.ACTIVE
        ):
            return None
        rights = self._db.execute(
            "SELECT entitlement FROM entitlements WHERE subject=? AND tenant=?",
            (row["subject"], tenant),
        ).fetchall()
        granted = frozenset(item["entitlement"] for item in rights)
        if entitlement not in granted:
            return None
        try:
            principal = Principal(
                subject=row["subject"],
                tenant=tenant,
                credential_revision=row["current_revision"],
                role=Role(row["role"]),
                status=MembershipStatus(row["status"]),
                entitlements=granted,
            )
            scope = StorageScope(tenant, entitlement, row["current_revision"])
            return AuthenticatedContext(principal=principal, scope=scope)
        except (ValueError, TypeError):
            return None

    def revoke_session(self, token: str) -> None:
        """Idempotent logout: never disclose if a bearer secret existed."""
        digest = _digest(token)
        if digest is not None:
            with self._db:
                self._db.execute(
                    "UPDATE sessions SET revoked=1 WHERE token_digest=?", (digest,)
                )

    def change_password(self, subject: str, old_password: str, new_password: str) -> None:
        """Rotate hash and credential revision; revoke all sessions atomically."""
        subject = _identifier(subject)
        new_password = _password(new_password)
        if type(old_password) is not str:
            raise AuthenticationError("invalid credentials")
        row = self._db.execute(
            "SELECT password_hash,credential_revision,disabled FROM users WHERE subject=?",
            (subject,),
        ).fetchone()
        try:
            _HASHER.verify(
                row["password_hash"] if row is not None else _dummy_hash(),
                old_password,
            )
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            raise AuthenticationError("invalid credentials") from None
        if row is None or row["disabled"]:
            raise AuthenticationError("invalid credentials")
        hashed = _HASHER.hash(new_password)
        revision = secrets.token_hex(16)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            changed = self._db.execute(
                "UPDATE users SET password_hash=?,credential_revision=? "
                "WHERE subject=? AND credential_revision=? AND disabled=0",
                (hashed, revision, subject, row["credential_revision"]),
            )
            if changed.rowcount != 1:
                raise AuthenticationError("invalid credentials")
            self._db.execute("UPDATE sessions SET revoked=1 WHERE subject=?", (subject,))
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise AuthenticationError("invalid credentials") from None
