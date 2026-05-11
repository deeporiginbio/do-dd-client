"""Data Platform result-explorer API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deeporigin.utils.constants import DEFAULT_SEARCH_PAGE_SIZE

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


def _build_result_filter(**kwargs: Any) -> dict[str, Any]:
    """Build equality filter fields for result-explorer queries.

    Each non-``None`` keyword becomes ``name: {"eq": value}``. Values that are
    ``list`` use ``{"in": value}`` instead (for fields such as ``tool_key``,
    ``ligand_id``, ``ligand1_id``).

    Args:
        **kwargs: Field names and values. ``None`` values are omitted.

    Returns:
        Filter fragment (no ``props`` / ``result_type``) for merging into a
        full result-explorer ``filter`` dict.
    """
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, list):
            out[key] = {"in": value}
        else:
            out[key] = {"eq": value}
    return out


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

    def _apply_project_scope(
        self,
        *,
        filter_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply client-level project scoping to a filter dictionary.

        If ``client.project_id`` is set, this method enforces
        ``{"project_id": {"eq": client.project_id}}``. When a caller also
        provides a ``project_id`` filter with a conflicting value, it raises
        ``ValueError``.

        Args:
            filter_dict: Existing filter dictionary.

        Returns:
            A copied filter dictionary with normalized ``project_id`` shape
            when project scope applies.

        Raises:
            ValueError: If the caller-provided ``project_id`` filter conflicts
                with ``client.project_id`` or has an unsupported shape while
                ``client.project_id`` is set.
        """
        scoped_filter = filter_dict.copy()
        client_project_id = self._c.project_id
        incoming_project_filter = scoped_filter.get("project_id")

        if incoming_project_filter is not None:
            incoming_project_id: str | None = None
            if isinstance(incoming_project_filter, dict):
                if "eq" in incoming_project_filter:
                    incoming_project_id = incoming_project_filter["eq"]
                elif client_project_id is not None:
                    raise ValueError(
                        "When client.project_id is set, filter_dict['project_id'] "
                        "must be a scalar or {'eq': ...}."
                    )
            else:
                incoming_project_id = incoming_project_filter

            if (
                client_project_id is not None
                and incoming_project_id is not None
                and incoming_project_id != client_project_id
            ):
                raise ValueError(
                    "Conflicting project scope: filter_dict['project_id'] does not "
                    "match client.project_id."
                )

            if incoming_project_id is not None:
                scoped_filter["project_id"] = {"eq": incoming_project_id}
                return scoped_filter

        if client_project_id is not None:
            scoped_filter["project_id"] = {"eq": client_project_id}
        return scoped_filter

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

        When ``client.project_id`` is set, this method automatically enforces
        ``filter.project_id == client.project_id``.

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
        filter_dict = self._apply_project_scope(filter_dict=filter_dict)
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
        effort: int | None = None,
        best_pose: bool | None = None,
        limit: int | None = 100,
        select: list[str] | None = None,
    ) -> dict:
        """Get docking poses, optionally filtered by protein.

        Convenience wrapper around :meth:`get` with
        ``result_type="pose"``.

        Project scope is inherited from :meth:`get`: when
        ``client.project_id`` is set, only rows for that project are returned.

        Args:
            protein_id: Optional protein ID to filter by.
            ligand_id: Optional ligand ID (or list of IDs) to filter by.
            compute_job_id: Optional compute job ID to filter by.
            tool_version: Optional tool version to filter by.
            effort: Optional docking effort level (1–5) to filter by.
            best_pose: When set, only rows whose ``data.best_pose`` matches this
                value (typically ``True`` for the top pose per ligand).
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
        filter_dict.update(
            _build_result_filter(
                protein_id=protein_id,
                ligand_id=ligand_id,
                compute_job_id=compute_job_id,
                tool_version=tool_version,
                effort=effort,
                best_pose=best_pose,
            )
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
        limit: int | None = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Get binding pockets, optionally filtered by protein.

        Convenience wrapper around :meth:`get` with
        ``result_type="pocket"``.

        Project scope is inherited from :meth:`get`: when
        ``client.project_id`` is set, only rows for that project are returned.

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
        filter_dict.update(
            _build_result_filter(
                id=id,
                protein_id=protein_id,
                compute_job_id=compute_job_id,
                pocket_count=pocket_count,
                pocket_min_size=pocket_min_size,
                tool_version=tool_version,
            )
        )
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

        Project scope is inherited from :meth:`get`: when
        ``client.project_id`` is set, only rows for that project are returned.

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
        filter_dict.update(
            _build_result_filter(
                protein_id=protein_id,
                ligand1_id=ligand1_id,
                ligand2_id=ligand2_id,
                compute_job_id=compute_job_id,
                padding=padding,
                retain_waters=retain_waters,
                protonate_protein=protonate_protein,
                tool_version=tool_version,
            )
        )
        # there is a bug upstream that is causing the add_H_atoms field to be called add_h_atoms
        # while this is sorted out we're disabling this filter for now
        # if add_H_atoms is not None:
        #     filter_dict["add_h_atoms"] = {"eq": add_H_atoms}

        return self.get(filter_dict=filter_dict, limit=limit, select=select)

    def get_abfe_results(
        self,
        *,
        protein_id: str | None = None,
        ligand1_id: str | list[str] | None = None,
        compute_job_id: str | None = None,
        tool_version: str | None = None,
        limit: int | None = 1000,
        select: list[str] | None = None,
    ) -> dict:
        """Get ABFE (Absolute Binding Free Energy) end-to-end results.

        Convenience wrapper around :meth:`get` that filters on
        ``result_type="abferesult"``. Records are produced by the
        ``deeporigin.abfe-e2e-workflow`` tool when run in ``mode="abfe"`` (or
        ``mode="full"``).

        Project scope is inherited from :meth:`get`: when
        ``client.project_id`` is set, only rows for that project are returned.

        Args:
            protein_id: Optional protein ID to filter by.
            ligand1_id: Optional ligand ID (or list of IDs) to filter by.
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
            "props": [{"column": "result_type", "op": "eq", "value": "abferesult"}]
        }
        filter_dict.update(
            _build_result_filter(
                protein_id=protein_id,
                ligand1_id=ligand1_id,
                compute_job_id=compute_job_id,
                tool_version=tool_version,
            )
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

        When ``client.project_id`` is set, this method automatically enforces
        ``filter.project_id == client.project_id``.

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
        filter_dict = self._apply_project_scope(filter_dict=filter_dict)

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
