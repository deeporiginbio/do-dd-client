"""Data Platform result-explorer API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deeporigin.platform.constants import ABFE_TOOL_KEY
from deeporigin.utils.constants import DEFAULT_SEARCH_PAGE_SIZE

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def _build_result_filter(
    *,
    id: str | None = None,
    tool_key: str | list[str] | None = None,
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
        tool_key: Tool ID (or list of IDs). A single string uses ``eq``;
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
    if tool_key is not None:
        if isinstance(tool_key, list):
            filter_dict["tool_key"] = {"in": tool_key}
        else:
            filter_dict["tool_key"] = {"eq": tool_key}
    if protein_id is not None:
        filter_dict["protein_id"] = {"eq": protein_id}
    if ligand_id is not None:
        if isinstance(ligand_id, list):
            filter_dict["ligand_id"] = {"in": ligand_id}
        else:
            filter_dict["ligand_id"] = {"eq": ligand_id}
    if compute_job_id is not None:
        filter_dict["compute_job_id"] = {"eq": compute_job_id}
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
        compute_job_id: str | None = None,
        limit: int | None = 1000,
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
            compute_job_id: Optional compute job ID to filter by.
            limit: Maximum total number of results to return across all
                pages. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_key", "tool_version", "data", "compute_job_id"]``.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.
        """
        if filter_dict is None:
            filter_dict = {}
        if compute_job_id is not None:
            filter_dict["compute_job_id"] = {"eq": compute_job_id}
        if select is None:
            # note -- compute_job_id is the same as executionId in the rest of the system
            # IMPORTANT! execution_id is not the same as executionId in the rest of the system
            select = ["id", "tool_key", "tool_version", "data", "compute_job_id"]

        if limit is not None:
            page_size = min(limit, DEFAULT_SEARCH_PAGE_SIZE)
        else:
            page_size = DEFAULT_SEARCH_PAGE_SIZE

        url = f"/data-platform/{self._c.org_key}/result-explorer/search"
        all_data: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            body: dict[str, Any] = {
                "filter": filter_dict,
                "limit": page_size,
                "select": select,
            }
            if cursor is not None:
                body["cursor"] = cursor

            response = self._c.post_json(url, body=body)
            all_data.extend(response.get("data", []))

            if limit is not None and len(all_data) >= limit:
                all_data = all_data[:limit]
                break

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
        compute_job_id: str | None = None,
        tool_version: str | None = None,
        limit: int | None = 100,
        select: list[str] | None = None,
    ) -> dict:
        """Get docking poses, optionally filtered by protein.

        Convenience wrapper around :meth:`get` with
        ``result_type="pose"``.

        Args:
            protein_id: Optional protein ID to filter by.
            ligand_id: Optional ligand ID (or list of IDs) to filter by.
            compute_job_id: Optional compute job ID to filter by.
            tool_version: Optional tool version to filter by.
            limit: Maximum total number of results to return. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_key", "tool_version", "data", "compute_job_id"]``.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.
        """
        filter_dict: dict[str, Any] = {
            "props": [{"column": "result_type", "op": "eq", "value": "pose"}]
        }

        if protein_id is not None:
            filter_dict["protein_id"] = {"eq": protein_id}
        if ligand_id is not None:
            if isinstance(ligand_id, list):
                filter_dict["ligand_id"] = {"in": ligand_id}
            else:
                filter_dict["ligand_id"] = {"eq": ligand_id}
        if compute_job_id is not None:
            filter_dict["compute_job_id"] = {"eq": compute_job_id}
        if tool_version is not None:
            filter_dict["tool_version"] = {"eq": tool_version}
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
        limit: int | None = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Get binding pockets, optionally filtered by protein.

        Convenience wrapper around :meth:`get` with
        ``result_type="pocket"``.

        Args:
            id: Optional record ID to fetch a specific pocket.
            protein_id: Optional protein ID to filter by.
            compute_job_id: Optional compute job ID to filter by.
            pocket_count: Optional pocket count to filter by.
            pocket_min_size: Optional pocket min size to filter by.
            tool_version: Optional tool version to filter by.
            limit: Maximum total number of results to return. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_key", "tool_version", "data", "compute_job_id"]``.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.
        """
        filter_dict: dict[str, Any] = {
            "props": [{"column": "result_type", "op": "eq", "value": "pocket"}]
        }

        if id is not None:
            filter_dict["id"] = {"eq": id}
        if protein_id is not None:
            filter_dict["protein_id"] = {"eq": protein_id}
        if compute_job_id is not None:
            filter_dict["compute_job_id"] = {"eq": compute_job_id}
        if pocket_count is not None:
            filter_dict["pocket_count"] = {"eq": pocket_count}
        if pocket_min_size is not None:
            filter_dict["pocket_min_size"] = {"eq": pocket_min_size}
        if tool_version is not None:
            filter_dict["tool_version"] = {"eq": tool_version}
        return self.get(filter_dict=filter_dict, limit=limit, select=select)

    def get_prepared_systems(
        self,
        *,
        protein_id: str | None = None,
        ligand1_id: str | None = None,
        ligand2_id: str | None = None,
        compute_job_id: str | None = None,
        padding: int | None = None,
        add_H_atoms: bool | None = None,  # NOSONAR
        retain_waters: bool | None = None,
        protonate_protein: bool | None = None,
        tool_version: str | None = None,
        limit: int | None = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Get system-prep results, optionally filtered by inputs and options.

        Convenience wrapper around :meth:`get` with
        ``tool_key="deeporigin.system-prep"``. Optional args filter on the
        tool result ``data`` (e.g. protein_id, ligand1_id, padding,
        add_H_atoms, retain_waters, protonate_protein).

        Args:
            protein_id: Optional protein ID to filter by.
            ligand1_id: Optional ligand1 ID to filter by.
            ligand2_id: Optional ligand2 ID to filter by.
            compute_job_id: Optional compute job ID to filter by.
            padding: Optional padding value to filter by.
            add_H_atoms: Optional add_H_atoms flag to filter by.
            retain_waters: Optional retain_waters flag to filter by.
            protonate_protein: Optional protonate_protein flag to filter by.
            tool_version: Optional tool version to filter by.
            limit: Maximum total number of results to return. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_key", "tool_version", "data", "compute_job_id"]``.

        Returns:
            Dictionary with ``data`` (all matching records across pages) and
            ``meta`` from the final response.
        """
        filter_dict: dict[str, Any] = {
            "props": [{"column": "result_type", "op": "eq", "value": "preparedsystem"}]
        }

        if protein_id is not None:
            filter_dict["protein_id"] = {"eq": protein_id}
        if ligand1_id is not None:
            filter_dict["ligand1_id"] = {"eq": ligand1_id}
        if ligand2_id is not None:
            filter_dict["ligand2_id"] = {"eq": ligand2_id}
        if compute_job_id is not None:
            filter_dict["compute_job_id"] = {"eq": compute_job_id}
        if padding is not None:
            filter_dict["padding"] = {"eq": padding}
        # there is a bug upstream that is causing the add_H_atoms field to be called add_h_atoms
        # while this is sorted out we're disabling this filter for now
        # if add_H_atoms is not None:
        #     filter_dict["add_h_atoms"] = {"eq": add_H_atoms}
        if retain_waters is not None:
            filter_dict["retain_waters"] = {"eq": retain_waters}
        if protonate_protein is not None:
            filter_dict["protonate_protein"] = {"eq": protonate_protein}
        if tool_version is not None:
            filter_dict["tool_version"] = {"eq": tool_version}

        return self.get(filter_dict=filter_dict, limit=limit, select=select)

    def get_abfe_results(
        self,
        *,
        protein_id: str | None = None,
        ligand_id: str | list[str] | None = None,
        compute_job_id: str | None = None,
        tool_version: str | None = None,
        limit: int | None = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Get ABFE (Absolute Binding Free Energy) end-to-end results.

        Convenience wrapper around :meth:`get` with
        ``tool_key="deeporigin.abfe-end-to-end"``.

        Args:
            protein_id: Optional protein ID to filter by.
            ligand_id: Optional ligand ID (or list of IDs) to filter by.
            compute_job_id: Optional compute job ID to filter by.
            tool_version: Optional tool version to filter by.
            limit: Maximum total number of results to return. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_key", "tool_version", "data", "compute_job_id"]``.

        Returns:
            Dictionary with ``data`` (all matching records across pages) and
            ``meta`` from the final response.
        """
        filter_dict: dict[str, Any] = {
            "tool_key": {"eq": ABFE_TOOL_KEY},
        }

        if protein_id is not None:
            filter_dict["protein_id"] = {"eq": protein_id}
        if ligand_id is not None:
            if isinstance(ligand_id, list):
                filter_dict["ligand_id"] = {"in": ligand_id}
            else:
                filter_dict["ligand_id"] = {"eq": ligand_id}
        if compute_job_id is not None:
            filter_dict["compute_job_id"] = {"eq": compute_job_id}
        if tool_version is not None:
            filter_dict["tool_version"] = {"eq": tool_version}
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
