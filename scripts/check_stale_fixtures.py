#!/usr/bin/env python3
"""Detect stale function-run fixtures whose version doesn't match ``TOOL_KEYS_AND_VERSIONS``.

A fixture is "stale" when the function version baked into the fixture JSON
(``function.version`` or ``function.manifestBody.version``) does not match the
canonical version in ``deeporigin.platform.constants.TOOL_KEYS_AND_VERSIONS``.

Pre-existing stale fixtures can be temporarily allowlisted in ``ALLOWLIST``
so that the check passes while they await regeneration.  Remove entries as
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
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "function-runs"

# Pre-existing stale fixtures that are tracked but not yet regenerated.
# Each entry is the path relative to the project root.  Remove an entry
# once the fixture has been brought up-to-date.
ALLOWLIST: set[str] = {
    "tests/fixtures/function-runs/deeporigin.docking/"
    "7327071365baa19d589f03adeaf910cf5b22645976a57c19ea65bf301c9fa7e0.json",
}


def _ensure_pkg_path() -> None:
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _expected_version_for_function_key(function_key: str) -> str | None:
    """Return the expected manifest version for *function_key*, or None if not tracked."""

    _ensure_pkg_path()
    from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS

    t = TOOL_KEYS_AND_VERSIONS
    for name, spec in t.items():
        if name == "mol_props":
            continue
        fk = spec.get("function_key")
        if fk == function_key:
            return spec.get("function_version")
    mp = t["mol_props"]
    if function_key == mp["protonation_function_key"]:
        return mp["function_version"]
    return None


def _fixture_version(fixture_path: Path) -> str | None:
    """Extract the function version from a fixture JSON file.

    Args:
        fixture_path: Path to the fixture JSON file.

    Returns:
        The version string, or None if the fixture has no version metadata.
    """
    with open(fixture_path) as f:
        data = json.load(f)

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

    for function_dir in sorted(FIXTURES_DIR.iterdir()):
        if not function_dir.is_dir():
            continue

        function_key = function_dir.name
        expected_version = _expected_version_for_function_key(function_key)
        if expected_version is None:
            continue

        for fixture_path in sorted(function_dir.glob("*.json")):
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
