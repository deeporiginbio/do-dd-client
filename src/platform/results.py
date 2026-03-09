"""Data Platform result-explorer API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def _build_result_filter(
    *,
    id: str | None = None,
    tool_id: str | list[str] | None = None,
    protein_id: str | None = None,
    ligand_id: str | list[str] | None = None,
    compute_job_id: str | None = None,
    tool_version: str | None = None,
    pocket_count: int | None = None,
    pocket_min_size: int | None = None,
) -> dict[str, Any]:
    """Build a filter dict for result-explorer queries.

    Args:
        id: Record ID (uses ``eq``).
        tool_id: Tool ID (or list of IDs). A single string uses ``eq``;
            a list uses ``in``.
        protein_id: Protein ID (uses ``eq``).
        ligand_id: Ligand ID (or list of IDs). A single string uses ``eq``;
            a list uses ``in``.
        compute_job_id: Compute job ID (passed as-is, no operator wrapper).
        tool_version: Tool version (uses ``eq``).
        pocket_count: Maximum number of pockets (uses ``eq``).
        pocket_min_size: Minimum pocket volume in cubic Angstroms (uses ``eq``).

    Returns:
        Filter dictionary ready to pass to the result-explorer search API.
    """
    filter_dict: dict[str, Any] = {}
    if id is not None:
        filter_dict["id"] = {"eq": id}
    if tool_id is not None:
        if isinstance(tool_id, list):
            filter_dict["tool_id"] = {"in": tool_id}
        else:
            filter_dict["tool_id"] = {"eq": tool_id}
    if protein_id is not None:
        filter_dict["protein_id"] = {"eq": protein_id}
    if ligand_id is not None:
        if isinstance(ligand_id, list):
            filter_dict["ligand_id"] = {"in": ligand_id}
        else:
            filter_dict["ligand_id"] = {"eq": ligand_id}
    if compute_job_id is not None:
        filter_dict["compute_job_id"] = compute_job_id
    if tool_version is not None:
        filter_dict["tool_version"] = {"eq": tool_version}
    if pocket_count is not None:
        filter_dict["pocket_count"] = {"eq": pocket_count}
    if pocket_min_size is not None:
        filter_dict["pocket_min_size"] = {"eq": pocket_min_size}
    return filter_dict


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

    def get(
        self,
        *,
        filter_dict: dict[str, Any] | None = None,
        limit: int = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Low-level paginated search against the result-explorer API.

        Prefer the higher-level wrappers (:meth:`get_poses`,
        :meth:`get_pockets`) which expose friendly keyword arguments and
        build the filter for you.  Use this method directly only when you
        need a filter shape that no wrapper covers yet.

        Automatically paginates using cursor-based pagination until all
        matching records have been fetched.

        Args:
            filter_dict: Raw filter criteria forwarded to the
                result-explorer search endpoint.
            limit: Page size per request. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_id", "tool_version", "data", "compute_job_id"]``.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.
        """
        if filter_dict is None:
            filter_dict = {}
        if select is None:
            # note -- job_compute_id is the same as executionId in the rest of the system
            # IMPORTANT! execution_id is not the same as executionId in the rest of the system
            select = ["id", "tool_id", "tool_version", "data", "compute_job_id"]

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
        protein_id: str | None = None,
        ligand_id: str | list[str] | None = None,
        tool_id: str | list[str] | None = None,
        compute_job_id: str | None = None,
        tool_version: str | None = None,
        limit: int = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Get docking poses, optionally filtered by protein.

        Convenience wrapper around :meth:`get` that fetches results
        from both ``deeporigin.docking`` and ``deeporigin.bulk-docking``.

        Args:
            protein_id: Optional protein ID to filter by.
            ligand_id: Optional ligand ID (or list of IDs) to filter by.
            tool_id: Optional tool ID (or list of IDs) to filter by.
                Defaults to ``["deeporigin.docking", "deeporigin.bulk-docking"]``.
            compute_job_id: Optional compute job ID to filter by.
            tool_version: Optional tool version to filter by.
            limit: Page size per request. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_id", "tool_version", "data", "compute_job_id"]``.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.
        """
        if tool_id is None:
            tool_id = ["deeporigin.docking", "deeporigin.bulk-docking"]
        filter_dict = _build_result_filter(
            tool_id=tool_id,
            protein_id=protein_id,
            ligand_id=ligand_id,
            compute_job_id=compute_job_id,
            tool_version=tool_version,
        )
        return self.get(filter_dict=filter_dict, limit=limit, select=select)

    def get_pockets(
        self,
        *,
        id: str | None = None,
        protein_id: str | None = None,
        compute_job_id: str | None = None,
        pocket_count: int | None = None,
        pocket_min_size: int | None = None,
        tool_version: str | None = None,
        limit: int = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Get binding pockets, optionally filtered by protein.

        Convenience wrapper around :meth:`get` with
        ``tool_id="deeporigin.pocketfinder"``.

        Args:
            id: Optional record ID to fetch a specific pocket.
            protein_id: Optional protein ID to filter by.
            compute_job_id: Optional compute job ID to filter by.
            pocket_count: Optional pocket count to filter by.
            pocket_min_size: Optional pocket min size to filter by.
            tool_version: Optional tool version to filter by.
            limit: Page size per request. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_id", "tool_version", "data", "compute_job_id"]``.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.
        """
        filter_dict = _build_result_filter(
            id=id,
            tool_id="deeporigin.pocketfinder",
            protein_id=protein_id,
            compute_job_id=compute_job_id,
            pocket_count=pocket_count,
            pocket_min_size=pocket_min_size,
            tool_version=tool_version,
        )
        return self.get(filter_dict=filter_dict, limit=limit, select=select)

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
