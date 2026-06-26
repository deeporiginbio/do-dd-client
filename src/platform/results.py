"""Data Platform result-explorer API wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deeporigin.utils.constants import (
    DEFAULT_SEARCH_PAGE_SIZE,
    RESULT_EXPLORER_CANONICAL_SORT_FIELDS,
)

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_RESULT_TYPE_POSE = "pose"
_RESULT_TYPE_POCKET = "pocket"
_RESULT_TYPE_PREPARED_SYSTEM = "preparedsystem"
_RESULT_TYPE_ABFE_RESULT = "abferesult"


def _normalize_result_type(value: str) -> str:
    """Normalize a platform result-type directive value.

    Args:
        value: Raw result type from caller input.

    Returns:
        Lowercased, stripped catalog base entity name.
    """
    return value.strip().lower()


def _build_result_type_filter(result_type: str | list[str]) -> dict[str, Any]:
    """Build a top-level ``result_type`` filter directive for result-explorer.

    Args:
        result_type: Single type or list of platform catalog base entities.

    Returns:
        Filter fragment ``{"result_type": {"eq": ...}}`` or
        ``{"result_type": {"in": [...]}}``.
    """
    if isinstance(result_type, list):
        normalized = [_normalize_result_type(value) for value in result_type]
        return {"result_type": {"in": normalized}}
    return {"result_type": {"eq": _normalize_result_type(result_type)}}


def _filter_dict_has_result_type(filter_dict: dict[str, Any]) -> bool:
    """Return whether *filter_dict* already constrains ``result_type``.

    Args:
        filter_dict: Result-explorer filter dictionary.

    Returns:
        ``True`` when a top-level or ``props`` ``result_type`` filter is present.
    """
    if "result_type" in filter_dict:
        return True
    for prop in filter_dict.get("props", []):
        if isinstance(prop, dict) and prop.get("column") == "result_type":
            return True
    return False


def _sort_uses_jsonb_fields(sort: dict[str, str] | None) -> bool:
    """Return whether *sort* includes any JSONB tool-data field keys.

    The data-platform result-explorer rejects cursor pagination when sorting
    by non-canonical (JSONB) fields; callers must use offset pagination instead.

    Args:
        sort: Optional sort mapping from :meth:`Results.get`.

    Returns:
        ``True`` when at least one sort key is not a canonical column.
    """
    if sort is None:
        return False
    return any(key not in RESULT_EXPLORER_CANONICAL_SORT_FIELDS for key in sort)


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

    def _prepare_search_filter(
        self,
        *,
        filter_dict: dict[str, Any] | None,
        result_type: str | list[str] | None,
        compute_job_id: str | None,
    ) -> dict[str, Any]:
        """Build the final filter dict for result-explorer search.

        Args:
            filter_dict: Caller filter criteria, or ``None``.
            result_type: Optional platform catalog base entity filter.
            compute_job_id: Optional compute job ID filter.

        Returns:
            Scoped, merged filter dictionary for the search endpoint.

        Raises:
            ValueError: If ``result_type`` is duplicated in ``filter_dict``.
        """
        prepared = {} if filter_dict is None else filter_dict.copy()
        if result_type is not None and _filter_dict_has_result_type(prepared):
            raise ValueError(
                "Cannot pass result_type both as a keyword argument and in filter_dict."
            )
        if result_type is not None:
            prepared.update(_build_result_type_filter(result_type))
        prepared = self._apply_project_scope(filter_dict=prepared)
        if compute_job_id is not None:
            prepared["compute_job_id"] = {"eq": compute_job_id}
        return prepared

    def _fetch_result_pages(
        self,
        *,
        filter_dict: dict[str, Any],
        page_size: int,
        select: list[str],
        sort: dict[str, str] | None,
        limit: int | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Paginate result-explorer search until *limit* or no further pages.

        Canonical sort keys use cursor pagination. JSONB/data sort keys fall back
        to offset pagination because the backend rejects cursor + JSONB sort.

        Args:
            filter_dict: Final filter for the search endpoint.
            page_size: Records requested per page.
            select: Fields to return for each record.
            sort: Optional sort mapping.
            limit: Maximum total records to return, or ``None`` for all pages.

        Returns:
            Tuple of accumulated records and the last API response body.
        """
        if _sort_uses_jsonb_fields(sort):
            return self._fetch_result_pages_by_offset(
                filter_dict=filter_dict,
                page_size=page_size,
                select=select,
                sort=sort,
                limit=limit,
            )
        return self._fetch_result_pages_by_cursor(
            filter_dict=filter_dict,
            page_size=page_size,
            select=select,
            sort=sort,
            limit=limit,
        )

    def _fetch_result_pages_by_cursor(
        self,
        *,
        filter_dict: dict[str, Any],
        page_size: int,
        select: list[str],
        sort: dict[str, str] | None,
        limit: int | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Paginate result-explorer search with cursor tokens.

        Args:
            filter_dict: Final filter for the search endpoint.
            page_size: Records requested per page.
            select: Fields to return for each record.
            sort: Optional sort mapping (canonical columns only).
            limit: Maximum total records to return, or ``None`` for all pages.

        Returns:
            Tuple of accumulated records and the last API response body.
        """
        url = f"/data-platform/{self._c.org_key}/result-explorer/search"
        all_data: list[dict[str, Any]] = []
        cursor: str | None = None
        response: dict[str, Any] = {}

        while True:
            body: dict[str, Any] = {
                "filter": filter_dict,
                "limit": page_size,
                "select": select,
            }
            if sort is not None:
                body["sort"] = sort
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

        return all_data, response

    def _fetch_result_pages_by_offset(
        self,
        *,
        filter_dict: dict[str, Any],
        page_size: int,
        select: list[str],
        sort: dict[str, str] | None,
        limit: int | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Paginate result-explorer search with offset/limit pages.

        Used when sorting by JSONB tool-data fields, which the backend does not
        support with cursor pagination.

        Args:
            filter_dict: Final filter for the search endpoint.
            page_size: Records requested per page.
            select: Fields to return for each record.
            sort: Optional sort mapping (may include JSONB field keys).
            limit: Maximum total records to return, or ``None`` for all pages.

        Returns:
            Tuple of accumulated records and the last API response body.
        """
        url = f"/data-platform/{self._c.org_key}/result-explorer/search"
        all_data: list[dict[str, Any]] = []
        offset = 0
        response: dict[str, Any] = {}

        while True:
            body: dict[str, Any] = {
                "filter": filter_dict,
                "limit": page_size,
                "select": select,
                "offset": offset,
            }
            if sort is not None:
                body["sort"] = sort

            response = self._c.post_json(url, body=body)
            page_data = response.get("data", [])
            all_data.extend(page_data)

            if limit is not None and len(all_data) >= limit:
                all_data = all_data[:limit]
                break

            if not page_data:
                break

            meta = response.get("meta", {})
            has_more = meta.get("hasMore")
            if has_more is False:
                break
            if has_more is True:
                offset += page_size
                continue
            if len(page_data) < page_size:
                break
            offset += page_size

        return all_data, response

    def get(
        self,
        *,
        filter_dict: dict[str, Any] | None = None,
        result_type: str | list[str] | None = None,
        compute_job_id: str | None = None,
        limit: int | None = 1000,
        select: list[str] | None = None,
        sort: dict[str, str] | None = None,
    ) -> dict:
        """Low-level paginated search against the result-explorer API.

        Prefer the higher-level wrappers (:meth:`get_poses`,
        :meth:`get_pockets`) which expose friendly keyword arguments and
        build the filter for you.  Use this method directly only when you
        need a filter shape that no wrapper covers yet.

        Automatically paginates until all matching records have been fetched.
        Canonical-column sorts use cursor pagination; JSONB tool-data sort
        keys use offset pagination (see ``sort`` below).

        When ``client.project_id`` is set, this method automatically enforces
        ``filter.project_id == client.project_id``.

        Args:
            filter_dict: Raw filter criteria forwarded to the
                result-explorer search endpoint (e.g. ``score``, ``protein_id``).
            result_type: Platform catalog base entity (``pose``, ``pocket``,
                ``preparedsystem``, ``abferesult``, …). Accepts a single value
                or list; input is case-insensitive. Maps to the top-level
                ``filter.result_type`` directive. Cannot be combined with
                ``result_type`` in ``filter_dict``.
            compute_job_id: Optional compute job ID to filter by.
            limit: Maximum total number of results to return across all
                pages. Defaults to 1000.
            select: List of fields to select. Defaults to
                ``["id", "tool_key", "tool_version", "data", "compute_job_id"]``.
            sort: Optional sort mapping field names to ``"asc"`` or ``"desc"``.
                Canonical columns (``measured_at``, ``tool_key``, …) paginate
                with cursors. JSONB tool-data fields (``pose_score``, …)
                automatically use offset pagination because the backend rejects
                cursor pagination combined with JSONB sort keys.

        Returns:
            Dictionary with ``data`` (all records across pages) and ``meta``
            from the final response.

        Raises:
            ValueError: If ``result_type`` is passed both as a kwarg and inside
                ``filter_dict``.
        """
        filter_dict = self._prepare_search_filter(
            filter_dict=filter_dict,
            result_type=result_type,
            compute_job_id=compute_job_id,
        )
        if select is None:
            # note -- compute_job_id is the same as executionId in the rest of the system
            # IMPORTANT! execution_id is not the same as executionId in the rest of the system
            select = ["id", "tool_key", "tool_version", "data", "compute_job_id"]

        page_size = (
            min(limit, DEFAULT_SEARCH_PAGE_SIZE)
            if limit is not None
            else DEFAULT_SEARCH_PAGE_SIZE
        )
        all_data, response = self._fetch_result_pages(
            filter_dict=filter_dict,
            page_size=page_size,
            select=select,
            sort=sort,
            limit=limit,
        )
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
        return self.get(
            result_type=_RESULT_TYPE_POSE,
            filter_dict=_build_result_filter(
                protein_id=protein_id,
                ligand_id=ligand_id,
                compute_job_id=compute_job_id,
                tool_version=tool_version,
                effort=effort,
                best_pose=best_pose,
            ),
            limit=limit,
            select=select,
        )

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
        return self.get(
            result_type=_RESULT_TYPE_POCKET,
            filter_dict=_build_result_filter(
                id=id,
                protein_id=protein_id,
                compute_job_id=compute_job_id,
                pocket_count=pocket_count,
                pocket_min_size=pocket_min_size,
                tool_version=tool_version,
            ),
            limit=limit,
            select=select,
        )

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
        filter_dict = _build_result_filter(
            protein_id=protein_id,
            ligand1_id=ligand1_id,
            ligand2_id=ligand2_id,
            compute_job_id=compute_job_id,
            padding=padding,
            retain_waters=retain_waters,
            protonate_protein=protonate_protein,
            tool_version=tool_version,
        )
        # there is a bug upstream that is causing the add_H_atoms field to be called add_h_atoms
        # while this is sorted out we're disabling this filter for now
        # if add_H_atoms is not None:
        #     filter_dict["add_h_atoms"] = {"eq": add_H_atoms}

        return self.get(
            result_type=_RESULT_TYPE_PREPARED_SYSTEM,
            filter_dict=filter_dict,
            limit=limit,
            select=select,
        )

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
        return self.get(
            result_type=_RESULT_TYPE_ABFE_RESULT,
            filter_dict=_build_result_filter(
                protein_id=protein_id,
                ligand1_id=ligand1_id,
                compute_job_id=compute_job_id,
                tool_version=tool_version,
            ),
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
