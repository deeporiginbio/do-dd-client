"""Mixins that compose execution capabilities for job classes.

These mixins are combined with ``Execution`` to build concrete types:

- ``QuoteMixin`` -- cost estimation via the functions or tools API
- ``SyncExecutableMixin`` -- blocking, stateless execution via ``run()``
- ``AsyncExecutableMixin`` -- async, stateful execution via ``start()``
- ``JupyterVizMixin`` -- notebook rendering via ``_repr_html_()``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from beartype import beartype

from deeporigin.drug_discovery.execution import PlatformStatus
from deeporigin.platform.client import DeepOriginClient

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
    """Adds ``start()``, ``cancel()``, ``refresh()``, ``from_id()``, and ``list()``
    for asynchronous, stateful execution backed by the platform tools API.

    Classes that include this mixin gain a ``status`` attribute tracking the
    platform lifecycle (``None`` -> ``Created`` -> ``Queued`` -> ... -> terminal).
    """

    status: PlatformStatus | None

    def _init_async(self) -> None:
        """Initialize async-specific state. Call from subclass ``__init__``."""
        with self._system_update():
            self.status = None
            self._execution_dto: dict | None = None

    @beartype
    def start(self, *, client: DeepOriginClient | None = None) -> None:
        """Submit a persisted execution to the platform.

        Assigns an execution ID and sets the initial status. Must be
        overridden by subclasses to build the tool payload.

        Args:
            client: Optional API client. Uses the default if not provided.

        Raises:
            NotImplementedError: Always, unless overridden.
        """
        raise NotImplementedError

    @beartype
    def cancel(self, *, client: DeepOriginClient | None = None) -> None:
        """Cancel a running or queued execution.

        Args:
            client: Optional API client. Uses the default if not provided.

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

        if client is None:
            client = DeepOriginClient.get()

        client.executions.cancel(execution_id=self.id)
        self.refresh(client=client)

    @beartype
    def refresh(self, *, client: DeepOriginClient | None = None) -> None:
        """Sync status, cost, and estimate from the platform.

        Args:
            client: Optional API client. Uses the default if not provided.

        Raises:
            ValueError: If the job has no execution ID.
        """
        if self.id is None:
            raise ValueError(
                "Cannot refresh: no execution has been started (id is None)."
            )

        if client is None:
            client = DeepOriginClient.get()

        result = client.executions.get_execution(execution_id=self.id)
        if result:
            with self._system_update():
                self._execution_dto = result
                self.status = result.get("status")

                quotation = result.get("quotationResult", {})
                successful = quotation.get("successfulQuotations", [])
                if successful:
                    price = successful[0].get("priceTotal")
                    if price is not None:
                        self.estimate = float(price)

                if self.status == "Succeeded":
                    if successful:
                        price = successful[0].get("priceTotal")
                        if price is not None:
                            self.cost = float(price)

    @classmethod
    def from_id(cls, id: str, *, client: DeepOriginClient | None = None) -> Self:
        """Construct an instance from an existing platform execution ID.

        Rehydrates the object by fetching the execution record and
        reconstructing input entities (protein, ligands, etc.) from
        the stored metadata.

        Args:
            id: Platform execution ID.
            client: Optional API client. Uses the default if not provided.

        Returns:
            A fully-hydrated instance of this class.

        Raises:
            NotImplementedError: Always, unless overridden by a subclass.
        """
        raise NotImplementedError(
            f"{cls.__name__}.from_id() must be implemented by the subclass."
        )

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
