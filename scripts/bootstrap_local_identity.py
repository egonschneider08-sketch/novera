"""Interactive local identity bootstrap; deliberately no password CLI arguments.

Only trusted machine operators should run this script. It cannot authenticate
HTTP users and intentionally refuses to overwrite an existing identity database.
"""

from __future__ import annotations

import argparse
import getpass
import hmac
import sys
from pathlib import Path

from novera.authorization import Role
from novera.identity import IdentityError, IdentityStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision the first LOCAL Novera account (no hosted login)."
    )
    parser.add_argument("--database", type=Path, required=True, help="New absolute SQLite path")
    parser.add_argument("--subject", required=True, help="Opaque internal user ID")
    parser.add_argument("--tenant", required=True, help="Opaque internal organization ID")
    parser.add_argument("--entitlement", required=True, help="Initial allowed research scope")
    args = parser.parse_args(argv)
    if not args.database.is_absolute():
        parser.error("--database must be an absolute path")
    if args.database.exists():
        print("Local identity bootstrap rejected; target already exists.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        parser.error("bootstrap requires an interactive terminal; no password piping")
    first = getpass.getpass("New local password (12+ characters): ")
    second = getpass.getpass("Confirm new local password: ")
    if not hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8")):
        print("Local identity bootstrap rejected.", file=sys.stderr)
        return 1
    try:
        with IdentityStore.local(args.database, create=True) as store:
            store.create_user(args.subject, first)
            store.set_membership(
                args.subject,
                args.tenant,
                Role.OWNER,
                frozenset({args.entitlement}),
            )
    except (OSError, IdentityError, FileExistsError):
        print(
            "Local identity bootstrap rejected; check permissions and target path.", file=sys.stderr
        )
        return 1
    print("Local identity provisioned. No HTTP login or session endpoint exists yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
