"""Mixins that compose execution capabilities for job classes.

These mixins are combined with ``Execution`` to build concrete types:

- ``QuoteMixin`` -- platform execution ``id`` / ``_id``, cost estimation via
  ``quote`` → ``_quote_setup``, ``_get_quote``, ``_quote_apply`` (tools API:
  implement ``_get_quote``; shared parsing in ``_quote_apply``)
- ``SyncExecutableMixin`` -- blocking, stateless execution via ``run()``
- ``AsyncExecutableMixin`` -- async, stateful execution via ``start()``
- ``JupyterVizMixin`` -- notebook rendering via ``_repr_html_()``
- ``NotebookWatchMixin`` -- live Jupyter HTML polling via ``watch_async()`` (see
  ``deeporigin.drug_discovery.notebook_watch_mixin``)
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import PlatformStatus

if TYPE_CHECKING:
    from typing import Self


class QuoteMixin:
    """Adds platform execution :attr:`id` and ``quote()`` for cost estimates.

    The tools-service execution id is stored in :attr:`_id` and exposed read-only
    via :attr:`id` (set by :meth:`_quote_apply`, async ``start()``, sync
    ``run()``, or rehydration helpers depending on the concrete class).

    Default flow: :meth:`quote` calls :meth:`_quote_setup`, :meth:`_get_quote`,
    then :meth:`_quote_apply`. Tools-API jobs implement :meth:`_get_quote` to
    call ``executions.create`` with ``approveAmount: 0`` and return the raw
    execution dict; :meth:`_quote_apply` validates ``quotationResult`` and sets
    estimate, id, and status.

    Function-based or custom flows may override :meth:`quote` entirely (typically
    calling :meth:`_quote_setup` first, then setting state without a tools DTO).

    ``quote()`` enforces that a quotation can only be requested once: it raises
    if ``status`` is already ``"Quoted"`` or an execution ID is already assigned.
    """

    _id: str | None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize execution id storage."""
        super().__init__(*args, **kwargs)
        self._id = None

    @property
    def id(self) -> str | None:
        """Platform execution ID when set (read-only)."""
        return self._id

    def quote(self) -> None:
        """Request a cost estimate.

        Runs :meth:`_quote_setup`, :meth:`_get_quote`, and :meth:`_quote_apply`.

        Raises:
            ValueError: If the execution has already been quoted or started.
            NotImplementedError: If :meth:`_get_quote` is not implemented.
            RuntimeError: If the API response fails quotation validation.
        """
        self._quote_setup()
        dto = self._get_quote()
        self._quote_apply(dto)

    def _quote_setup(self) -> None:
        """Guard: allow at most one quote before an execution id exists.

        Raises:
            ValueError: If status is ``Quoted`` or an execution id is set.
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

    def _get_quote(self) -> dict[str, Any]:
        """Build the quote request and return the tools API execution DTO.

        Subclasses using the default :meth:`quote` implement this to call
        ``client.executions.create`` with ``approveAmount: 0``.

        Returns:
            Raw execution dictionary from the platform.

        Raises:
            NotImplementedError: Unless overridden.
        """
        raise NotImplementedError(
            "Subclasses must implement _get_quote() for the tools API, or override "
            "quote() for a non-tools quote path."
        )

    def _quote_apply(self, execution_dto: dict[str, Any]) -> None:
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

    tool_key: str
    client: DeepOriginClient
    # Same backing field as :attr:`QuoteMixin._id` when both mixins are used.
    _id: str | None
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
            self.client.executions.confirm(self._id)
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
        if self._id is None:
            raise ValueError(
                "Cannot cancel: no execution has been started (id is None)."
            )

        cancellable = {"Created", "Queued", "Running"}
        if self.status not in cancellable:
            raise ValueError(
                f"Cannot cancel: job is in {self.status!r} state. "
                f"Only jobs in {cancellable} can be cancelled."
            )

        self.client.executions.cancel(self._id)
        self.sync()

    def sync(self) -> None:
        """Sync status, cost, and estimate from the platform.

        Raises:
            ValueError: If the job has no execution ID.
        """
        if self._id is None:
            raise ValueError("Cannot sync: no execution has been started (id is None).")

        result = self.client.executions.get(self._id)
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
        DTO ``name`` field).  If the instance defines ``_init_after_from_dto``
        (e.g. :class:`~deeporigin.drug_discovery.notebook_watch_mixin.NotebookWatchMixin`),
        it is called after common fields are set.  Subclasses should call
        ``super().from_dto()`` then rehydrate domain-specific fields from
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

        post_init = getattr(instance, "_init_after_from_dto", None)
        if post_init is not None:
            post_init()

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
        status: builtins.list[str] | None = None,
    ) -> builtins.list[Self]:
        """List executions of this tool type from the platform.

        Args:
            client: Optional API client. Uses the default if not provided.
            status: Optional list of statuses to filter by.

        Returns:
            Instances of this class, one per matching execution.
        """
        if client is None:
            client = DeepOriginClient()

        current_page = 0
        page_size = 1000
        all_dtos: builtins.list[dict] = []

        while True:
            response = client.executions.list(
                page=current_page,
                page_size=page_size,
                tool_key=cls.tool_key,
            )

            if not isinstance(response, dict):
                all_dtos.extend(response if isinstance(response, builtins.list) else [])
                break

            page_dtos = response.get("data", [])
            all_dtos.extend(page_dtos)

            count = response.get("count", 0)

            if count > page_size:
                if len(page_dtos) < page_size:
                    break
                if len(all_dtos) >= count:
                    break
                current_page += 1
            else:
                break

        all_dtos = [
            dto for dto in all_dtos if dto.get("tool", {}).get("key") == cls.tool_key
        ]

        instances = [cls.from_dto(dto, client=client) for dto in all_dtos]

        if status is not None:
            instances = [i for i in instances if i.status in status]

        return instances


class JupyterVizMixin:
    """Adds notebook-friendly rendering via ``_repr_html_()``."""

    def _repr_html_(self) -> str:
        """Render this execution as HTML for Jupyter display.

        Returns:
            HTML string.
        """
        return f"<pre>{self!r}</pre>"
