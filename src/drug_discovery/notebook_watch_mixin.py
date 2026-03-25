"""Mixin for live Jupyter HTML updates while polling platform execution state.

- :meth:`NotebookWatchMixin.watch_async` — ``await`` until the job reaches a
  terminal state (blocks the notebook cell).
- :meth:`NotebookWatchMixin.watch` — ``await`` returns immediately with a
  background :class:`asyncio.Task` (non-blocking cell; closest to legacy
  ``Job.watch()``).

Does not use ``nest_asyncio``.
"""

from __future__ import annotations

import asyncio
from asyncio import Task
from contextlib import suppress
import uuid

from beartype import beartype
from IPython.display import HTML, display, update_display

from deeporigin.platform.constants import TERMINAL_STATES

_MAX_CONSECUTIVE_ERRORS = 10


class NotebookWatchMixin:
    """Poll ``sync()`` and refresh a Jupyter HTML display for one execution.

    Must be mixed with :class:`~deeporigin.drug_discovery.execution.Execution` and
    :class:`~deeporigin.drug_discovery.execution_mixins.AsyncExecutableMixin` so
    ``id``, ``status``, ``sync()``, ``client``, and ``_execution_dto`` are normal
    instance attributes (see
    :meth:`~deeporigin.drug_discovery.execution_mixins.AsyncExecutableMixin.__init__`).
    """

    # Populated by AsyncExecutableMixin; referenced here for type checkers.
    _execution_dto: dict | None

    _watch_task: Task | None
    _display_id: str | None
    _last_html: str | None

    def __init__(self) -> None:
        """Initialize watch-related instance state."""
        super().__init__()
        self._watch_task = None
        self._display_id = None
        self._last_html = None

    @beartype
    def _is_terminal(self) -> bool:
        """Return True if the execution is in a platform terminal state."""
        status = self.status
        return status is not None and status in TERMINAL_STATES

    @beartype
    def _compose_error_overlay_html(self, *, message: str) -> str:
        """Build a transient error banner HTML string.

        Args:
            message: Error text to show in the banner.

        Returns:
            HTML fragment prepended to the last good render.
        """
        import time

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        return (
            "<div style='background: #fff4f4; border: 1px solid #f0b5b5; color: #8a1f1f;"
            " padding: 8px 12px; margin-bottom: 8px; border-radius: 6px;'>"
            f"Network/update issue at {timestamp}. Will retry automatically. Error: {message}"
            "</div>"
        )

    @beartype
    def _render_execution_html(self, *, will_auto_update: bool) -> str:
        """Render the execution card HTML (:class:`~deeporigin.platform.execution_display.ExecutionDisplay`).

        Args:
            will_auto_update: Whether the footer may show a live-update spinner.

        Returns:
            Rendered HTML string.

        Raises:
            ValueError: If there is no execution DTO after a successful sync path.
        """
        from deeporigin.platform.execution_display import ExecutionDisplay

        dto = self._execution_dto
        if dto is None:
            raise ValueError(
                "No execution data available. Call sync() first or ensure the execution exists."
            )
        return ExecutionDisplay.from_dto(dto).render_html(
            will_auto_update=will_auto_update
        )

    @beartype
    def show(self) -> None:
        """Display the current execution in Jupyter using the execution card HTML view.

        If no platform execution ID exists yet, shows the same card with a short notice
        instead of raising (see :meth:`~deeporigin.platform.execution_display.ExecutionDisplay.from_pending`).
        """
        from deeporigin.platform.execution_display import ExecutionDisplay

        if self.id is None:
            html = ExecutionDisplay.from_pending(
                name=self.name,
                status=self.status,
            ).render_html(will_auto_update=False)
        else:
            html = self._render_execution_html(will_auto_update=False)
        display(HTML(html))

    @beartype
    def stop_watching(self) -> None:
        """Cancel an in-flight :meth:`watch_async` loop if one is running.

        Safe to call when no watch is active. Does not cancel the caller's
        current task when invoked from inside :meth:`watch_async`.
        """
        t = self._watch_task
        if t is None:
            return
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if current is not None and t is current:
            return
        if not t.done():
            t.cancel()

    def _display_no_active_job_message(self) -> None:
        """Show the standard message when the execution is already terminal."""
        display(
            HTML(
                "<div style='color: gray;'>No active job to monitor. "
                "This display will not update.</div>"
            )
        )

    async def _finalize_watch_display(self, *, display_id: str) -> None:
        """Best-effort final sync and HTML refresh after the poll loop ends."""
        with suppress(Exception):
            await asyncio.to_thread(self.sync)
        with suppress(Exception):
            final_html = self._render_execution_html(will_auto_update=False)
            update_display(HTML(final_html), display_id=display_id)
        self._display_id = None

    async def _watch_poll_loop(self, *, display_id: str, interval: float) -> None:
        """Poll until terminal or too many consecutive errors."""
        consecutive_errors = 0
        while True:
            try:
                await asyncio.to_thread(self.sync)
                if self._execution_dto is None:
                    raise ValueError("Execution DTO missing after sync.")
                html = self._render_execution_html(will_auto_update=True)
                update_display(HTML(html), display_id=display_id)
                self._last_html = html
                consecutive_errors = 0
                if self._is_terminal():
                    break
            except Exception as e:
                consecutive_errors += 1
                banner = self._compose_error_overlay_html(message=str(e))
                fallback = (
                    self._last_html or "<div style='color: gray;'>No data yet.</div>"
                )
                update_display(HTML(banner + fallback), display_id=display_id)
                if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    error_msg = (
                        f"Stopped monitoring after {_MAX_CONSECUTIVE_ERRORS} "
                        f"consecutive errors. Last error: {str(e)}"
                    )
                    final_banner = self._compose_error_overlay_html(message=error_msg)
                    update_display(
                        HTML(final_banner + fallback),
                        display_id=display_id,
                    )
                    break
            await asyncio.sleep(interval)

    @beartype
    async def watch_async(self, *, interval: float = 5.0) -> None:
        """Poll the platform and update a Jupyter display until a terminal state.

        In notebooks use top-level ``await abfe.watch_async()``. In scripts use
        ``asyncio.run(abfe.watch_async())``.

        Args:
            interval: Seconds between polls after a successful update.

        Raises:
            ValueError: If ``id`` is None, or execution data is missing when required.
        """
        if self.id is None:
            raise ValueError(
                "Cannot watch: no execution has been started (id is None)."
            )

        self.stop_watching()

        self._watch_task = asyncio.current_task()
        display_id: str | None = None
        try:
            await asyncio.to_thread(self.sync)

            if self._execution_dto is None:
                raise ValueError(
                    "No execution data after sync. Cannot render execution view."
                )

            if self._is_terminal():
                self._display_no_active_job_message()
                html = self._render_execution_html(will_auto_update=False)
                display(HTML(html))
                return

            display_id = str(uuid.uuid4())
            self._display_id = display_id
            display(
                HTML("<div style='color: gray;'>Initializing...</div>"),
                display_id=display_id,
            )

            try:
                await self._watch_poll_loop(display_id=display_id, interval=interval)
            finally:
                if self._display_id is not None and display_id is not None:
                    await self._finalize_watch_display(display_id=display_id)
        finally:
            self._watch_task = None

    @beartype
    async def watch(self, *, interval: float = 5.0) -> Task:
        """Schedule :meth:`watch_async` and return the :class:`asyncio.Task` immediately.

        In Jupyter, **awaiting** this coroutine finishes in one event-loop turn,
        so the cell returns while the display keeps updating in the background
        (similar to legacy ``Job.watch()``). Use this when you need to run other
        cells while the job runs::

            task = await abfe.watch()

        To block until the job finishes, use :meth:`watch_async` instead::

            await abfe.watch_async()

        Args:
            interval: Seconds between polls; passed to :meth:`watch_async`.

        Returns:
            The task running :meth:`watch_async`. Cancel it with
            :meth:`stop_watching` or ``task.cancel()``.
        """
        self.stop_watching()
        return asyncio.create_task(self.watch_async(interval=interval))
