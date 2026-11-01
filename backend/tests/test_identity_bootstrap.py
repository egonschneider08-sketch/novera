"""Local bootstrap security: interactive only, never overwrites or echoes secrets."""

import importlib.util
import sys
from pathlib import Path

import pytest
from novera.authorization import Permission, require_permission
from novera.identity import IdentityStore

BOOTSTRAP = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_local_identity.py"
PHRASE = "local synthetic passphrase!1234"


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("novera_local_bootstrap_test", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(path):
    return [
        "--database",
        str(path),
        "--subject",
        "operator-a",
        "--tenant",
        "lab-a",
        "--entitlement",
        "research-demo",
    ]


def test_local_bootstrap_interactive_creates_only_owner_but_no_http_login(
    tmp_path, monkeypatch, capsys
):
    app = _load_bootstrap()

    class Interactive:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Interactive())
    prompts = []
    answers = iter([PHRASE, PHRASE])

    def answer(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr(app.getpass, "getpass", answer)
    path = (tmp_path / "new-identity.sqlite3").absolute()
    assert app.main(_args(path)) == 0
    messages = capsys.readouterr()
    assert "Local identity provisioned" in messages.out
    assert PHRASE not in messages.out + messages.err
    assert len(prompts) == 2
    with IdentityStore.local(path) as store:
        grant = store.issue_session("operator-a", PHRASE, "lab-a")
        context = store.resolve(grant.token, tenant="lab-a", entitlement="research-demo")
        require_permission(
            context.principal, context.scope, Permission.MANAGE_USERS, synthetic=True
        )
        assert store.resolve(grant.token, tenant="lab-b", entitlement="research-demo") is None


def test_existing_file_is_rejected_before_asking_for_any_password(tmp_path, monkeypatch):
    app = _load_bootstrap()
    path = tmp_path / "identity.sqlite3"
    path.write_bytes(b"do-not-overwrite")
    monkeypatch.setattr(
        app.getpass, "getpass",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("prompt unexpectedly invoked")),
    )
    assert app.main(_args(path)) == 1
    assert path.read_bytes() == b"do-not-overwrite"


def test_noninteractive_cli_refuses_to_request_password(tmp_path, monkeypatch):
    app = _load_bootstrap()

    class NonInteractive:
        def isatty(self):
            return False

    monkeypatch.setattr(sys, "stdin", NonInteractive())
    path = tmp_path / "not-created.sqlite3"
    with pytest.raises(SystemExit) as err:
        app.main(_args(path))
    assert err.value.code == 2
    assert not path.exists()


def test_password_confirmation_mismatch_creates_no_account_file(tmp_path, monkeypatch):
    app = _load_bootstrap()
    class Interactive:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Interactive())
    values = iter([PHRASE, "a different synthetic secret!99"])
    monkeypatch.setattr(app.getpass, "getpass", lambda _prompt: next(values))
    path = tmp_path / "identity.sqlite3"
    assert app.main(_args(path)) == 1
    assert not path.exists()
