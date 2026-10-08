"""Executions API wrapper for DeepOriginClient."""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from datetime import datetime, timezone
import random
import time
from typing import TYPE_CHECKING, Any

from beartype import beartype
import httpx

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.errors import raise_for_platform_restriction

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

from deeporigin.platform.constants import (
    EXECUTION_VISIBILITY_VALUES,
    TERMINAL_STATES,
    ExecutionVisibility,
)
from deeporigin.platform.project_scope import stamp_execution_project_id
from deeporigin.platform.sse import (
    StreamUnavailableError,
    abort_stream_after,
    iter_dirty_filters,
    open_project_stream,
)
from deeporigin.utils.constants import (
    DATA_PLATFORM_INGESTION_POLL_SECONDS,
    DATA_PLATFORM_INGESTION_SWEEP_SECONDS,
    DATA_PLATFORM_INGESTION_TIMEOUT_SECONDS,
    DATA_PLATFORM_NO_ROW_TIMEOUT_SECONDS,
    SSE_MAX_READ_TIMEOUT_SECONDS,
    SSE_RECONNECT_BACKOFF_SECONDS,
    SSE_RECONNECT_MAX_BACKOFF_SECONDS,
    SSE_STABLE_CONNECTION_SECONDS,
    TOOL_EXECUTION_GET_ACCEPT_HEADER,
    TOOL_EXECUTION_POST_TIMEOUT_SECONDS,
)

_INGESTION_FILTER_ID = "execution"


@dataclass
class _IngestionWait:
    """State of one :meth:`Executions.wait_for_ingestion` call.

    Attributes:
        execution_id: Tools-service execution id (``compute_job_id``).
        project_id: Project the execution belongs to.
        started: ``time.monotonic()`` value at which the wait began.
        deadline: ``time.monotonic()`` value at which the wait gives up.
        next_sweep: ``time.monotonic()`` value at which the row is re-read
            even if no frame asks for it. Every read pushes it back.
        last_read: ``time.monotonic()`` value of the latest row read, or of
            the start of the wait before the first read.
        include_hidden: Whether the row is searched with ``include_hidden``.
            Cleared when the backend does not accept the flag.
    """

    execution_id: str
    project_id: str
    started: float
    deadline: float
    next_sweep: float
    last_read: float
    include_hidden: bool = True

    def time_left(self) -> float:
        """Return seconds left before the deadline, raising once it has passed.

        Returns:
            Positive seconds remaining.

        Raises:
            TimeoutError: If the deadline has passed.
        """
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                "Timed out waiting for data-platform ingestion "
                f"(execution_id={self.execution_id!r}, "
                f"project_id={self.project_id!r})."
            )
        return remaining

    def sweep_due(self) -> bool:
        """Return whether the row should be re-read without a frame asking.

        Returns:
            True once ``next_sweep`` has passed.
        """
        return time.monotonic() >= self.next_sweep


def _rejects_include_hidden(error: DeepOriginException) -> bool:
    """Return whether a search failed because ``include_hidden`` is unknown.

    Backends without the flag reject it as an unknown key with a 400 that
    names the field.

    Args:
        error: The error raised by :meth:`Executions.search`.

    Returns:
        True when the 400 names ``include_hidden``.
    """
    if error.http_status != 400 or not isinstance(error.response_data, dict):
        return False
    errors = error.response_data.get("errors")
    return isinstance(errors, list) and any(
        isinstance(item, dict) and item.get("field") == "include_hidden"
        for item in errors
    )


def _reconnect_delay(failures: int) -> float:
    """Return the jittered pause before reopening an SSE stream.

    Doubles from ``SSE_RECONNECT_BACKOFF_SECONDS`` with each consecutive
    failure, up to ``SSE_RECONNECT_MAX_BACKOFF_SECONDS``, then picks a point
    between half and all of it so clients dropped together do not reconnect
    together.

    Args:
        failures: Consecutive failed connects; ``0`` after a stable stream.

    Returns:
        Seconds to wait.
    """
    delay = min(
        SSE_RECONNECT_BACKOFF_SECONDS * 2 ** max(failures - 1, 0),
        SSE_RECONNECT_MAX_BACKOFF_SECONDS,
    )
    return random.uniform(delay / 2, delay)


def _created_after_to_iso_utc(created_after: datetime | str) -> str:
    """Format a lower bound for ``createdAt: {$gt: ...}`` tools list filters.

    Args:
        created_after: Instant or ISO-8601 string (as accepted by the API).

    Returns:
        UTC timestamp string with millisecond precision and ``Z`` suffix,
        matching typical execution DTO ``createdAt`` values.
    """
    if isinstance(created_after, str):
        return created_after
    dt = created_after
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Executions:
    """Executions API wrapper.

    Provides access to tool execution-related endpoints through the DeepOriginClient.
    """

    def __init__(self, client: DeepOriginClient) -> None:
        """Initialize Executions wrapper.

        Args:
            client: The DeepOriginClient instance to use for API calls.
        """
        self._c = client
        self._include_hidden_supported = True

    def create(
        self,
        *,
        tool_key: str,
        tool_version: str,
        data: dict,
        timeout: float | None = None,
        visibility: ExecutionVisibility | None = None,
    ) -> dict:
        """Create (run) an execution of a tool with a specific version.

        Args:
            tool_key: Key of the tool to run.
            tool_version: Version of the tool to run.
            data: Data transfer object (DTO) containing tool execution parameters.
                This is typically generated by the `make_payload` function.
                If "clusterId" is not present, it will be set to the default cluster ID.
            timeout: HTTP timeout in seconds for this request. If None, uses
                ``TOOL_EXECUTION_POST_TIMEOUT_SECONDS`` (600s), since quoting and
                synchronous execution creation can exceed the client's default
                short timeout (e.g. molprops, protonation, system-prep).
                When ``client.tag`` is set, it is sent as ``tag`` unless the
                caller already included ``tag`` in ``data``. When
                ``client.billing_tag`` is set, it is sent as ``billing`` unless
                the caller already included ``billing`` in ``data``.
                Uses ``retry=False`` so a failed create (including gateway 504)
                is not retried; retries can otherwise duplicate long sync jobs.
            visibility: Optional activity-history visibility, ``"visible"`` or
                ``"hidden"``. ``"hidden"`` opts the run out of user-facing activity
                views (it still exists, and stays visible to admin/audit/billing).
                Sent unless the caller already included ``visibility`` in ``data``.
                Falls back to the client-level ``_visibility`` default when both
                are unset; when every source is ``None`` the key is omitted and
                the server decides. Validated whichever source supplies it.
                Note ``data={"visibility": None}`` does not suppress a client-level
                default -- ``None`` reads as "unset" at every level, so resolution
                falls through to it. To force one run visible on a client that
                defaults to hidden, pass ``visibility="visible"`` explicitly.

        Returns:
            Dictionary containing the execution response from the API.

        Raises:
            ValueError: If the resolved ``visibility`` -- from ``data``, the
                argument, or the client default -- is not ``"visible"`` or
                ``"hidden"``.
            PlatformRestrictionError: If licensing or billing rejects execution.
                The exception preserves the platform reason, action, and response.
        """
        payload = data.copy()

        # Resolved and validated before any side effect (the clusterId lookup below
        # can issue a request), so a bad value fails instantly and offline.
        #
        # Precedence, highest first: an explicit value already in `data`, the
        # `visibility` argument, then the client-level default. This matches how
        # `tag` / `billing` treat a caller-supplied payload as authoritative.
        # Every source is validated, so no path can fail open -- validating only
        # the argument would leave the winning one unchecked.
        resolved_visibility = next(
            (
                candidate
                for candidate in (
                    payload.get("visibility"),
                    visibility,
                    getattr(self._c, "_visibility", None),
                )
                if candidate is not None
            ),
            None,
        )
        if (
            resolved_visibility is not None
            and resolved_visibility not in EXECUTION_VISIBILITY_VALUES
        ):
            raise ValueError(
                f"visibility must be one of "
                f"{sorted(EXECUTION_VISIBILITY_VALUES)}, got {resolved_visibility!r}"
            )
        if resolved_visibility is None:
            # Drops an explicit `{"visibility": None}` from `data`; the server's
            # schema marks the field optional, which accepts an absent key but
            # rejects a JSON null.
            payload.pop("visibility", None)
        else:
            payload["visibility"] = resolved_visibility

        stamp_execution_project_id(self._c, payload)

        if "clusterId" not in payload:
            payload["clusterId"] = self._c.clusters.get_default_cluster_id()

        payload["app"] = self._c._app
        payload["session"] = self._c._session
        if self._c.tag is not None and "tag" not in payload:
            payload["tag"] = self._c.tag
        if (
            getattr(self._c, "billing_tag", None) is not None
            and "billing" not in payload
        ):
            payload["billing"] = self._c.billing_tag

        req_timeout = (
            timeout if timeout is not None else TOOL_EXECUTION_POST_TIMEOUT_SECONDS
        )

        # Single attempt: retrying a timed-out sync create can spawn duplicate
        # long-running tool work (e.g. system-prep behind an nginx 504).
        result = self._c.post_json(
            f"/tools/{self._c.org_key}/tools/{tool_key}/{tool_version}/executions",
            body=payload,
            timeout=req_timeout,
            retry=False,
        )
        raise_for_platform_restriction(result)
        return result

    def _list_tools_executions_page(
        self,
        *,
        page: int | None,
        page_size: int | None,
        order: str | None = None,
        tool_key: str | None = None,
        session: str | None = None,
        project_id: str | None = None,
        created_after: datetime | str | None = None,
    ) -> Any:
        """Perform one GET for the tools-service executions list URL with query params.

        Args:
            page: Zero-based page index, or ``None`` to omit (server default).
            page_size: Page size query param, or ``None`` to omit.
            order: Sort order string.
            tool_key: Filter by tool manifest key.
            session: Filter by session tag.
            project_id: Filter by project id.
            created_after: Lower bound on ``createdAt``.

        Returns:
            Parsed JSON from the platform (typically ``{"data": [...], "count": n}``).
        """
        params: dict[str, int | str] = {}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["pageSize"] = page_size
        if order is not None:
            params["order"] = order

        filter_dict: dict = {}
        if tool_key is not None:
            filter_dict["tool"] = {"toolManifest": {"key": tool_key}}
        if session is not None:
            filter_dict["session"] = session
        if project_id is not None:
            filter_dict["projectId"] = project_id
        if created_after is not None:
            filter_dict["createdAt"] = {"$gt": _created_after_to_iso_utc(created_after)}

        if filter_dict:
            import json

            params["filter"] = json.dumps(filter_dict)

        return self._c.get_json(
            f"/tools/{self._c.org_key}/tools/executions",
            params=params if params else None,
        )

    def _list_tools_executions_fetch_all(
        self,
        *,
        chunk_size: int,
        order: str | None = None,
        tool_key: str | None = None,
        session: str | None = None,
        project_id: str | None = None,
        created_after: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Merge every page of tools execution list results for the given filters.

        Args:
            chunk_size: Rows per request (``pageSize`` query param).
            order: Sort order string.
            tool_key: Filter by tool manifest key.
            session: Filter by session tag.
            project_id: Filter by project id.
            created_after: Lower bound on ``createdAt``.

        Returns:
            ``{"data": [...], "count": <server total>}`` with ``data`` concatenated
            across pages in order.
        """
        current_page = 0
        all_dtos: builtins.list[dict[str, Any]] = []
        total_count = 0

        while True:
            response = self._list_tools_executions_page(
                page=current_page,
                page_size=chunk_size,
                order=order,
                tool_key=tool_key,
                session=session,
                project_id=project_id,
                created_after=created_after,
            )

            if not isinstance(response, dict):
                all_dtos.extend(response if isinstance(response, builtins.list) else [])
                return {"data": all_dtos, "count": len(all_dtos)}

            page_dtos = response.get("data", [])
            all_dtos.extend(page_dtos)
            total_count = response.get("count", 0)

            if total_count > chunk_size:
                if len(page_dtos) < chunk_size:
                    break
                if len(all_dtos) >= total_count:
                    break
                current_page += 1
            else:
                break

        return {"data": all_dtos, "count": total_count}

    def list(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
        order: str | None = None,
        tool_key: str | None = None,
        session: str | None = None,
        project_id: str | None = None,
        created_after: datetime | str | None = None,
        fetch_all_pages: bool = False,
    ) -> dict:
        """List tool executions with pagination and filtering.

        Args:
            page: Page number of the pagination (default 0). Ignored when
                ``fetch_all_pages`` is ``True``.
            page_size: Page size of the pagination (max 10,000). When
                ``fetch_all_pages`` is ``True`` and this is ``None``, uses ``1000``.
            order: Order of the pagination, e.g., "executionId? asc", "completedAt? desc".
            tool_key: Tool key to filter by.
            session: Session identifier to filter by. Returns only executions
                tagged with this session on creation (see ``executions.create``
                where ``payload["session"] = self._c._session``). Without this,
                the endpoint returns all executions the caller can see, not
                just ones from the caller's own client.
            project_id: When set, restrict to executions whose root-level
                ``projectId`` matches (same field as in the tools execution
                DTO; may be omitted or null on rows that are not project-scoped).
            created_after: When set, restrict to rows with ``createdAt`` strictly
                after this instant. Passed to the tools-service list filter as
                ``createdAt: {"$gt": "<iso-8601>"}`` (MikroORM operator on the
                entity ``createdAt`` column). Use a timezone-aware
                :class:`~datetime.datetime` or an ISO string such as
                ``2026-05-07T15:13:25.254Z``.
            fetch_all_pages: When ``True``, follow pagination until every row
                for the filter is collected, merge ``data`` in page order, and
                return ``{"data": [...], "count": <total>}``. When ``False``,
                performs a single request using ``page`` / ``page_size``.

        Returns:
            Dictionary containing paginated execution data (or all rows when
            ``fetch_all_pages`` is ``True``).
        """
        if fetch_all_pages:
            chunk_size = page_size if page_size is not None else 1000
            return self._list_tools_executions_fetch_all(
                chunk_size=chunk_size,
                order=order,
                tool_key=tool_key,
                session=session,
                project_id=project_id,
                created_after=created_after,
            )

        return self._list_tools_executions_page(
            page=page,
            page_size=page_size,
            order=order,
            tool_key=tool_key,
            session=session,
            project_id=project_id,
            created_after=created_after,
        )

    def get(self, execution_id: str) -> dict:
        """Get a tool execution by execution ID.

        Requests the tools-service v2.0 execution DTO (``Accept:
        application/json;v=2.0``), which includes the enhanced
        ``progressReport`` tree. Top-level fields such as ``executionId``,
        ``status``, ``userInputs``, and ``jobOutputs`` match the v1 shape
        used elsewhere in this library.

        Args:
            execution_id: The execution ID to fetch.

        Returns:
            Dictionary containing the tool execution data.
        """
        return self._c.get_json(
            f"/tools/{self._c.org_key}/tools/executions/{execution_id}",
            headers={"Accept": TOOL_EXECUTION_GET_ACCEPT_HEADER},
        )

    def search(
        self,
        *,
        project_id: str | None = None,
        tool_key: list[str] | str | None = None,
        status: str | None = None,
        extra_props: list[dict[str, Any]] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select: list[str] | None = None,
        with_total_count: bool = False,
        compute_job_id: str | None = None,
        include_hidden: bool = False,
    ) -> dict:
        """Search executions via the data-platform endpoint.

        Unlike :meth:`list` (tools-service DTO with camelCase ``projectId``;
        use ``list(project_id=...)`` to filter there), this method hits
        ``POST /data-platform/{org}/executions/search`` which:

        - exposes ``project_id`` as a first-class column and applies it as
          a server-side filter when provided,
        - returns rows with snake_case columns (``tool_key``,
          ``started_at``, ``project_id``, ...) and ``tags`` (``app`` +
          ``session``) / ``compute_metadata`` (``userInputs``, ...) as
          nested objects,
        - supports the standard data-platform ``{"props": [...]}`` filter
          grammar with ``eq`` / ``neq`` / ``in`` / ... ops.

        Args:
            project_id: Scope to this project. **Strongly recommended** —
                without it the response spans every execution the caller
                can see.
            tool_key: Equality filter on ``tool_key`` (e.g.
                ``"deeporigin.bulk-docking"``).
            status: Equality filter on ``status`` (e.g. ``"Completed"``,
                ``"Failed"``, ``"Running"``).
            extra_props: Additional filter props appended to the
                built-in ones. Each prop is a dict with
                ``{"column": str, "op": str, "value": Any}``.
            limit: Max rows to return.
            offset: Skip offset.
            select: Columns to select; all columns by default.
            with_total_count: When True, the server returns a total count
                alongside the page (may be slower).
            compute_job_id: Equality filter on ``compute_job_id`` (the
                tools-service execution id).
            include_hidden: When True, also return runs submitted with
                ``visibility="hidden"``, which the search omits by default.

        Returns:
            The raw response dict, typically ``{"data": [...], "meta": {...}}``.
        """
        props: list[dict[str, Any]] = []
        if project_id is not None:
            props.append({"column": "project_id", "op": "eq", "value": project_id})
        if isinstance(tool_key, (list, tuple)):
            props.append({"column": "tool_key", "op": "in", "value": tool_key})
        elif isinstance(tool_key, str) and tool_key:
            props.append({"column": "tool_key", "op": "eq", "value": tool_key})
        if status is not None:
            props.append({"column": "status", "op": "eq", "value": status})
        if compute_job_id is not None:
            props.append(
                {"column": "compute_job_id", "op": "eq", "value": compute_job_id}
            )
        if extra_props:
            props.extend(extra_props)

        body: dict[str, Any] = {"filter": {"props": props}}
        if limit is not None:
            body["limit"] = limit
        if offset is not None:
            body["offset"] = offset
        if select is not None:
            body["select"] = select
        if with_total_count:
            body["with_total_count"] = True
        if include_hidden:
            body["include_hidden"] = True

        return self._c.post_json(
            f"/data-platform/{self._c.org_key}/executions/search",
            body=body,
        )

    def from_data_platform(self, data_platform_execution_id: str) -> dict:
        """Get an execution from the data-platform API by its execution identifier.

        This identifier is not the same as the tools-service ``execution_id`` used
        by :meth:`get`.

        Args:
            data_platform_execution_id: Data-platform execution ID (e.g. from search UIs).

        Returns:
            Dictionary containing the execution record from the data platform.
        """
        return self._c.get_json(
            f"/data-platform/{self._c.org_key}/executions/{data_platform_execution_id}"
        )

    def cancel(self, execution_id: str) -> None:
        """Cancel a tool execution.

        Args:
            execution_id: The execution ID to cancel.

        Returns:
            None. If the execution is already in a terminal state, returns early.
        """
        data = self.get(execution_id)

        if data.get("status") in TERMINAL_STATES:
            return

        self._c._patch(
            f"/tools/{self._c.org_key}/tools/executions/{execution_id}:cancel"
        )

    def confirm(
        self,
        execution_id: str,
        *,
        timeout: float | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Confirm a tool execution.

        Args:
            execution_id: The execution ID to confirm.
            timeout: Optional HTTP timeout in seconds for this request. When
                ``None``, the client's default timeout applies.
            retry: When ``True`` (default), use the client's retry policy for
                transient failures. Set ``False`` for a single attempt.

        Returns:
            Updated execution DTO from the platform (same shape as :meth:`get`).

        Raises:
            PlatformRestrictionError: If licensing or billing rejects confirmation.
        """
        patch_kwargs: dict[str, Any] = {}
        if timeout is not None:
            patch_kwargs["timeout"] = timeout
        if not retry:
            patch_kwargs["retry"] = False
        response = self._c._patch(
            f"/tools/{self._c.org_key}/tools/executions/{execution_id}:confirm",
            **patch_kwargs,
        )
        result = response.json()
        raise_for_platform_restriction(result)
        return result

    @beartype
    def wait(
        self,
        executions: str | builtins.list[str],
        *,
        poll_interval: float = 5.0,
        timeout: float | None = None,
    ) -> builtins.list[dict]:
        """Block until every given execution reaches a terminal state.

        Periodically polls the platform via :meth:`get` for each execution
        whose status is not yet in
        :data:`~deeporigin.platform.constants.TERMINAL_STATES`, sleeping
        ``poll_interval`` seconds between polling cycles. Once all executions
        have terminated (or ``timeout`` elapses), returns the latest DTOs in
        the same order as the input.

        Args:
            executions: A single execution ID string, or a list of execution
                ID strings to wait on.
            poll_interval: Seconds to sleep between polling cycles. Must be
                positive. Defaults to ``5.0``.
            timeout: Maximum total seconds to wait. If ``None`` (default),
                waits indefinitely. When set and exceeded before all
                executions terminate, raises :class:`TimeoutError`.

        Returns:
            Latest execution DTOs (one per input), each in a terminal state.
            List inputs retain all results, including rejected executions.

        Raises:
            ValueError: If ``executions`` is empty, ``poll_interval`` is not
                positive, or any execution ID is an empty string.
            TimeoutError: If ``timeout`` is set and elapses before every
                execution reaches a terminal state.
            PlatformRestrictionError: For a single string ID, if licensing or
                billing rejected execution. List inputs return rejected DTOs.
        """
        ids = [executions] if isinstance(executions, str) else list(executions)
        if not ids:
            raise ValueError("executions must be a non-empty list")
        if poll_interval <= 0:
            raise ValueError(f"poll_interval must be positive, got {poll_interval!r}")
        for index, exec_id in enumerate(ids):
            if not exec_id:
                raise ValueError(f"executions[{index}] is an empty string")

        latest: dict[str, dict] = {}
        deadline = time.monotonic() + timeout if timeout is not None else None

        while pending := self._poll_pending(ids, latest):
            sleep_for = poll_interval
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out after {timeout}s waiting for "
                        f"{len(pending)} of {len(ids)} executions to "
                        f"reach a terminal state: {pending}"
                    )
                sleep_for = min(poll_interval, remaining)
            time.sleep(sleep_for)

        if isinstance(executions, str):
            raise_for_platform_restriction(latest[executions])
        return [latest[exec_id] for exec_id in ids]

    def _poll_pending(
        self,
        ids: builtins.list[str],
        latest: dict[str, dict],
    ) -> builtins.list[str]:
        """Refresh non-terminal executions and return those still pending.

        Args:
            ids: Execution IDs to inspect (order preserved).
            latest: Cache of the most recent DTO per execution ID; updated
                in place for any execution that gets re-polled.

        Returns:
            IDs whose latest status is not yet in
            :data:`~deeporigin.platform.constants.TERMINAL_STATES`.
        """
        pending: builtins.list[str] = []
        for exec_id in ids:
            cached = latest.get(exec_id)
            if cached is not None and cached.get("status") in TERMINAL_STATES:
                continue
            dto = self.get(exec_id)
            latest[exec_id] = dto
            if dto.get("status") not in TERMINAL_STATES:
                pending.append(exec_id)
        return pending

    @beartype
    def wait_for_ingestion(
        self,
        execution_id: str,
        *,
        project_id: str | None = None,
        timeout: int | float = DATA_PLATFORM_INGESTION_TIMEOUT_SECONDS,
    ) -> dict:
        """Block until an execution's data-platform ingestion has finished.

        Woken by the gateway's SSE stream rather than by polling. Data-platform
        holds an execution at ``DataIngesting`` until its results are ingested,
        so a status in :data:`~deeporigin.platform.constants.TERMINAL_STATES`
        means ingestion is done. The stream watches
        ``execution:{execution_id}``; each ``filters.dirty`` frame re-reads the
        row via :meth:`search` with ``include_hidden=True``, since client runs
        are submitted hidden. The row is also re-read on every connect, and
        each stream is opened before its read, so a completion in between is
        not missed.

        Frames are not replayed, so while the stream is open a sweep re-reads
        the row whenever ``DATA_PLATFORM_INGESTION_SWEEP_SECONDS`` pass
        without a read. Every read pushes the sweep back, so it only fires
        when the stream has gone quiet. While the stream is closed, dropped
        or refused, the row is polled every
        ``DATA_PLATFORM_INGESTION_POLL_SECONDS`` instead.

        A stream that closed, dropped with a network error or was refused
        with a retryable status is reopened after a jittered pause that
        doubles from ``SSE_RECONNECT_BACKOFF_SECONDS`` up to
        ``SSE_RECONNECT_MAX_BACKOFF_SECONDS``. A stream that stayed open for
        ``SSE_STABLE_CONNECTION_SECONDS`` resets the pause. An open stream is
        cut off at the deadline, so a read waiting on the next heartbeat
        cannot carry the wait past ``timeout``. A row re-read already in
        flight at the deadline uses the client's own request timeout and
        retries.

        Args:
            execution_id: Tools-service execution id (data-platform
                ``compute_job_id``).
            project_id: Project the execution belongs to. Defaults to the
                client's ``project_id``.
            timeout: Maximum total seconds to wait.

        If the backend does not accept ``include_hidden`` yet, the search
        drops it. A visible run is then waited on as usual. A hidden run's row
        cannot be read, so ingestion counts as done once result-explorer has
        rows for it, or after ``DATA_PLATFORM_NO_ROW_TIMEOUT_SECONDS`` with no
        row, and ``{}`` is returned.

        Returns:
            The data-platform execution row, in a terminal state. Failed and
            cancelled executions are returned, not raised; check ``status``.
            ``{}`` when the backend cannot return a hidden run's row.

        Raises:
            ValueError: If ``execution_id`` is empty or no project id is set.
            TimeoutError: If ingestion does not finish within ``timeout``.
            DeepOriginException: If the gateway refuses the stream with a
                non-retryable status (e.g. 401, 403, 404).
        """
        if not execution_id:
            raise ValueError("execution_id must be a non-empty string")
        project_id = project_id or self._c.project_id
        if not project_id:
            raise ValueError("project_id is required: pass it or set client.project_id")

        started = time.monotonic()
        wait = _IngestionWait(
            execution_id=execution_id,
            project_id=project_id,
            started=started,
            deadline=started + timeout,
            next_sweep=started + DATA_PLATFORM_INGESTION_SWEEP_SECONDS,
            last_read=started,
            include_hidden=self._include_hidden_supported,
        )
        filters = {_INGESTION_FILTER_ID: f"execution:{execution_id}"}
        failures = 0
        while True:
            remaining = wait.time_left()
            opened_at: float | None = None
            try:
                with (
                    open_project_stream(
                        self._c,
                        project_id=project_id,
                        filters=filters,
                        read_timeout=min(remaining, SSE_MAX_READ_TIMEOUT_SECONDS),
                    ) as response,
                    abort_stream_after(response, wait.deadline - time.monotonic()),
                ):
                    opened_at = time.monotonic()
                    row = self._wait_on_ingestion_stream(response, wait)
                    if row is not None:
                        return row
            except (httpx.TransportError, StreamUnavailableError):
                pass
            stable = (
                opened_at is not None
                and time.monotonic() - opened_at >= SSE_STABLE_CONNECTION_SECONDS
            )
            failures = 0 if stable else failures + 1
            row = self._pause_before_reconnect(wait, _reconnect_delay(failures))
            if row is not None:
                return row

    def _wait_on_ingestion_stream(
        self,
        response: httpx.Response,
        wait: _IngestionWait,
    ) -> dict | None:
        """Read the row now, then on each matching dirty frame or due sweep.

        Args:
            response: The open SSE stream for this execution's filter.
            wait: State of the wait.

        Returns:
            The row once it is terminal, or ``None`` if the stream closed first.

        Raises:
            TimeoutError: If the deadline passes while the stream is open.
        """
        row = self._terminal_ingestion_row(wait)
        if row is not None:
            return row
        for dirty in iter_dirty_filters(response):
            woken = dirty is not None and _INGESTION_FILTER_ID in dirty
            if woken or wait.sweep_due():
                row = self._terminal_ingestion_row(wait)
                if row is not None:
                    return row
            wait.time_left()
        return None

    def _pause_before_reconnect(
        self,
        wait: _IngestionWait,
        delay: float,
    ) -> dict | None:
        """Sleep before the next connect, polling the row while the stream is down.

        The row is read every ``DATA_PLATFORM_INGESTION_POLL_SECONDS`` since
        the last read, so polling keeps its pace across reconnect attempts.

        Args:
            wait: State of the wait.
            delay: Seconds to pause before reconnecting.

        Returns:
            The row if a poll during the pause found it terminal, else
            ``None``.

        Raises:
            TimeoutError: If the deadline passes during the pause.
        """
        while True:
            until_poll = (
                wait.last_read + DATA_PLATFORM_INGESTION_POLL_SECONDS - time.monotonic()
            )
            if until_poll >= delay:
                time.sleep(min(delay, wait.time_left()))
                return None
            if until_poll > 0:
                time.sleep(min(until_poll, wait.time_left()))
                delay -= until_poll
            wait.time_left()
            row = self._terminal_ingestion_row(wait)
            if row is not None:
                return row

    def _terminal_ingestion_row(self, wait: _IngestionWait) -> dict | None:
        """Read an execution's data-platform row if it is terminal.

        Pushes the next sweep back, since the row has just been read.

        Without ``include_hidden`` (a backend that rejects it), a hidden run's
        row is never returned. Ingestion then counts as done once
        result-explorer has rows for the execution, or once
        ``DATA_PLATFORM_NO_ROW_TIMEOUT_SECONDS`` pass with no row, as before
        the flag existed.

        Args:
            wait: State of the wait.

        Returns:
            The row when its status is terminal, ``{}`` when ingestion is
            judged done without a visible row, else ``None`` (including when
            the row does not exist yet).
        """
        rows = self._read_ingestion_rows(wait)
        wait.last_read = time.monotonic()
        wait.next_sweep = wait.last_read + DATA_PLATFORM_INGESTION_SWEEP_SECONDS
        if rows:
            return rows[0] if rows[0].get("status") in TERMINAL_STATES else None
        if wait.include_hidden:
            return None
        if self._c.results.get(compute_job_id=wait.execution_id, limit=1).get("data"):
            return {}
        give_up_at = wait.started + DATA_PLATFORM_NO_ROW_TIMEOUT_SECONDS
        if time.monotonic() >= give_up_at:
            return {}
        wait.next_sweep = min(wait.next_sweep, give_up_at)
        return None

    def _read_ingestion_rows(self, wait: _IngestionWait) -> list[dict]:
        """Search the execution's data-platform row.

        Falls back to searching without ``include_hidden`` when the backend
        rejects the flag, and remembers that for later waits on this client.

        Args:
            wait: State of the wait.

        Returns:
            The matching rows, at most one.

        Raises:
            DeepOriginException: If the search fails for any other reason.
        """
        try:
            response = self.search(
                compute_job_id=wait.execution_id,
                project_id=wait.project_id,
                limit=1,
                include_hidden=wait.include_hidden,
            )
        except DeepOriginException as error:
            if not wait.include_hidden or not _rejects_include_hidden(error):
                raise
            wait.include_hidden = False
            self._include_hidden_supported = False
            response = self.search(
                compute_job_id=wait.execution_id,
                project_id=wait.project_id,
                limit=1,
            )
        return response.get("data") or []
