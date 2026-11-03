"""Tools API wrapper for DeepOriginClient."""

from __future__ import annotations

import builtins
import json
from typing import TYPE_CHECKING, Any

from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import (
    TOOL_DEFINITIONS_LIST_ACCEPT_HEADER,
    TOOL_DEFINITIONS_LIST_PAGE_SIZE,
)

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

    def list(self, *, enabled: bool | None = None) -> builtins.list[dict]:
        """List tool definitions, every version of every tool by default.

        Reads the v2 list (``Accept: application/json;v=2.0``), which answers
        ``{"count": n, "data": [...]}`` one page at a time, and follows the pages
        until ``count`` rows are read. A platform without the v2 list answers with
        the whole registry as a bare array and ignores paging and filters; that
        array is used as is, so the result is the same on either platform.

        Args:
            enabled: ``True`` for enabled versions only, ``False`` for disabled
                ones only, ``None`` (default) for every version.

        Returns:
            List of tool definition dictionaries from the API.
        """
        params: dict[str, Any] = {"pageSize": TOOL_DEFINITIONS_LIST_PAGE_SIZE}
        if enabled is not None:
            params["filter"] = json.dumps({"enabled": enabled})

        rows: builtins.list[dict] = []
        page = 0
        while True:
            response = self._c.get_json(
                "/tools/protected/tools/definitions",
                params={**params, "page": page},
                headers={"Accept": TOOL_DEFINITIONS_LIST_ACCEPT_HEADER},
            )
            if isinstance(response, builtins.list):
                rows = response
                break
            if not isinstance(response, dict):
                break
            data = response.get("data") or []
            rows.extend(data)
            count = response.get("count")
            if not data or not isinstance(count, int) or len(rows) >= count:
                break
            page += 1

        if enabled is None:
            return rows
        # A platform without the v2 list ignores the filter.
        return [row for row in rows if bool(row.get("enabled")) is enabled]

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
