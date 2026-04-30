#!/usr/bin/env python3
"""Detect stale tool-run fixtures whose version doesn't match ``TOOL_KEYS_AND_VERSIONS``.

A fixture is "stale" when the tool version baked into the fixture JSON
(``tool.version``, ``function.version``, or ``function.manifestBody.version``)
does not match the canonical version in
``deeporigin.platform.constants.TOOL_KEYS_AND_VERSIONS``.

Pre-existing stale fixtures can be temporarily allowlisted in ``ALLOWLIST``
so that the check passes while they await regeneration. Remove entries as
fixtures are brought up-to-date.

Exit codes:
    0 – all fixtures are up-to-date (or allowlisted).
    1 – at least one stale fixture was found that is not allowlisted.

Usage:
    python scripts/check_stale_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "tool-runs"

# Pre-existing stale fixtures that are tracked but not yet regenerated.
# Each entry is the path relative to the project root. Remove an entry
# once the fixture has been brought up-to-date.
ALLOWLIST: set[str] = {
    "tests/fixtures/tool-runs/deeporigin.docking/run.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-ames/"
    "70456ca2628ceb7811e86e82fb2b0064e2a065e2afb7e03ef19694c803b84fc1.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-cyp/"
    "70456ca2628ceb7811e86e82fb2b0064e2a065e2afb7e03ef19694c803b84fc1.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-herg/"
    "70456ca2628ceb7811e86e82fb2b0064e2a065e2afb7e03ef19694c803b84fc1.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-logd/"
    "70456ca2628ceb7811e86e82fb2b0064e2a065e2afb7e03ef19694c803b84fc1.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-logp/"
    "70456ca2628ceb7811e86e82fb2b0064e2a065e2afb7e03ef19694c803b84fc1.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-logs/"
    "70456ca2628ceb7811e86e82fb2b0064e2a065e2afb7e03ef19694c803b84fc1.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-pains/"
    "70456ca2628ceb7811e86e82fb2b0064e2a065e2afb7e03ef19694c803b84fc1.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-protonation/"
    "2895f2afe88b5a1d970acf10e41f302bb810cc8bf37d849758400f4367ee1d85.json",
    "tests/fixtures/tool-runs/deeporigin.mol-props-protonation/"
    "d9309dc3b122fc636e63c88a2dbf0b32f04cb23a5557affb9f1bb577ec6e5ffb.json",
    "tests/fixtures/tool-runs/deeporigin.pocketfinder/quote.json",
    "tests/fixtures/tool-runs/deeporigin.pocketfinder/run.json",
    "tests/fixtures/tool-runs/deeporigin.system-prep/"
    "a10d5446bf28de3e526fc41cda7f00beb1ba511ced05ac87a27cb2b98faefeb6.json",
    "tests/fixtures/tool-runs/deeporigin.system-prep/run.json",
}


def _ensure_pkg_path() -> None:
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _expected_version_for_tool_key(tool_key: str) -> str | None:
    """Return the expected manifest version for *tool_key*, or None if not tracked."""

    _ensure_pkg_path()
    from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS

    t = TOOL_KEYS_AND_VERSIONS
    if tool_key == t["docking"]["tool_key"]:
        return t["docking"]["tool_version"]
    if tool_key in (t["pocket_finder"]["tool_key"], "deeporigin.pocketfinder"):
        return t["pocket_finder"]["tool_version"]
    if tool_key == t["sysprep"]["tool_key"]:
        return t["sysprep"]["tool_version"]
    mp = t["mol_props"]
    if tool_key == mp["protonation_tool_key"]:
        return mp["tool_version"]
    prefix = mp["tool_key_prefix"]
    if tool_key.startswith(f"{prefix}-"):
        return mp["tool_version"]
    return None


def _fixture_version(fixture_path: Path) -> str | None:
    """Extract the tool version from a fixture JSON file.

    Args:
        fixture_path: Path to the fixture JSON file.

    Returns:
        The version string, or None if the fixture has no version metadata.
    """
    with open(fixture_path) as f:
        data = json.load(f)

    tool = data.get("tool")
    if isinstance(tool, dict) and tool.get("version"):
        return tool["version"]

    func = data.get("function")
    if not isinstance(func, dict):
        return None

    manifest = func.get("manifestBody")
    if isinstance(manifest, dict) and "version" in manifest:
        return manifest["version"]

    return func.get("version")


def main() -> int:
    """Check for stale fixtures and return an appropriate exit code.

    Returns:
        0 if no stale fixtures found (ignoring allowlisted), 1 otherwise.
    """
    stale: list[tuple[Path, str, str]] = []
    allowed: list[tuple[Path, str, str]] = []

    for tool_dir in sorted(FIXTURES_DIR.iterdir()):
        if not tool_dir.is_dir():
            continue

        tool_key = tool_dir.name
        expected_version = _expected_version_for_tool_key(tool_key)
        if expected_version is None:
            continue

        for fixture_path in sorted(tool_dir.glob("*.json")):
            version = _fixture_version(fixture_path)
            if version is None:
                continue
            if version != expected_version:
                rel = str(fixture_path.relative_to(PROJECT_ROOT))
                if rel in ALLOWLIST:
                    allowed.append((fixture_path, version, expected_version))
                else:
                    stale.append((fixture_path, version, expected_version))

    if allowed:
        print(f"{len(allowed)} allowlisted stale fixture(s) (tracked, not blocking):")
        for path, got, want in allowed:
            rel = path.relative_to(PROJECT_ROOT)
            print(f"  {rel}  ({got} → {want})")
        print()

    if not stale:
        print("No new stale fixtures found.")
        return 0

    print(f"Found {len(stale)} stale fixture(s):\n")
    for path, got, want in stale:
        rel = path.relative_to(PROJECT_ROOT)
        print(f"  {rel}")
        print(f"    fixture version: {got}  (expected {want})\n")

    print(
        "Regenerate stale fixtures by running the relevant test with "
        "DO_ENV=dev and record=True on the client, then delete the old files."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
