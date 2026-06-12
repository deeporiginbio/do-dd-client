"""Tools API wrapper for DeepOriginClient."""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING

from deeporigin.exceptions import DeepOriginException

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Tools:
    """Tools API wrapper.

    Provides access to tools-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Tools wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def list(self) -> builtins.list[dict]:
        """List all available tool definitions.

        Returns:
            List of tool definition dictionaries from the API.
        """
        response = self._c.get_json("/tools/protected/tools/definitions")
        # Handle both dict with 'data' key and direct list responses
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        elif isinstance(response, list):
            return response
        else:
            return []

    def get_by_key(self, *, tool_key: str) -> builtins.list[dict]:
        """Get all versions of a tool definition by tool key.

        Args:
            tool_key: The key of the tool to get the definitions for.

        Returns:
            List of tool definition dictionaries for all versions of the tool.
        """
        return self._c.get_json(f"/tools/protected/tools/{tool_key}/definitions")

    def get(self, *, tool_key: str, tool_version: str) -> dict:
        """Return a single tool definition for the given key and version.

        Uses ``GET /tools/protected/tools/{toolKey}/{toolVersion}/definitions``.

        Args:
            tool_key: Tool identifier.
            tool_version: Exact version string to match.

        Returns:
            Tool definition dict (includes ``inputs``, ``key``, ``version``, etc.).
        """
        return self._c.get_json(
            f"/tools/protected/tools/{tool_key}/{tool_version}/definitions"
        )

    def exists(self, *, tool_key: str, tool_version: str) -> bool:
        """Return whether a tool version pin resolves to an enabled definition.

        The platform resolves *tool_version* at request time: exact semver
        (``"3.2.3"``), major-only (``"1"`` → latest ``1.x.x``), or ``"latest"``.

        Args:
            tool_key: Tool identifier.
            tool_version: Version pin accepted by the platform tools API.

        Returns:
            ``True`` when the pin resolves and the definition is enabled.
        """
        try:
            definition = self.get(tool_key=tool_key, tool_version=tool_version)
        except DeepOriginException:
            return False
        return definition.get("enabled") is not False
