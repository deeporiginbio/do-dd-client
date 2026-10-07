"""Tests for :meth:`Executions.wait_for_ingestion` and the SSE reader."""

from collections.abc import Iterator
import json
import threading
import time
from unittest.mock import patch

import httpx
import pytest

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.sse import iter_dirty_filters

EXECUTION_ID = "exec-1"
PROJECT_ID = "proj-1"
ORG_KEY = "test_org"
STREAM_PATH = f"/sse/{ORG_KEY}/stream/{PROJECT_ID}"
SEARCH_PATH = f"/data-platform/{ORG_KEY}/executions/search"

HEARTBEAT = ": heartbeat\n\n"
RETRY = "retry: 3000\n\n"
DIRTY = 'data: {"type":"filters.dirty","filters":["execution"]}\n\n'


@pytest.fixture
def mock_client_config() -> Iterator[None]:
    """Configure a local client without a real token or config on disk."""
    with (
        patch("deeporigin.platform.client.get_token") as mock_get_token,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
        patch(
            "deeporigin.platform.client.DeepOriginClient.check_token"
        ) as mock_check_token,
    ):
        mock_get_token.return_value = "test_token"
        mock_get_value.return_value = {
            "env": "local",
            "org_key": ORG_KEY,
            "project_id": None,
        }
        mock_check_token.return_value = None
        yield


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """Record reconnect backoff sleeps instead of sleeping.

    Returns:
        The requested sleep durations, in order.
    """
    recorded: list[float] = []
    monkeypatch.setattr("deeporigin.platform.executions.time.sleep", recorded.append)
    return recorded


class FakeGateway:
    """Scripted gateway: one SSE body per connect, one status per search.

    The last stream body and the last status repeat once their scripts run out.
    """

    def __init__(
        self,
        *,
        streams: list[str | int | httpx.SyncByteStream],
        statuses: list[str | None],
    ) -> None:
        """Store the scripts.

        Args:
            streams: SSE body per connect, an HTTP status code to refuse it,
                or a byte stream to serve as-is.
            statuses: Row status per search, or ``None`` for no row yet.
        """
        self.streams = streams
        self.statuses = statuses
        self.calls: list[str] = []
        self.stream_requests: list[httpx.Request] = []
        self.search_bodies: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Serve one request.

        Args:
            request: Incoming request.

        Returns:
            The scripted response.
        """
        if request.url.path == STREAM_PATH:
            n = sum(c == "stream" for c in self.calls)
            self.calls.append("stream")
            self.stream_requests.append(request)
            body = self.streams[min(n, len(self.streams) - 1)]
            if isinstance(body, int):
                return httpx.Response(body, json={"message": "refused"})
            if isinstance(body, httpx.SyncByteStream):
                return httpx.Response(
                    200, headers={"Content-Type": "text/event-stream"}, stream=body
                )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=body.encode(),
            )
        if request.url.path == SEARCH_PATH:
            n = sum(c == "search" for c in self.calls)
            self.calls.append("search")
            self.search_bodies.append(json.loads(request.content))
            status = self.statuses[min(n, len(self.statuses) - 1)]
            rows = [] if status is None else [{"id": "dp-1", "status": status}]
            return httpx.Response(200, json={"data": rows, "meta": {}})
        return httpx.Response(404)

    def client(self) -> DeepOriginClient:
        """Build a client whose HTTP traffic goes to this fake.

        Returns:
            A client with a mock transport.
        """
        client = DeepOriginClient.from_local()
        client.org_key = ORG_KEY
        client._client = httpx.Client(
            transport=httpx.MockTransport(self.handler), base_url="http://test"
        )
        return client


def _wait(gateway: FakeGateway, **kwargs) -> dict:
    """Run ``wait_for_ingestion`` against a fake gateway.

    Args:
        gateway: The fake gateway.
        **kwargs: Overrides for ``wait_for_ingestion`` keyword arguments.

    Returns:
        The row returned by the wait.
    """
    kwargs.setdefault("project_id", PROJECT_ID)
    kwargs.setdefault("timeout", 5.0)
    return gateway.client().executions.wait_for_ingestion(EXECUTION_ID, **kwargs)


def test_already_terminal_on_first_read(mock_client_config) -> None:
    """A terminal row on the first read returns, with the stream opened first."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=["Completed"])

    row = _wait(gateway)

    assert row["status"] == "Completed"
    assert gateway.calls == ["stream", "search"]
    request = gateway.stream_requests[0]
    assert request.url.params.get_list("filter") == [
        f"execution=execution:{EXECUTION_ID}"
    ]
    assert request.headers["Accept"] == "text/event-stream"
    assert gateway.search_bodies[0]["filter"]["props"] == [
        {"column": "project_id", "op": "eq", "value": PROJECT_ID},
        {"column": "compute_job_id", "op": "eq", "value": EXECUTION_ID},
    ]


def test_terminal_after_ping(mock_client_config) -> None:
    """A heartbeat does not re-read; a ``filters.dirty`` frame does."""
    gateway = FakeGateway(
        streams=[RETRY + HEARTBEAT + DIRTY],
        statuses=["DataIngesting", "Completed"],
    )

    row = _wait(gateway)

    assert row["status"] == "Completed"
    assert gateway.calls == ["stream", "search", "search"]


def test_terminal_after_reconnect(mock_client_config, sleeps) -> None:
    """A stream closed by the gateway is reopened and the row re-read."""
    gateway = FakeGateway(
        streams=[HEARTBEAT, HEARTBEAT],
        statuses=["DataIngesting", "Completed"],
    )

    row = _wait(gateway)

    assert row["status"] == "Completed"
    assert gateway.calls == ["stream", "search", "stream", "search"]


def test_timeout(mock_client_config) -> None:
    """Ingestion that never finishes raises ``TimeoutError``."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=["DataIngesting"])

    with pytest.raises(TimeoutError, match=EXECUTION_ID) as caught:
        _wait(gateway, timeout=0.2)
    assert PROJECT_ID in str(caught.value)


class SilentStream(httpx.SyncByteStream):
    """SSE body that sends one heartbeat, then stays silent until closed."""

    def __init__(self) -> None:
        """Create the stream, open."""
        self.closed = threading.Event()

    def __iter__(self) -> Iterator[bytes]:
        """Yield a heartbeat, then block like an idle gateway stream.

        Yields:
            The heartbeat bytes.
        """
        yield HEARTBEAT.encode()
        self.closed.wait(10)

    def close(self) -> None:
        """Unblock the pending read."""
        self.closed.set()


def test_timeout_cuts_off_a_silent_stream(mock_client_config) -> None:
    """The deadline ends a read blocked on the next heartbeat, not the heartbeat."""
    stream = SilentStream()
    gateway = FakeGateway(streams=[stream], statuses=["DataIngesting"])

    started = time.monotonic()
    with pytest.raises(TimeoutError, match=EXECUTION_ID):
        _wait(gateway, timeout=0.3)

    assert time.monotonic() - started < 1.5
    assert stream.closed.is_set()


def test_accepts_integer_timeout(mock_client_config) -> None:
    """A whole-number ``timeout`` is accepted."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=["Completed"])

    assert _wait(gateway, timeout=60)["status"] == "Completed"


def test_failed_row_is_returned(mock_client_config) -> None:
    """A failed execution is returned for the caller to inspect, not raised."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=["Failed"])

    assert _wait(gateway)["status"] == "Failed"


def test_missing_row_then_ping(mock_client_config) -> None:
    """No row yet is not terminal; the row's creation wakes the wait."""
    gateway = FakeGateway(
        streams=[DIRTY + DIRTY],
        statuses=[None, "DataIngesting", "Completed"],
    )

    assert _wait(gateway)["status"] == "Completed"
    assert gateway.calls == ["stream", "search", "search", "search"]


def test_ping_for_other_filter_does_not_reread(mock_client_config, sleeps) -> None:
    """A dirty frame naming another filter does not trigger a re-read."""
    other = 'data: {"type":"filters.dirty","filters":["results"]}\n\n'
    gateway = FakeGateway(
        streams=[other, HEARTBEAT],
        statuses=["DataIngesting", "Completed"],
    )

    assert _wait(gateway)["status"] == "Completed"
    assert gateway.calls == ["stream", "search", "stream", "search"]


def test_network_error_reconnects(mock_client_config, monkeypatch) -> None:
    """A dropped connection is reopened after a backoff."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=["Completed"])
    real_handler = gateway.handler
    failed = []

    def flaky(request: httpx.Request) -> httpx.Response:
        """Fail the first stream connect, then delegate.

        Args:
            request: Incoming request.

        Returns:
            The scripted response.
        """
        if request.url.path == STREAM_PATH and not failed:
            failed.append(request)
            raise httpx.ReadError("connection reset", request=request)
        return real_handler(request)

    gateway.handler = flaky
    sleeps: list[float] = []
    monkeypatch.setattr("deeporigin.platform.executions.time.sleep", sleeps.append)

    assert _wait(gateway)["status"] == "Completed"
    assert len(failed) == 1
    assert sleeps == [1.0]


def test_refused_stream_raises(mock_client_config, tmp_path) -> None:
    """A gateway refusal (e.g. 403) raises, saving a curl with the filters."""
    gateway = FakeGateway(streams=[403], statuses=["Completed"])

    with (
        patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path),
        pytest.raises(DeepOriginException),
    ):
        _wait(gateway)
    assert gateway.calls == ["stream"]
    (curl_file,) = tmp_path.iterdir()
    assert f"{STREAM_PATH}?filter=execution%3Dexecution%3A{EXECUTION_ID}" in (
        curl_file.read_text()
    )


def test_requires_project_id(mock_client_config) -> None:
    """Without a project id on the call or the client, the wait refuses."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=["Completed"])

    with pytest.raises(ValueError, match="project_id"):
        _wait(gateway, project_id=None)


def test_iter_dirty_filters_parses_frames() -> None:
    """Comments and ``retry`` tick; multi-line and unknown ``data`` is handled."""
    body = (
        RETRY
        + HEARTBEAT
        + 'data: {"type":"filters.dirty",\ndata: "filters":["a","b"]}\n\n'
        + 'data: {"type":"something.else"}\n\n'
        + "data: not json\n\n"
        + DIRTY
    )
    response = httpx.Response(200, content=body.encode())

    assert list(iter_dirty_filters(response)) == [
        None,
        None,
        {"a", "b"},
        {"execution"},
    ]


@pytest.mark.parametrize("status", [409, 429, 503])
def test_retryable_refusal_reconnects(
    mock_client_config, sleeps, tmp_path, status: int
) -> None:
    """A connection-cap or transient refusal is retried, without a curl file."""
    gateway = FakeGateway(streams=[status, HEARTBEAT], statuses=["Completed"])

    with patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path):
        assert _wait(gateway)["status"] == "Completed"
    assert gateway.calls == ["stream", "stream", "search"]
    assert sleeps == [1.0]
    assert list(tmp_path.iterdir()) == []


def test_every_reconnect_waits_one_second(mock_client_config, sleeps) -> None:
    """Each reopen waits the same fixed pause, with no growing backoff."""
    gateway = FakeGateway(
        streams=[HEARTBEAT],
        statuses=["DataIngesting", "DataIngesting", "DataIngesting", "Completed"],
    )

    assert _wait(gateway)["status"] == "Completed"
    assert sleeps == [1.0, 1.0, 1.0]


def test_reconnect_pause_is_capped_by_deadline(mock_client_config, sleeps) -> None:
    """The pause never runs past the caller's deadline."""
    gateway = FakeGateway(
        streams=[HEARTBEAT],
        statuses=["DataIngesting", "Completed"],
    )

    assert _wait(gateway, timeout=0.5)["status"] == "Completed"
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 0.5
