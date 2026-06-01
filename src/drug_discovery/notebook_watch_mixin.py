"""Mixin for live Jupyter HTML updates while polling platform execution state.

- :meth:`NotebookWatchMixin.watch` — by default ``await`` returns immediately with a
  background :class:`asyncio.Task` that updates the notebook display.
- Pass ``blocking=True`` or set env :data:`~deeporigin.utils.constants.JOB_WATCH_BLOCK_ENV`
  to block the cell until the execution is terminal (e.g. ``nbconvert --execute``).

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
from deeporigin.utils.constants import JOB_WATCH_BLOCK_ENV
from deeporigin.utils.env import get_bool_env

_MAX_CONSECUTIVE_ERRORS = 10


def _strip_or_none(value: object) -> str | None:
    """Return a stripped non-empty string, or ``None`` for missing or blank values.

    Used when passing tool metadata into :class:`~deeporigin.platform.execution_display.ExecutionDisplay`.
    """
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


class NotebookWatchMixin:
    """Poll ``sync()`` and refresh a Jupyter HTML display for one execution.

    Must be mixed with :class:`~deeporigin.drug_discovery.execution.Execution` and
    :class:`~deeporigin.drug_discovery.execution_mixins.AsyncExecutableMixin` so
    ``id``, ``status``, ``sync()``, ``client``, and ``_dto`` are normal
    instance attributes (see
    :meth:`~deeporigin.drug_discovery.execution_mixins.AsyncExecutableMixin.__init__`).
    """

    # Populated by AsyncExecutableMixin; referenced here for type checkers.
    _dto: dict | None

    _watch_task: Task | None
    _display_id: str | None
    _last_html: str | None

    def __init__(self) -> None:
        """Initialize watch-related instance state."""
        super().__init__()
        self._watch_task = None
        self._display_id = None
        self._last_html = None

    def _init_after_from_dto(self) -> None:
        """Set notebook watch attributes when the instance skipped ``__init__``.

        :meth:`~deeporigin.drug_discovery.execution.Execution.from_dto`
        builds instances with ``object.__new__``, so this mixin is never
        initialized unless we patch up here.
        """
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

        dto = self._dto
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
                tool_key=_strip_or_none(getattr(self, "tool_key", None)),
                tool_version=_strip_or_none(getattr(self, "tool_version", None)),
            ).render_html(will_auto_update=False)
        else:
            html = self._render_execution_html(will_auto_update=False)
        display(HTML(html))

    @beartype
    def stop_watching(self) -> None:
        """Cancel an in-flight watch loop if one is running.

        Safe to call when no watch is active. Does not cancel the caller's
        current task when invoked from inside the watch loop.
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
                if self._dto is None:
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

    async def _watch_until_terminal(self, *, interval: float = 5.0) -> None:
        """Poll the platform and update a Jupyter display until a terminal state.

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

            if self._dto is None:
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
    def _watch_should_block(self, *, blocking: bool) -> bool:
        """Return whether :meth:`watch` should await the poll loop before returning.

        Args:
            blocking: Explicit request from the ``blocking`` keyword argument.

        Returns:
            True if the watch loop should run inline (blocking the caller).
        """
        return blocking or get_bool_env(JOB_WATCH_BLOCK_ENV, default=False)

    @beartype
    async def watch(
        self,
        *,
        interval: float = 5.0,
        blocking: bool = False,
    ) -> Task | None:
        """Start live notebook updates; optionally block until the job finishes.

        By default, **awaiting** this coroutine finishes in one event-loop turn,
        so the cell returns while the display keeps updating in the background.
        Use this when you need to run other cells while the job runs::

            task = await abfe.watch()

        Set ``blocking=True`` or export ``JOB_WATCH_BLOCK=1`` (truthy values:
        ``1``, ``true``, ``yes``, ``on``) to run the poll loop inline so the cell
        does not return until a terminal state — useful for ``nbconvert --execute``
        and doc CI (see :data:`~deeporigin.utils.constants.JOB_WATCH_BLOCK_ENV`)::

            await abfe.watch(blocking=True)
            # or: export JOB_WATCH_BLOCK=1

        Args:
            interval: Seconds between polls.
            blocking: When True, await the watch loop instead of returning a
                background task. Also blocks when ``JOB_WATCH_BLOCK`` is truthy.

        Returns:
            The background task when not blocking; ``None`` when blocking.
            Cancel a background watch with :meth:`stop_watching` or ``task.cancel()``.
        """
        self.stop_watching()
        if self._watch_should_block(blocking=blocking):
            await self._watch_until_terminal(interval=interval)
            return None
        return asyncio.create_task(self._watch_until_terminal(interval=interval))
