"""Data Platform result-explorer API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class Results:
    """Result-explorer API wrapper.

    Provides access to result-explorer endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Results wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def get_for(
        self,
        *,
        tool_id: str,
        protein_id: str,
        tool_version: str | None = None,
        limit: int = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Search result-explorer records filtered by tool and protein.

        Automatically paginates using cursor-based pagination until all
        matching records have been fetched.

        Args:
            tool_id: Tool ID to filter by (e.g. "deeporigin.bulk-docking").
            protein_id: Protein ID to filter by.
            tool_version: Optional tool version to filter by.
            limit: Page size per request. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_id", "tool_version", "data", "execution_id"]``.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.
        """
        if select is None:
            select = ["id", "tool_id", "tool_version", "data", "execution_id"]

        filter_dict: dict[str, Any] = {
            "protein_id": {"eq": protein_id},
            "tool_id": {"eq": tool_id},
        }
        if tool_version is not None:
            filter_dict["tool_version"] = {"eq": tool_version}

        url = f"/data-platform/{self._c.org_key}/result-explorer/search"
        all_data: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            body: dict[str, Any] = {
                "filter": filter_dict,
                "limit": limit,
                "select": select,
            }
            if cursor is not None:
                body["cursor"] = cursor

            response = self._c.post_json(url, body=body)
            all_data.extend(response.get("data", []))

            next_cursor = response.get("meta", {}).get("nextCursor")
            if not next_cursor:
                break
            cursor = next_cursor

        response["data"] = all_data
        return response

    def get_poses(
        self,
        *,
        protein_id: str,
        tool_version: str | None = None,
        limit: int = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Get docking poses for a protein.

        Convenience wrapper around :meth:`get_for` with
        ``tool_id="deeporigin.docking"``.

        Args:
            protein_id: Protein ID to filter by.
            tool_version: Optional tool version to filter by.
            limit: Page size per request. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_id", "tool_version", "data", "execution_id"]``.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.
        """
        return self.get_for(
            tool_id="deeporigin.docking",
            protein_id=protein_id,
            tool_version=tool_version,
            limit=limit,
            select=select,
        )

    def with_ligands(
        self,
        *,
        cursor: str | None = None,
        experiments: list[dict[str, str]] | None = None,
        filter_dict: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict:
        """Search ligands joined with tool results (wide pivot view).

        Args:
            cursor: Cursor for pagination.
            experiments: List of experiment filters, each containing toolId and
                optionally toolVersion.
            filter_dict: Additional filter criteria as a dictionary.
            limit: Maximum number of results to return. Defaults to 100.
            offset: Number of results to skip.
            select: List of fields to select in the response.
            sort: Dictionary mapping field names to sort order ("asc" or "desc").

        Returns:
            Dictionary containing the search results.
        """
        if filter_dict is None:
            filter_dict = {"deleted": False}
        else:
            filter_dict = filter_dict.copy()
            filter_dict["deleted"] = False

        body: dict[str, Any] = {}
        if cursor is not None:
            body["cursor"] = cursor
        if experiments is not None:
            body["experiments"] = experiments
        body["filter"] = filter_dict

        if limit is not None:
            body["limit"] = limit
        if offset is not None:
            body["offset"] = offset
        if select is not None:
            body["select"] = select
        if sort is not None:
            body["sort"] = sort

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/ligands_with_results/search",
            body=body,
        )
