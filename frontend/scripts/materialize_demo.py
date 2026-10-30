"""Export the existing Python synthetic research output to a checked-in UI snapshot.

This is a build-time export of fixed, reviewed synthetic fixtures. Never import
external provider data, tokens, network or real company identifiers into this file.
"""

import argparse
import json
from pathlib import Path

from novera.research_compare import compare_scenarios, comparison_json

TARGET = Path(__file__).resolve().parents[1] / "src" / "data" / "scenarios.json"


def render() -> str:
    data = comparison_json(compare_scenarios())
    if data["synthetic"] is not True or any(not x["synthetic"] for x in data["reports"]):
        raise RuntimeError("non-synthetic data cannot enter the frontend")
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or materialize offline demonstration JSON")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.write:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8")
        print(f"Generated {TARGET.relative_to(TARGET.parents[2])}")
        return 0
    if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != expected:
        parser.exit(1, "Static synthetic fixture is missing or out of sync; run --write.\n")
    print("Synthetic UI fixture verified against Python strategies and SQLite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
