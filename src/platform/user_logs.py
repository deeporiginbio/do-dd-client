"""user_logs entity API wrapper for DeepOriginClient (data-platform user_logs table)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient


class UserLogs:
    """Data-platform ``user_logs`` entity (search by compute job, etc.).

    Hits ``POST /data-platform/{orgKey}/user_logs/search`` with the standard
    data-platform filter grammar (``filter.props`` with ``eq`` / ...).
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize UserLogs wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client

    def search(
        self,
        compute_job_id: str | None = None,
        *,
        limit: int | None = None,
        offset: int | None = None,
        select: list[str] | None = None,
        with_total_count: bool = False,
    ) -> dict:
        """Search user log rows, optionally scoped to a compute job.

        Calls ``POST /data-platform/{orgKey}/user_logs/search`` with
        an optional ``compute_job_id`` ``eq`` filter (same pattern as
        :meth:`deeporigin.platform.executions.Executions.search` for
        executions) when provided.

        Args:
            compute_job_id: If set, restrict results to this compute job.
            limit: Max rows to return.
            offset: Skip offset.
            select: Columns to select; all columns by default.
            with_total_count: When True, the server may return a total
                count alongside the page (may be slower).

        Returns:
            The raw response dict, typically ``{"data": [...], "meta": {...}}``
            (exact keys depend on the service).
        """
        props: list[dict[str, Any]] = []
        if compute_job_id is not None:
            props.append(
                {"column": "compute_job_id", "op": "eq", "value": compute_job_id}
            )
        body: dict[str, Any] = {"filter": {"props": props}}
        if limit is not None:
            body["limit"] = limit
        if offset is not None:
            body["offset"] = offset
        if select is not None:
            body["select"] = select
        if with_total_count:
            body["with_total_count"] = True

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/user_logs/search",
            body=body,
        )
