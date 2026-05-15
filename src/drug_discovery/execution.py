"""Base class for the jobs-centric API.

Provides ``Execution`` -- a base class with read-only ``@property`` descriptors
for system-managed fields, platform ``id``, and ``confirm()`` for tools
executions, lifecycle state management, :attr:`Execution.runtime` from DTO
timestamps, plus ``from_id()`` / :meth:`Execution.list` delegate to
:meth:`Execution.from_dto`. :meth:`Execution.sync` refreshes an instance from
``executions.get`` (any execution class, including sync-only or objects built
from a stale DTO). :meth:`Execution.update_from_dto` applies the same fields to
an existing instance (for example after ``executions.create``). The base
``from_dto`` hydrates tools execution fields from the DTO; concrete types
override it, call ``super().from_dto()``, then restore domain-specific state
from ``userInputs``. Subclasses also expose immutable input fields as read-only
properties and compose with mixins (``SyncExecutableMixin``,
``AsyncExecutableMixin``) to build concrete execution types like
``PocketFinder``, ``Docking``, and ``ABFE``.

Quoting is handled directly by ``run()`` and ``start()`` via ``quote=True``
(sugar for ``approve_amount=0``) or an explicit ``approve_amount``. When the
platform returns a ``Quoted`` DTO the instance is left in that state -- no
automatic confirmation is performed.
"""

from __future__ import annotations

import builtins
import copy
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, Self

from deeporigin.platform.constants import ALLOWED_STATUS_TRANSITIONS
from deeporigin.utils.constants import TOOL_EXECUTION_POST_TIMEOUT_SECONDS
from deeporigin.utils.iso8601 import parse_iso_timestamp_utc

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

QuoteMode = Literal["sync", "async"]

__all__ = ["Execution", "QuoteMode"]


class Execution:
    """Base class for all execution types in the jobs-centric API.

    System-managed fields ``estimate`` and ``cost`` are exposed as read-only
    properties. Platform execution ``id`` and ``confirm()`` live on this class
    for tool-backed jobs. Subclasses implement :meth:`_make_payload` to build
    create payloads; they receive ``sync: bool`` and ``approve_amount`` directly.

    Rehydration: :meth:`from_dto` on this base class performs shared tools DTO
    hydration (``executionId``, pricing, lifecycle fields, ``_dto``).
    Concrete subclasses **must** override :meth:`from_dto`, call
    ``super().from_dto()``, then attach domain-specific state from
    ``userInputs`` (see :class:`~deeporigin.drug_discovery.docking.Docking` and
    :class:`~deeporigin.drug_discovery.pocket_finder.PocketFinder`). Calling
    :meth:`from_id` or :meth:`list` on :class:`Execution` itself raises
    ``NotImplementedError`` (no ``tool_key`` on the bare base class).

    To align with the platform after a job was updated elsewhere (for example
    the web UI) or to poll status, call :meth:`sync` whenever :attr:`id` is set;
    it is not limited to async subclasses.

    Attributes:
        estimate: Cost estimate in dollars, populated from the DTO quotation result.
        cost: Actual cost in dollars, set after execution completes.
        id: Platform execution id when set (read-only :class:`property`; backed by ``_id``).
        dto: Last tools execution DTO from the platform, if any (read-only ``property``;
            backed by ``_dto``).
        name: Optional user label; writable until execution ``id`` is set, then read-only
            (``property``; backed by ``_name``).
        runtime: Elapsed seconds from DTO ``startedAt`` to ``completedAt`` or now; see property.
        tool_key: Platform tool key identifying this execution type (class attribute on
            concrete subclasses; may be updated from the DTO in :meth:`update_from_dto`).
        tool_version: Version string for the tool (updated from the DTO like ``tool_key``).
        _id: Internal storage for the execution UUID; use :attr:`id` for reads. Subclasses
            and tests may assign before the property is wired from the platform.
        _dto: Internal storage for the raw execution dict; use :attr:`dto` for reads.
        _name: Internal storage for the display name; use :attr:`name` and its setter.
    """

    tool_key: str = ""

    def __init__(self, *, client: DeepOriginClient | None = None) -> None:
        """Initialize base execution state and chain mixin ``__init__`` via ``super()``."""
        super().__init__()
        self._estimate: float | None = None
        self._cost: float | None = None
        self._name: str | None = None
        self._id: str | None = None
        self._dto: dict[str, Any] | None = None

        if client is None:
            from deeporigin.platform.client import DeepOriginClient

            client = DeepOriginClient()
        self.client: DeepOriginClient = client

    @property
    def id(self) -> str | None:
        """Platform execution ID when set (read-only)."""
        return self._id

    @property
    def dto(self) -> dict[str, Any] | None:
        """Last tools execution DTO from the platform, if any."""
        return self._dto

    @property
    def runtime(self) -> float | None:
        """Seconds from DTO ``startedAt`` to ``completedAt`` or current UTC time.

        Uses :attr:`dto` (same shape as ``client.executions.get``). When
        ``completedAt`` is present, it is the end time; otherwise the end time is
        ``datetime.now(timezone.utc)``. Returns ``None`` if there is no DTO or
        ``startedAt`` is missing or empty.
        """
        if self._dto is None:
            return None
        started_raw = self._dto.get("startedAt")
        if not started_raw:
            return None
        started = parse_iso_timestamp_utc(started_raw)
        completed_raw = self._dto.get("completedAt")
        if completed_raw:
            end = parse_iso_timestamp_utc(completed_raw)
        else:
            end = datetime.now(timezone.utc)
        return (end - started).total_seconds()

    @property
    def estimate(self) -> float | None:
        """Cost estimate in dollars, populated when the platform returns a quotation.

        Set after ``run(quote=True)``, ``start(quote=True)``, or any call with
        ``approve_amount=0``. ``None`` until a quotation result is received.
        This property cannot be set manually."""
        return self._estimate

    @property
    def cost(self) -> float | None:
        """Actual cost in dollars, set after execution completes.

        This property cannot be set manually."""
        return self._cost

    @property
    def name(self) -> str | None:
        """Optional user-defined label for this execution.

        May be set or changed only while ``id`` is unset. After an execution
        ID exists, ``name`` is read-only."""
        return self._name

    @name.setter
    def name(self, value: str | None) -> None:
        """Set ``name`` only before the platform assigns an execution ``id``."""
        if getattr(self, "_id", None) is not None:
            raise AttributeError("cannot assign to 'name': execution id is already set")
        self._name = value

    def _make_payload(
        self,
        *,
        approve_amount: int | None,
        sync: bool,
    ) -> dict[str, Any]:
        """Build the body dict for ``client.executions.create``.

        Args:
            approve_amount: ``0`` to request a quote only; ``None`` to omit the
                field (platform runs immediately); any positive value sets a
                spend cap.
            sync: ``True`` for blocking (sync) execution; ``False`` for async.

        Returns:
            Payload for ``executions.create``.

        Raises:
            NotImplementedError: Unless overridden by a concrete tool class.
        """
        raise NotImplementedError(
            f"{type(self).__qualname__} must implement _make_payload()."
        )

    def confirm(self) -> None:
        """Confirm a quoted tools execution on the platform.

        Requires :attr:`id` and ``status`` equal to ``"Quoted"``. Uses
        :meth:`~deeporigin.platform.executions.Executions.confirm` with
        :data:`~deeporigin.utils.constants.TOOL_EXECUTION_POST_TIMEOUT_SECONDS`
        (10 minutes) and ``retry=False``.

        Raises:
            ValueError: If there is no platform execution id or status is not
                ``"Quoted"``.
        """
        if self._id is None:
            raise ValueError(
                "Cannot confirm: no platform execution id (quote first or load via "
                "from_id)."
            )
        status = getattr(self, "status", None)
        if status != "Quoted":
            raise ValueError(
                f"Cannot confirm: execution is in {status!r} state, not 'Quoted'."
            )
        self.client.executions.confirm(  # ty:ignore[unresolved-attribute]
            self._id,
            timeout=TOOL_EXECUTION_POST_TIMEOUT_SECONDS,  # ty:ignore[unknown-argument]
            retry=False,
        )

    def _set_status(self, new_status: str) -> None:
        """Validate and apply a lifecycle state transition.

        Args:
            new_status: The target status to transition to.

        Raises:
            ValueError: If the transition from the current status is not allowed.
        """
        current = getattr(self, "status", None)
        allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {current!r} -> {new_status!r}. "
                f"Allowed transitions from {current!r}: {allowed}"
            )
        self.status = new_status

    def duplicate(self, *, client: DeepOriginClient | None = None) -> Self:
        """Create a fresh copy with the same configuration but no execution state.

        Useful after ``from_id()`` to re-run the same calculation.  The
        returned instance has no ``id``, ``status``, ``estimate``, or
        ``cost`` — it is ready for ``run()`` / ``start()``.

        Args:
            client: Optional API client for the new instance.
                Falls back to the current instance's client.

        Returns:
            A new instance sharing the same domain-specific configuration.
        """
        new = copy.copy(self)
        if hasattr(new, "_id"):
            new._id = None
        new._estimate = None
        new._cost = None
        for attr in ("status", "progress", "_dto"):
            if hasattr(new, attr):
                delattr(new, attr)
        if client is not None:
            new.client = client
        return new

    def update_from_dto(self, dto: dict[str, Any]) -> None:
        """Apply tools execution fields from ``dto`` onto this instance.

        Updates ``id``, pricing, lifecycle fields, and ``_dto`` the same
        way as :meth:`from_dto` for a newly created instance. Use after a live
        ``executions.create`` / ``sync()`` response to refresh state without
        constructing a new object (domain inputs on ``self`` are unchanged).

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).

        Raises:
            NotImplementedError: If ``type(self)`` has no ``tool_key`` (bare
                :class:`Execution`).
            ValueError: If the DTO ``tool.key`` does not match ``tool_key``.
        """
        cls = type(self)
        if not cls.tool_key:
            raise NotImplementedError(
                f"{cls.__qualname__}.update_from_dto requires a non-empty class tool_key."
            )

        tool_info = dto["tool"]
        dto_tool_key = tool_info["key"]
        expected_tool_key = cls.tool_key
        if dto_tool_key != expected_tool_key:
            raise ValueError(
                "Cannot apply execution DTO: "
                f"tool key mismatch (dto={dto_tool_key!r}, class={expected_tool_key!r})."
            )

        self._id = dto["executionId"]
        self._estimate = None
        self._cost = None
        self.tool_key = expected_tool_key
        self.tool_version = tool_info["version"]

        self.status = dto.get("status")
        self.progress = dto.get("progressReport")
        self.app = dto.get("app")
        self.approve_amount = dto.get("approveAmount")
        self.created_at = dto.get("createdAt")
        self.created_by = dto.get("createdBy")
        self.started_at = dto.get("startedAt")
        self.completed_at = dto.get("completedAt")
        self.session = dto.get("session")
        self._dto = dto
        self._name = dto.get("name")

        quotation = dto.get("quotationResult") or {}
        successful = quotation.get("successfulQuotations", [])
        if successful:
            price = successful[0].get("priceTotal")
            if price is not None:
                self._estimate = float(price)
            if self.status == "Succeeded" and price is not None:
                self._cost = float(price)

    def sync(self) -> None:
        """Fetch the latest tools execution from the platform and refresh fields.

        Calls ``client.executions.get`` for :attr:`id` and applies the response
        with :meth:`update_from_dto`. Use when the job may have changed outside
        this process (for example after submission from the web UI), to poll
        lifecycle state, or to refresh an instance built from an older DTO.
        Available on sync-only and async execution types alike.

        If ``executions.get`` returns a falsy value, this instance is left
        unchanged.

        Raises:
            ValueError: If this instance has no execution id yet.
            NotImplementedError: If ``type(self).tool_key`` is empty (bare
                :class:`Execution`).
            ValueError: If the returned DTO ``tool.key`` does not match this
                class (see :meth:`update_from_dto`).
        """
        exec_id = self._id
        if exec_id is None:
            raise ValueError("Cannot sync: no execution has been started (id is None).")
        cls = type(self)
        if not cls.tool_key:
            raise NotImplementedError(
                f"{cls.__qualname__}.sync requires a non-empty class tool_key."
            )
        result = self.client.executions.get(exec_id)  # ty:ignore[unresolved-attribute]
        if result:
            self.update_from_dto(result)

    @classmethod
    def from_dto(
        cls,
        dto: dict[str, Any],
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an instance from an execution DTO returned by the platform API.

        Creates a bare instance via ``object.__new__`` (bypassing ``__init__``)
        and populates common tools execution fields (including :attr:`name` from
        the DTO ``name`` field) via :meth:`update_from_dto`. If the instance
        defines ``_init_after_from_dto``
        (e.g. :class:`~deeporigin.drug_discovery.notebook_watch_mixin.NotebookWatchMixin`),
        it is called after common fields are set. Subclasses should call
        ``super().from_dto()`` then rehydrate domain-specific fields from
        ``instance._dto["userInputs"]``.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A partially-hydrated instance with common fields populated.

        Raises:
            NotImplementedError: If ``cls`` has no ``tool_key`` (bare
                :class:`Execution`).
            ValueError: If the DTO ``tool.key`` does not match ``cls.tool_key``.
        """
        if not cls.tool_key:
            raise NotImplementedError(
                f"{cls.__qualname__}.from_dto requires a non-empty class tool_key."
            )
        if client is None:
            from deeporigin.platform.client import DeepOriginClient

            client = DeepOriginClient()

        instance = object.__new__(cls)
        instance.client = client
        instance.update_from_dto(dto)

        post_init = getattr(instance, "_init_after_from_dto", None)
        if post_init is not None:
            post_init()

        return instance

    @classmethod
    def from_id(cls, id: str, *, client: DeepOriginClient | None = None) -> Self:
        """Construct an instance from an existing platform execution ID.

        Fetches the execution DTO via ``client.executions.get`` and delegates to
        :meth:`from_dto`. Concrete subclasses override :meth:`from_dto` to attach
        domain state from ``userInputs``.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A partially-hydrated instance with common fields populated.

        Raises:
            NotImplementedError: If ``cls`` has no ``tool_key`` (bare
                :class:`Execution`).
        """
        if not cls.tool_key:
            raise NotImplementedError(
                f"{cls.__qualname__}.from_id requires a non-empty class tool_key."
            )
        if client is None:
            from deeporigin.platform.client import DeepOriginClient

            client = DeepOriginClient()

        dto = client.executions.get(id)  # ty:ignore[unresolved-attribute]
        return cls.from_dto(dto, client=client)

    @classmethod
    def list(
        cls,
        *,
        client: DeepOriginClient | None = None,
        status: builtins.list[str] | None = None,
    ) -> builtins.list[Self]:
        """List executions of this tool type from the platform.

        Calls ``client.executions.list(fetch_all_pages=True, tool_key=...)``,
        then builds instances via :meth:`from_dto`. Optional ``status`` filters
        hydrated instances by ``instance.status``.

        Args:
            client: Optional API client. Uses the default if not provided.
            status: Optional list of statuses to keep (membership test).

        Returns:
            Instances of this class, one per matching execution.

        Raises:
            NotImplementedError: If ``cls`` has no ``tool_key`` (bare
                :class:`Execution`).
        """
        if not cls.tool_key:
            raise NotImplementedError(
                f"{cls.__qualname__}.list requires a non-empty class tool_key."
            )
        if client is None:
            from deeporigin.platform.client import DeepOriginClient

            client = DeepOriginClient()

        all_dtos = client.executions.list(  # ty:ignore[unresolved-attribute]
            fetch_all_pages=True,
            tool_key=cls.tool_key,
        ).get("data", [])
        all_dtos = [
            dto for dto in all_dtos if dto.get("tool", {}).get("key") == cls.tool_key
        ]

        instances = [cls.from_dto(dto, client=client) for dto in all_dtos]

        if status is not None:
            instances = [i for i in instances if i.status in status]

        return instances

    def _ensure_id(self) -> str:
        """Ensure this execution has a platform ID, raising if it does not.

        Returns:
            The execution ID string.

        Raises:
            ValueError: If the execution has no ID (i.e. it has not been started yet).
        """
        exec_id = getattr(self, "_id", None)
        if exec_id is None:
            raise ValueError(
                f"{type(self).__name__} has no execution ID. "
                "Call run() or start() to set an ID."
            )
        return exec_id

    def get_results(self, **kwargs: Any) -> Any:
        """Fetch results for this execution from the data platform.

        Thin wrapper around :meth:`deeporigin.platform.results.Results.get`
        scoped to this execution's ``compute_job_id``. Subclasses that need
        result-type-specific filtering (e.g. poses, prepared systems) should
        override this method and call the appropriate ``Results`` wrapper
        directly rather than teaching this base method about those filters.

        Args:
            **kwargs: Forwarded verbatim to
                :meth:`~deeporigin.platform.results.Results.get` (typically
                ``filter_dict``, ``limit``, ``select``).

        Returns:
            Result-explorer response dict with ``data`` and ``meta`` keys.

        Raises:
            ValueError: If the execution has no ID yet.
        """
        exec_id = getattr(self, "_id", None)
        if exec_id is None:
            raise ValueError(
                "Cannot get results: no execution has been started (id is None)."
            )
        return self.client.results.get(compute_job_id=exec_id, **kwargs)

    def get_user_logs(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        select: builtins.list[str] | None = None,
        with_total_count: bool = False,
    ) -> dict[str, Any] | None:
        """Search data-platform ``user_logs`` rows for this execution.

        Uses :meth:`deeporigin.platform.user_logs.UserLogs.search` with this
        execution's id (tools ``executionId``), stored as ``execution_id`` on
        ``user_logs`` rows — the same string passed to :meth:`get_results` as
        ``compute_job_id``.

        When no execution id is assigned yet, returns ``None`` without calling
        the API.

        Args:
            limit: Max rows to return (forwarded to ``UserLogs.search``).
            offset: Skip offset (forwarded).
            select: Columns to select (forwarded).
            with_total_count: Request total count from the server (forwarded).

        Returns:
            The search response dict (typically ``data`` / ``meta``), or
            ``None`` if this instance has no execution id yet.
        """
        exec_id = getattr(self, "_id", None)
        if exec_id is None:
            return None
        ul = self.client.user_logs
        if ul is None:
            return None
        return ul.search(
            execution_id=exec_id,
            limit=limit,
            offset=offset,
            select=select,
            with_total_count=with_total_count,
        )

    def __repr__(self) -> str:
        """Return a concise summary of the execution."""
        parts: builtins.list[str] = [type(self).__name__]
        if self._name is not None:
            parts.append(f"name={self._name!r}")
        exec_id = getattr(self, "_id", None)
        if exec_id:
            parts.append(f"id={exec_id!r}")
        status = getattr(self, "status", None)
        if status:
            parts.append(f"status={status!r}")
        if self.estimate is not None:
            parts.append(f"estimate=${self.estimate:.2f}")
        if self.cost is not None:
            parts.append(f"cost=${self.cost:.2f}")
        return f"<{' '.join(parts)}>"
