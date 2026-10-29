"""Scan tracked files with local detectors; print counts, never candidate secrets."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from detect_secrets.core.scan import scan_file
from detect_secrets.settings import default_settings


def scan(paths: list[str]) -> bool:
    count = 0
    with default_settings() as settings:
        # No verification filter: detectors run locally without validating credentials.
        if any("verif" in item["path"] for item in settings.json()["filters_used"]):
            raise RuntimeError("unexpected verification filter configured")
        for name in paths:
            path = Path(name)
            if path.is_symlink():
                raise RuntimeError("symlinks require manual security review")
            path.read_bytes()  # Fail closed on missing/unreadable tracked files.
            count += len(list(scan_file(str(path))))
    print(f"Secret scan findings: {count}")
    return count == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        with tempfile.TemporaryDirectory(prefix="novera-secret-check-") as directory:
            path = Path(directory) / "synthetic.txt"
            # A synthetic header only, never an actual key or credential.
            path.write_text("-----BEGIN " + "RSA PRIVATE KEY-----\n", encoding="utf-8")
            if scan([str(path)]):
                raise RuntimeError("scanner did not reject synthetic private-key header")
        print("Secret scanner negative control passed")
        return 0
    result = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    paths = result.stdout.decode("utf-8").split("\0")
    if not any(paths):
        raise RuntimeError("no tracked files to scan")
    return 0 if scan([path for path in paths if path]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
