"""Mixins that compose execution capabilities for job classes.

These mixins are combined with ``Execution`` to build concrete types:

- ``QuoteMixin`` -- cost estimation via the functions or tools API
- ``SyncExecutableMixin`` -- blocking, stateless execution via ``run()``
- ``AsyncExecutableMixin`` -- async, stateful execution via ``start()``
- ``JupyterVizMixin`` -- notebook rendering via ``_repr_html_()``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import PlatformStatus

if TYPE_CHECKING:
    from typing import Self

    from deeporigin.platform.job import JobList


class QuoteMixin:
    """Adds ``quote()`` to request a cost estimate before execution.

    Subclasses should override ``quote()`` to call the appropriate API
    (functions or tools) with ``quote=True`` and populate ``self.estimate``.
    """

    def quote(self) -> None:
        """Request a cost estimate. Must be overridden by subclasses.

        Raises:
            NotImplementedError: Always, unless overridden.
        """
        raise NotImplementedError


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
    """Adds ``start()``, ``cancel()``, ``sync()``, ``from_id()``, and ``list()``
    for asynchronous, stateful execution backed by the platform tools API.

    Classes that include this mixin gain ``status`` and ``progress`` attributes
    tracking the platform lifecycle and execution progress respectively.
    """

    status: PlatformStatus | None
    progress: dict | None

    def __init__(self) -> None:
        """Initialize async-specific state."""
        super().__init__()
        self.status = None
        self.progress = None
        self._execution_dto: dict | None = None

    def start(self) -> None:
        """Submit a persisted execution to the platform.

        Assigns an execution ID and sets the initial status. Must be
        overridden by subclasses to build the tool payload.

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

        self.client.executions.cancel(execution_id=self.id)
        self.sync()

    def sync(self) -> None:
        """Sync status, cost, and estimate from the platform.

        Raises:
            ValueError: If the job has no execution ID.
        """
        if self.id is None:
            raise ValueError("Cannot sync: no execution has been started (id is None).")

        result = self.client.executions.get_execution(execution_id=self.id)
        if result:
            self._execution_dto = result
            self.status = result.get("status")
            self.progress = result.get("progressReport")

            quotation = result.get("quotationResult", {})
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
    def from_id(cls, id: str, *, client: DeepOriginClient | None = None) -> Self:
        """Construct an instance from an existing platform execution ID.

        Creates a bare instance via ``object.__new__`` (bypassing
        ``__init__``), fetches the execution DTO, and populates the
        common execution fields.  Subclasses should call
        ``super().from_id()`` then rehydrate domain-specific fields
        from ``instance._execution_dto["userInputs"]``.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A partially-hydrated instance with common fields populated.
        """
        if client is None:
            client = DeepOriginClient.get()

        dto = client.executions.get_execution(execution_id=id)
        tool_info = dto["tool"]

        instance = object.__new__(cls)

        instance.client = client
        instance._id = dto["executionId"]
        instance._estimate = None
        instance._cost = None
        instance.tool_key = tool_info["key"]
        instance.tool_version = tool_info["version"]

        instance.status = dto.get("status")
        instance.progress = dto.get("progressReport")
        instance._execution_dto = dto

        quotation = dto.get("quotationResult", {})
        successful = quotation.get("successfulQuotations", [])
        if successful:
            price = successful[0].get("priceTotal")
            if price is not None:
                instance._estimate = float(price)
            if instance.status == "Succeeded" and price is not None:
                instance._cost = float(price)

        return instance

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
            client = DeepOriginClient.get()

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
