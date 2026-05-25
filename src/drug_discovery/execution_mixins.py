"""Mixins that compose execution capabilities for job classes.

These mixins are combined with ``Execution`` to build concrete types:

- ``SyncExecutableMixin`` -- blocking execution via ``run()``
- ``AsyncExecutableMixin`` -- async, stateful execution via ``start()`` and
  ``cancel()`` (platform refresh uses
  :meth:`~deeporigin.drug_discovery.execution.Execution.sync` on the base class)
- ``NotebookWatchMixin`` -- live Jupyter HTML polling via ``watch_async()`` (see
  ``deeporigin.drug_discovery.notebook_watch_mixin``)

Both ``run()`` and ``start()`` accept ``quote=True`` (sugar for
``approve_amount=0``) and an explicit ``approve_amount``. If the platform returns
a ``Quoted`` DTO the instance is left in that state with no automatic
confirmation. ``confirm()``, :meth:`~deeporigin.drug_discovery.execution.Execution.sync`,
and :attr:`~deeporigin.drug_discovery.execution.Execution.runtime` live on
:class:`~deeporigin.drug_discovery.execution.Execution`.
"""

from __future__ import annotations

from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import PlatformStatus


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
    """Adds ``start()`` and ``cancel()`` for asynchronous, stateful execution
    backed by the platform tools API.

    Platform state refresh uses :meth:`~deeporigin.drug_discovery.execution.Execution.sync`
    (inherited from :class:`~deeporigin.drug_discovery.execution.Execution`), so
    sync-only execution types can poll the same way after an ``id`` exists.

    Listing and rehydration use :meth:`~deeporigin.drug_discovery.execution.Execution.list`,
    :meth:`~deeporigin.drug_discovery.execution.Execution.from_id`, and
    :meth:`~deeporigin.drug_discovery.execution.Execution.from_dto` on the
    composed class (subclasses override ``from_dto`` and call ``super()``).

    Classes that include this mixin gain ``status`` and ``progress`` attributes
    tracking the platform lifecycle and execution progress respectively. Elapsed
    time is available on :class:`~deeporigin.drug_discovery.execution.Execution`
    via :attr:`~deeporigin.drug_discovery.execution.Execution.runtime`.
    """

    tool_key: str
    client: DeepOriginClient
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
        self._dto: dict | None = None

    def start(
        self,
        *,
        quote: bool = False,
        approve_amount: int | None = None,
        **kwargs,
    ) -> None:
        """Submit a persisted async execution to the platform.

        Only valid when ``status`` is ``None`` (no execution exists yet).
        All other statuses raise immediately to prevent re-submission.

        Pass ``quote=True`` or ``approve_amount=0`` to request a cost estimate
        without running. If the platform returns a ``Quoted`` DTO the instance
        is left in that state — call :meth:`~deeporigin.drug_discovery.execution.Execution.confirm`
        explicitly to proceed.

        Args:
            quote: Shorthand for ``approve_amount=0``. Takes precedence when both
                ``quote`` and ``approve_amount`` are provided.
            approve_amount: Spend cap passed to the platform as ``approveAmount``.
                ``0`` requests a quote only. ``None`` omits the field (platform
                runs immediately).
            **kwargs: Forwarded verbatim to ``_start_impl``.

        Raises:
            ValueError: If the current status is not ``None``.
        """
        if self.status is not None:
            raise ValueError(
                f"Cannot start: execution is already in {self.status!r} state. "
                "start() is only allowed when status is None."
            )
        resolved_amount = 0 if quote else approve_amount
        self._start_impl(approve_amount=resolved_amount, **kwargs)

    def _start_impl(self, *, approve_amount: int | None = None, **kwargs) -> None:
        """Perform the actual async submission. Must be overridden by subclasses.

        Args:
            approve_amount: Resolved spend cap (``0`` for quote-only, ``None``
                to run immediately, or a positive value for a spend cap).
            **kwargs: Additional tool-specific keyword arguments.

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

        cancellable = {"Created", "Queued", "Running", "DataIngesting"}
        if self.status not in cancellable:
            raise ValueError(
                f"Cannot cancel: job is in {self.status!r} state. "
                f"Only jobs in {cancellable} can be cancelled."
            )

        self.client.executions.cancel(self._id)  # ty:ignore[unresolved-attribute]
        self.sync()
