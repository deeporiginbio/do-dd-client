"""Mixins that compose execution capabilities for job classes.

These mixins are combined with ``Execution`` to build concrete types:

- ``QuoteMixin`` -- cost estimation via the functions or tools API (tools API:
  implement ``get_quote_execution_dto``; shared validation in ``_apply_quotation_dto``)
- ``SyncExecutableMixin`` -- blocking, stateless execution via ``run()``
- ``AsyncExecutableMixin`` -- async, stateful execution via ``start()``
- ``JupyterVizMixin`` -- notebook rendering via ``_repr_html_()``
- ``NotebookWatchMixin`` -- live Jupyter HTML polling via ``watch_async()`` (see
  ``deeporigin.drug_discovery.notebook_watch_mixin``)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import PlatformStatus

if TYPE_CHECKING:
    from typing import Self

    from deeporigin.platform.job import JobList


class QuoteMixin:
    """Adds ``quote()`` to request a cost estimate before execution.

    Tools-API executors implement :meth:`get_quote_execution_dto` to build the
    payload and return the raw execution DTO from ``executions.create``; shared
    parsing lives in :meth:`_apply_quotation_dto`.

    Function-based flows may override :meth:`_quote_impl` entirely instead of
    :meth:`get_quote_execution_dto`.

    ``quote()`` enforces that a quotation can only be requested once: it raises
    if ``status`` is already ``"Quoted"`` or an execution ID is already assigned.
    """

    def quote(self) -> None:
        """Request a cost estimate.

        Guards against re-quoting: raises if the execution has already been
        quoted (``status == "Quoted"``) or if an execution ID has been assigned.

        Raises:
            ValueError: If the execution has already been quoted or started.
        """
        id_ = getattr(self, "id", None)
        status = getattr(self, "status", None)

        if status == "Quoted":
            raise ValueError(
                "Cannot quote: a quotation already exists for this execution. "
                "Call start() to confirm it."
            )
        if id_ is not None:
            raise ValueError(
                f"Cannot quote: execution already has id {id_!r} in {status!r} state."
            )
        self._quote_impl()

    def get_quote_execution_dto(self) -> dict[str, Any]:
        """Build the quote payload and return the tools API execution DTO.

        Tools-API subclasses implement this to call ``client.executions.create``
        with ``approveAmount: 0``. Function-based subclasses that override
        :meth:`_quote_impl` instead do not implement this method.

        Returns:
            Raw execution dictionary from the platform.

        Raises:
            NotImplementedError: If neither this method nor a full
                :meth:`_quote_impl` override is provided.
        """
        raise NotImplementedError(
            "Subclasses using the tools API must implement get_quote_execution_dto(), "
            "or override _quote_impl() for a non-tools quote path."
        )

    def _apply_quotation_dto(self, execution_dto: dict[str, Any]) -> None:
        """Validate ``quotationResult`` and set estimate, id, and status.

        Args:
            execution_dto: Response body from ``executions.create`` or equivalent.

        Raises:
            RuntimeError: If ``quotationResult`` or ``successfulQuotations`` is
                missing or invalid, there are no successful quotations, or
                ``priceTotal`` is missing on the first successful row.
        """
        if (
            "quotationResult" not in execution_dto
            or execution_dto["quotationResult"] is None
        ):
            raise RuntimeError("Quote failed: quotationResult is missing.")
        quotation = execution_dto["quotationResult"]
        if not isinstance(quotation, dict):
            raise RuntimeError("Quote failed: quotationResult is invalid.")
        if (
            "successfulQuotations" not in quotation
            or quotation["successfulQuotations"] is None
        ):
            raise RuntimeError("Quote failed: successfulQuotations is missing.")
        successful = quotation["successfulQuotations"]
        if not isinstance(successful, list):
            raise RuntimeError("Quote failed: successfulQuotations is invalid.")
        if not successful:
            raise RuntimeError("Quote failed: no successful quotations.")
        price = successful[0].get("priceTotal")
        if price is None:
            raise RuntimeError("Quote failed: priceTotal is missing.")

        self._estimate = float(price)
        self._id = execution_dto.get("executionId")
        self.status = execution_dto.get("status")

    def _quote_impl(self) -> None:
        """Fetch a tools API quote DTO and apply it to this execution.

        Default for tools-API jobs. Override entirely for function-based quoting.

        Raises:
            NotImplementedError: If :meth:`get_quote_execution_dto` is not implemented.
            RuntimeError: If the API response fails quotation validation.
        """
        dto = self.get_quote_execution_dto()
        self._apply_quotation_dto(dto)


class SyncExecutableMixin:
    """Adds ``run()`` for synchronous, blocking execution.

    The ``run()`` call does **not** create a persisted execution record,
    does not assign an execution ID, and cannot be recovered later.
    """

    def run(self):
        """Execute synchronously. Must be overridden by subclasses.

        Raises:
            NotImplementedError: Always, unless overridden.
        """
        raise NotImplementedError


class AsyncExecutableMixin:
    """Adds ``start()``, ``cancel()``, ``sync()``, ``from_id()``, ``from_dto()``,
    and ``list()`` for asynchronous, stateful execution backed by the platform
    tools API.

    Classes that include this mixin gain ``status`` and ``progress`` attributes
    tracking the platform lifecycle and execution progress respectively.
    """

    status: PlatformStatus | None
    progress: dict | None
    app: str | None
    approve_amount: int | None
    created_at: str | None
    created_by: str | None
    started_at: str | None
    completed_at: str | None
    session: str | None

    def __init__(self) -> None:
        """Initialize async-specific state."""
        super().__init__()
        self.status = None
        self.progress = None
        self.app = None
        self.approve_amount = None
        self.created_at = None
        self.created_by = None
        self.started_at = None
        self.completed_at = None
        self.session = None
        self._execution_dto: dict | None = None

    def start(self, **kwargs) -> None:
        """Submit a persisted execution to the platform.

        Two valid paths depending on current status:

        - ``None``: no execution exists yet — calls ``_start_impl`` to
          create and submit a new one.
        - ``"Quoted"``: a cost-approved execution already exists — calls
          ``confirm`` on the platform to promote it, then syncs state.

        All other statuses raise immediately to prevent re-submission.

        Args:
            **kwargs: Forwarded to ``_start_impl`` (only used when
                status is ``None``).

        Raises:
            ValueError: If the current status does not permit starting.
        """
        if self.status is None:
            self._start_impl(**kwargs)
        elif self.status == "Quoted":
            self.client.executions.confirm(self.id)
            self.sync()
        else:
            raise ValueError(
                f"Cannot start: execution is already in {self.status!r} state. "
                f"start() is only allowed when status is None or 'Quoted'."
            )

    def _start_impl(self, **kwargs) -> None:
        """Perform the actual submission. Must be overridden by subclasses.

        Args:
            **kwargs: Tool-specific keyword arguments.

        Raises:
            NotImplementedError: Always, unless overridden.
        """
        raise NotImplementedError

    def cancel(self) -> None:
        """Cancel a running or queued execution.

        Raises:
            ValueError: If the job has no execution ID.
            ValueError: If the job is not in a cancellable state.
        """
        if self.id is None:
            raise ValueError(
                "Cannot cancel: no execution has been started (id is None)."
            )

        cancellable = {"Created", "Queued", "Running"}
        if self.status not in cancellable:
            raise ValueError(
                f"Cannot cancel: job is in {self.status!r} state. "
                f"Only jobs in {cancellable} can be cancelled."
            )

        self.client.executions.cancel(self.id)
        self.sync()

    def sync(self) -> None:
        """Sync status, cost, and estimate from the platform.

        Raises:
            ValueError: If the job has no execution ID.
        """
        if self.id is None:
            raise ValueError("Cannot sync: no execution has been started (id is None).")

        result = self.client.executions.get(self.id)
        if result:
            self._execution_dto = result
            self.status = result.get("status")
            self.progress = result.get("progressReport")
            self._name = result.get("name")
            self.app = result.get("app")
            self.approve_amount = result.get("approveAmount")
            self.created_at = result.get("createdAt")
            self.created_by = result.get("createdBy")
            self.started_at = result.get("startedAt")
            self.completed_at = result.get("completedAt")
            self.session = result.get("session")

            quotation = result.get("quotationResult") or {}
            successful = quotation.get("successfulQuotations", [])
            if successful:
                price = successful[0].get("priceTotal")
                if price is not None:
                    self._estimate = float(price)

            if self.status == "Succeeded" and successful:
                price = successful[0].get("priceTotal")
                if price is not None:
                    self._cost = float(price)

    @classmethod
    def from_dto(
        cls,
        dto: dict,
        *,
        client: DeepOriginClient | None = None,
    ) -> Self:
        """Construct an instance from an execution DTO returned by the platform API.

        Creates a bare instance via ``object.__new__`` (bypassing
        ``__init__``) and populates the common execution fields (including
        :attr:`~deeporigin.drug_discovery.execution.Execution.name` from the
        DTO ``name`` field).  Subclasses should call ``super().from_dto()``
        then rehydrate domain-specific fields from
        ``instance._execution_dto["userInputs"]``.

        Args:
            dto: Execution payload (same shape as ``client.executions.get``).
            client: Optional API client. Uses the default if not provided.

        Returns:
            A partially-hydrated instance with common fields populated.
        """
        if client is None:
            client = DeepOriginClient()

        tool_info = dto["tool"]
        dto_tool_key = tool_info["key"]
        expected_tool_key = cls.tool_key
        if dto_tool_key != expected_tool_key:
            raise ValueError(
                "Cannot rehydrate execution from DTO: "
                f"tool key mismatch (dto={dto_tool_key!r}, class={expected_tool_key!r})."
            )

        # Bypass __init__ so subclasses can rehydrate domain fields
        # (e.g. _protein, _ligands) from the DTO instead of constructor args.
        # All Execution-level attributes are set explicitly below.
        instance = object.__new__(cls)

        instance.client = client
        instance._id = dto["executionId"]
        instance._estimate = None
        instance._cost = None
        instance.tool_key = expected_tool_key
        instance.tool_version = tool_info["version"]

        instance.status = dto.get("status")
        instance.progress = dto.get("progressReport")
        instance.app = dto.get("app")
        instance.approve_amount = dto.get("approveAmount")
        instance.created_at = dto.get("createdAt")
        instance.created_by = dto.get("createdBy")
        instance.started_at = dto.get("startedAt")
        instance.completed_at = dto.get("completedAt")
        instance.session = dto.get("session")
        instance._execution_dto = dto
        instance._name = dto.get("name")

        quotation = dto.get("quotationResult") or {}
        successful = quotation.get("successfulQuotations", [])
        if successful:
            price = successful[0].get("priceTotal")
            if price is not None:
                instance._estimate = float(price)
            if instance.status == "Succeeded" and price is not None:
                instance._cost = float(price)

        return instance

    @classmethod
    def from_id(cls, id: str, *, client: DeepOriginClient | None = None) -> Self:
        """Construct an instance from an existing platform execution ID.

        Fetches the execution DTO via ``client.executions.get`` and delegates
        to :meth:`from_dto`.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A partially-hydrated instance with common fields populated.
        """
        if client is None:
            client = DeepOriginClient()

        dto = client.executions.get(id)
        return cls.from_dto(dto, client=client)

    @classmethod
    def list(
        cls,
        *,
        client: DeepOriginClient | None = None,
        status: list[str] | None = None,
    ) -> JobList:
        """List executions of this tool type from the platform.

        Args:
            client: Optional API client. Uses the default if not provided.
            status: Optional list of statuses to filter by.

        Returns:
            A ``JobList`` of matching executions.
        """
        from deeporigin.platform.job import JobList as PlatformJobList

        if client is None:
            client = DeepOriginClient()

        jobs = PlatformJobList.list(
            client=client,
            tool_key=cls.tool_key,
        )

        if status is not None:
            jobs = jobs.filter(status=status)

        return jobs


class JupyterVizMixin:
    """Adds notebook-friendly rendering via ``_repr_html_()``."""

    def _repr_html_(self) -> str:
        """Render this execution as HTML for Jupyter display.

        Returns:
            HTML string.
        """
        return f"<pre>{self!r}</pre>"
