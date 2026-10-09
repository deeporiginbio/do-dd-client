"""Minimal reader for the gateway's server-sent event (SSE) notification streams.

The SSE service sends ``filters.dirty`` frames that name which of the
client-assigned filters went dirty. Frames carry no domain data: a client
re-reads the authoritative state over REST when one arrives.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import socket
import threading
from typing import TYPE_CHECKING

import httpx

from deeporigin.utils.constants import (
    SSE_CONNECT_TIMEOUT_SECONDS,
    SSE_RETRYABLE_STATUS_CODES,
)

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

FILTERS_DIRTY_FRAME_TYPE = "filters.dirty"


class StreamUnavailableError(Exception):
    """The gateway refused an SSE stream with a status worth reconnecting on."""

    def __init__(self, status_code: int) -> None:
        """Store the refusal status.

        Args:
            status_code: HTTP status of the refused stream.
        """
        super().__init__(f"SSE stream unavailable (HTTP {status_code})")
        self.status_code = status_code


def iter_dirty_filters(response: httpx.Response) -> Iterator[set[str] | None]:
    """Parse an open SSE response into dirty-filter notifications.

    Args:
        response: A streamed ``text/event-stream`` response.

    Yields:
        The set of filter ids named by each ``filters.dirty`` frame, or
        ``None`` for a heartbeat comment or ``retry:`` line. ``None`` is a
        liveness tick for deadline checks, not a reason to re-read state.
        The generator returns when the server closes the stream.
    """
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line.startswith((":", "retry:")):
            yield None
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").removeprefix(" "))
        elif line == "" and data_lines:
            dirty = _dirty_filters_from_data("\n".join(data_lines))
            data_lines = []
            if dirty is not None:
                yield dirty


def _dirty_filters_from_data(data: str) -> set[str] | None:
    """Extract filter ids from one SSE ``data`` payload.

    Args:
        data: The joined ``data`` lines of a single event.

    Returns:
        The filter ids of a ``filters.dirty`` frame, or ``None`` for any
        other or unparseable payload.
    """
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != FILTERS_DIRTY_FRAME_TYPE:
        return None
    filters = payload.get("filters")
    if not isinstance(filters, list):
        return set()
    return {str(f) for f in filters}


@contextmanager
def open_project_stream(
    client: DeepOriginClient,
    *,
    project_id: str,
    filters: dict[str, str],
    read_timeout: float,
) -> Iterator[httpx.Response]:
    """Open a project-scoped SSE stream through the gateway.

    Args:
        client: Authenticated client; its org key and bearer token are used.
        project_id: Project the stream is pinned to.
        filters: Client-assigned filter id to ref pattern(s), e.g.
            ``{"execution": "execution:abc"}``. Each entry is sent as one
            ``filter=id=pattern`` query parameter.
        read_timeout: Seconds a read may block before ``httpx.ReadTimeout``.
            Also caps the connect, write and pool timeouts, so opening the
            stream cannot outlast it.

    Yields:
        The open streamed response; it is closed on exit.

    Raises:
        StreamUnavailableError: If the gateway refuses the stream with a status
            in :data:`~deeporigin.utils.constants.SSE_RETRYABLE_STATUS_CODES`.
        DeepOriginException: If the gateway refuses the stream with any other
            non-2xx status.
    """
    client.check_token()
    path = f"/sse/{client.org_key}/stream/{project_id}"
    request = client._client.build_request(
        "GET",
        path,
        params=[("filter", f"{fid}={pattern}") for fid, pattern in filters.items()],
        headers={"Accept": "text/event-stream"},
        timeout=httpx.Timeout(
            min(SSE_CONNECT_TIMEOUT_SECONDS, read_timeout), read=read_timeout
        ),
    )
    response = client._client.send(request, stream=True)
    try:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            response.read()
            if response.status_code in SSE_RETRYABLE_STATUS_CODES:
                raise StreamUnavailableError(response.status_code) from None
            client._handle_request_error(
                "GET", f"{path}?{request.url.query.decode()}", error
            )
        yield response
    finally:
        response.close()


@contextmanager
def abort_stream_after(response: httpx.Response, seconds: float) -> Iterator[None]:
    """Cut an open stream off once ``seconds`` have passed.

    A stream read blocks until the next frame, and the gateway sends one only
    every heartbeat interval, so a caller's deadline can pass mid-read. A timer
    shuts the connection's socket down at the deadline, which ends the blocked
    read at once; closing the response from another thread does not reliably
    interrupt it. Without a socket (e.g. a mock transport) the response is
    closed instead.

    Args:
        response: The open streamed response.
        seconds: Delay before the stream is cut off.

    Yields:
        Nothing; the timer is cancelled on exit.
    """

    def abort() -> None:
        """Shut the stream's socket down, or close the response without one."""
        network_stream = response.extensions.get("network_stream")
        sock = (
            network_stream.get_extra_info("socket")
            if network_stream is not None
            else None
        )
        if sock is None:
            response.close()
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    timer = threading.Timer(seconds, abort)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()
