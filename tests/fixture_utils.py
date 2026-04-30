"""Utilities for patching test fixture data at load time."""

from __future__ import annotations

from typing import Any

from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def patch_fixture_version(response: dict[str, Any]) -> dict[str, Any]:
    """Patch the embedded ``tool.version`` (or legacy ``function.*``) in fixtures.

    Replaces version fields in a tool-execution fixture dict so that fixtures
    stay in sync with ``TOOL_KEYS_AND_VERSIONS`` without manual edits when the
    canonical version is bumped.

    Mutates *response* in place and returns it for convenience. If no
    recognised key is present, the dict is returned unchanged.

    Args:
        response: A single tool-execution response dict loaded from a fixture.

    Returns:
        The same dict, with version fields patched.
    """
    t = TOOL_KEYS_AND_VERSIONS
    key_to_version = {
        t["pocket_finder"]["tool_key"]: t["pocket_finder"]["tool_version"],
        t["sysprep"]["tool_key"]: t["sysprep"]["tool_version"],
        t["docking"]["tool_key"]: t["docking"]["tool_version"],
    }

    tool = response.get("tool")
    if isinstance(tool, dict):
        target_version = key_to_version.get(tool.get("key"))
        if target_version is not None:
            tool["version"] = target_version

    return response
