"""Validate the installed package independently of the source checkout."""

import subprocess
import sys


def test_installed_package_import_with_socket_constructor_guard(tmp_path):
    """Guard Python socket creation only, not DNS, native I/O or subprocesses.

    This is an import smoke test, not an OS-level network isolation guarantee.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import socket; "
            "socket.socket = lambda *a, **k: (_ for _ in ()).throw("
            "AssertionError('network forbidden during import')); "
            "import novera; print(novera.__name__)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "novera"
    assert result.stderr == ""
