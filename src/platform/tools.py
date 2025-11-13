"""Tools API wrapper for DeepOriginClient."""

from __future__ import annotations

from typing import TYPE_CHECKING

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

    def list(self) -> dict:
        """List all available tool definitions.

        Returns:
            Dictionary containing tool definitions from the API.
        """
        return self._c.get_json("/tools/protected/tools/definitions")

    def get_by_key(self, *, tool_key: str) -> list[dict]:
        """Get all versions of a tool definition by tool key.

        Args:
            tool_key: The key of the tool to get the definitions for.

        Returns:
            List of tool definition dictionaries for all versions of the tool.
        """
        return self._c.get_json(f"/tools/protected/tools/{tool_key}/definitions")
