"""Utilities for patching test fixture data at load time."""

from __future__ import annotations

import re
from typing import Any

from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def patch_fixture_version(response: dict[str, Any]) -> dict[str, Any]:
    """Patch version strings in a fixture dict to match current constants.

    Replaces ``function.version``, ``function.manifestBody.version``, and
    the Docker image tag in ``function.manifestBody.executor.image`` so that
    fixtures stay in sync with ``TOOL_KEYS_AND_VERSIONS`` without manual edits.

    Mutates *response* in place and returns it for convenience.  If the
    fixture has no ``function`` block or the manifest key is not one of
    docking, pocket finder, or sysprep, the dict is returned unchanged.

    Args:
        response: A single function-run response dict loaded from a fixture.

    Returns:
        The same dict, with version fields patched.
    """
    func = response.get("function")
    if not isinstance(func, dict):
        return response

    manifest = func.get("manifestBody")
    if not isinstance(manifest, dict):
        return response

    key = manifest.get("key")
    t = TOOL_KEYS_AND_VERSIONS
    target_version = (
        {
            t["pocket_finder"]["tool_key"]: t["pocket_finder"]["tool_version"],
            t["sysprep"]["tool_key"]: t["sysprep"]["tool_version"],
        }.get(key)
        if key
        else None
    )
    if target_version is None:
        return response

    func["version"] = target_version
    manifest["version"] = target_version

    executor = manifest.get("executor")
    if isinstance(executor, dict) and isinstance(executor.get("image"), str):
        executor["image"] = re.sub(r":[^:]+$", f":{target_version}", executor["image"])

    return response
