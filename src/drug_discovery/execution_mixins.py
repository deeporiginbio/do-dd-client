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

from datetime import datetime, timezone
from typing import Any

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import PlatformStatus
from deeporigin.utils.constants import TOOL_EXECUTION_POST_TIMEOUT_SECONDS


def _parse_iso_timestamp_utc(value: str) -> datetime:
    """Parse a tools API ISO-8601 timestamp (e.g. ``startedAt``, ``completedAt``) to UTC."""
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class QuoteMixin:
    """Adds platform execution :attr:`id` and ``quote()`` for cost estimates.

    The tools-service execution id is stored in :attr:`_id` and exposed read-only
    via :attr:`id` (set by :meth:`_quote_apply`, async ``start()``, sync
    ``run()``, or rehydration helpers depending on the concrete class).

    Default flow: :meth:`quote` calls :meth:`_quote_setup`, :meth:`_quote_impl`
    (which uses :meth:`_get_quote` and :meth:`_quote_apply` for tools jobs), then
    :meth:`_quote_finalize`. Tools-API jobs implement :meth:`_get_quote` to
    call ``executions.create`` with ``approveAmount: 0`` and return the raw
    execution dict; :meth:`_quote_apply` validates ``quotationResult`` and sets
    estimate, id, and status.

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

        Runs :meth:`_quote_setup`, :meth:`_quote_impl`, and :meth:`_quote_finalize`.

        Raises:
            ValueError: If the execution has already been quoted or started.
            NotImplementedError: If :meth:`_get_quote` is not implemented.
            RuntimeError: If the API response fails quotation validation.
        """
        self._quote_setup()
        self._quote_impl()
        self._quote_finalize()

    def _quote_impl(self) -> None:
        """Perform the quote request and populate estimate (and optional id).

        Default implementation calls the tools API via :meth:`_get_quote` and
        :meth:`_quote_apply`. Override for function-quote or other non-tools paths.
        """
        dto = self._get_quote()
        self._quote_apply(dto)

    def _quote_finalize(self) -> None:
        """Apply the single-quote contract when no platform execution id exists yet.

        Tools-API quotations set ``status`` (and often ``id``) from the execution
        DTO in :meth:`_quote_apply`. Sync function quotations leave ``id`` unset
        until :meth:`~deeporigin.drug_discovery.execution_mixins.SyncExecutableMixin.run`;
        those paths get ``status='Quoted'`` here so :meth:`_quote_setup` blocks
        repeat quotes.
        """
        if self.id is None:
            self.status = "Quoted"

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

    Subclasses implement ``run()`` as a blocking call. For tools backed by
    ``client.executions.create`` with ``sync=True``, the response is typically a
    completed execution DTO that includes ``executionId`` and billing fields.
    Other subclasses may call legacy synchronous APIs instead; behaviour is
    defined per class.
    """

    def run(self):
        """Execute synchronously. Must be overridden by subclasses.

        Raises:
            NotImplementedError: Always, unless overridden.
        """
        raise NotImplementedError


class AsyncExecutableMixin:
    """Adds ``start()``, ``cancel()``, and ``sync()`` for asynchronous,
    stateful execution backed by the platform tools API.

    Listing and rehydration use :meth:`~deeporigin.drug_discovery.execution.Execution.list`,
    :meth:`~deeporigin.drug_discovery.execution.Execution.from_id`, and
    :meth:`~deeporigin.drug_discovery.execution.Execution.from_dto` on the
    composed class (subclasses override ``from_dto`` and call ``super()``).

    Classes that include this mixin gain ``status`` and ``progress`` attributes
    tracking the platform lifecycle and execution progress respectively, and a
    :attr:`runtime` property for elapsed seconds from ``startedAt`` to ``completedAt``
    (or now if still running) when ``startedAt`` is known.
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

    @property
    def runtime(self) -> float | None:
        """Seconds from ``_execution_dto["startedAt"]`` to ``completedAt`` or now.

        When ``completedAt`` is set, uses that as the end time; otherwise uses
        the current UTC time. Returns ``None`` if ``startedAt`` is unknown.
        """
        if self._execution_dto is None:
            return None
        started_raw = self._execution_dto.get("startedAt")
        if not started_raw:
            return None
        started = _parse_iso_timestamp_utc(started_raw)
        completed_raw = self._execution_dto.get("completedAt")
        if completed_raw:
            end = _parse_iso_timestamp_utc(completed_raw)
        else:
            end = datetime.now(timezone.utc)
        return (end - started).total_seconds()

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
            ValueError: If the current status does not permit starting, or if
                status is ``Quoted`` but the execution id (:attr:`_id`) is missing.
        """
        if self.status is None:
            self._start_impl(**kwargs)
        elif self.status == "Quoted":
            if self._id is None:
                raise ValueError(
                    "Cannot start: quoted execution has no platform id (_id is None)."
                )
            self.client.executions.confirm(  # ty:ignore[unresolved-attribute]
                self._id,
                timeout=TOOL_EXECUTION_POST_TIMEOUT_SECONDS,
                retry=False,
            )
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
