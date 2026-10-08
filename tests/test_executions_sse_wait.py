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
RESULTS_PATH = f"/data-platform/{ORG_KEY}/result-explorer/search"
INCLUDE_HIDDEN_REJECTED = {
    "message": "Unknown keys in payload",
    "errors": [{"field": "include_hidden", "reason": "unknown_field"}],
}

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
    """Record sleeps instead of sleeping, on a fake clock and without jitter.

    Each sleep advances ``time.monotonic`` by its duration and nothing else
    does, and jitter picks the top of its range, so recorded pauses are exact.

    Returns:
        The requested sleep durations, in order.
    """
    recorded: list[float] = []
    clock = [1000.0]

    def sleep(seconds: float) -> None:
        """Record a sleep and advance the fake clock.

        Args:
            seconds: Requested duration.
        """
        recorded.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("deeporigin.platform.executions.time.sleep", sleep)
    monkeypatch.setattr(
        "deeporigin.platform.executions.time.monotonic", lambda: clock[0]
    )
    monkeypatch.setattr(
        "deeporigin.platform.executions.random.uniform", lambda low, high: high
    )
    return recorded


@pytest.fixture
def sweep_every_tick(monkeypatch) -> None:
    """Make every heartbeat and every reconnect pause re-read the row."""
    monkeypatch.setattr(
        "deeporigin.platform.executions.DATA_PLATFORM_INGESTION_SWEEP_SECONDS", 0.0
    )


@pytest.fixture
def no_poll(monkeypatch) -> None:
    """Stop reconnect pauses from polling the row, to observe backoff alone."""
    monkeypatch.setattr(
        "deeporigin.platform.executions.DATA_PLATFORM_INGESTION_POLL_SECONDS", 1e6
    )


class FakeGateway:
    """Scripted gateway: one SSE body per connect, one status per search.

    The last stream body and the last status repeat once their scripts run out.
    """

    def __init__(
        self,
        *,
        streams: list[str | int | httpx.SyncByteStream],
        statuses: list[str | None],
        rejects_include_hidden: bool = False,
        results: list[dict] | None = None,
    ) -> None:
        """Store the scripts.

        Args:
            streams: SSE body per connect, an HTTP status code to refuse it,
                or a byte stream to serve as-is.
            statuses: Row status per search, or ``None`` for no row yet.
            rejects_include_hidden: Answer a search sending ``include_hidden``
                with the 400 of a backend that does not know the flag.
            results: Result-explorer rows for the execution.
        """
        self.streams = streams
        self.statuses = statuses
        self.rejects_include_hidden = rejects_include_hidden
        self.results = results or []
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
            body = json.loads(request.content)
            if self.rejects_include_hidden and "include_hidden" in body:
                self.calls.append("rejected")
                return httpx.Response(400, json=INCLUDE_HIDDEN_REJECTED)
            n = sum(c == "search" for c in self.calls)
            self.calls.append("search")
            self.search_bodies.append(body)
            status = self.statuses[min(n, len(self.statuses) - 1)]
            rows = [] if status is None else [{"id": "dp-1", "status": status}]
            return httpx.Response(200, json={"data": rows, "meta": {}})
        if request.url.path == RESULTS_PATH:
            self.calls.append("results")
            return httpx.Response(200, json={"data": self.results, "meta": {}})
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
    assert gateway.search_bodies[0]["include_hidden"] is True


def test_stream_open_timeouts_are_capped_by_deadline(mock_client_config) -> None:
    """Connect, write and pool timeouts cannot outlast a short wait."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=["Completed"])

    _wait(gateway, timeout=2.0)

    timeouts = gateway.stream_requests[0].extensions["timeout"]
    assert all(0 < value <= 2.0 for value in timeouts.values())


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


def test_network_error_reconnects(mock_client_config, sleeps) -> None:
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


def test_flapping_stream_backoff_doubles_to_cap(
    mock_client_config, sleeps, no_poll
) -> None:
    """Streams that close before holding double the pause, up to the cap."""
    gateway = FakeGateway(
        streams=[HEARTBEAT],
        statuses=["DataIngesting"] * 7 + ["Completed"],
    )

    assert _wait(gateway, timeout=600)["status"] == "Completed"
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_stable_stream_resets_backoff(mock_client_config, sleeps, monkeypatch) -> None:
    """A stream that held long enough reopens after the first pause again."""
    monkeypatch.setattr(
        "deeporigin.platform.executions.SSE_STABLE_CONNECTION_SECONDS", 0.0
    )
    gateway = FakeGateway(
        streams=[HEARTBEAT],
        statuses=["DataIngesting", "DataIngesting", "DataIngesting", "Completed"],
    )

    assert _wait(gateway)["status"] == "Completed"
    assert sleeps == [1.0, 1.0, 1.0]


def test_backoff_is_jittered(mock_client_config, monkeypatch) -> None:
    """The pause is drawn between half and all of the backoff."""
    bounds: list[tuple[float, float]] = []
    sleeps: list[float] = []
    monkeypatch.setattr("deeporigin.platform.executions.time.sleep", sleeps.append)

    def low(a: float, b: float) -> float:
        """Record the jitter range and pick its bottom.

        Args:
            a: Lower bound.
            b: Upper bound.

        Returns:
            The lower bound.
        """
        bounds.append((a, b))
        return a

    monkeypatch.setattr("deeporigin.platform.executions.random.uniform", low)
    gateway = FakeGateway(
        streams=[HEARTBEAT], statuses=["DataIngesting", "DataIngesting", "Completed"]
    )

    assert _wait(gateway)["status"] == "Completed"
    assert bounds == [(0.5, 1.0), (1.0, 2.0)]
    assert sleeps == [0.5, 1.0]


def test_sweep_rereads_on_heartbeat(mock_client_config, sweep_every_tick) -> None:
    """A due sweep re-reads the row on a heartbeat, with no dirty frame."""
    gateway = FakeGateway(
        streams=[HEARTBEAT + HEARTBEAT],
        statuses=["DataIngesting", "Completed"],
    )

    assert _wait(gateway)["status"] == "Completed"
    assert gateway.calls == ["stream", "search", "search"]


def test_refused_stream_polls_row(mock_client_config, sleeps, tmp_path) -> None:
    """A stream that never opens still finds the row by polling."""
    gateway = FakeGateway(streams=[503], statuses=["DataIngesting", "Completed"])

    with patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path):
        assert _wait(gateway)["status"] == "Completed"
    assert gateway.calls == ["stream", "stream", "search", "stream", "search"]
    assert sleeps == [1.0, 1.0, 1.0, 1.0]


def test_backoff_pause_polls_every_interval(
    mock_client_config, sleeps, monkeypatch, tmp_path
) -> None:
    """A long reconnect pause polls the row every poll interval."""
    monkeypatch.setattr(
        "deeporigin.platform.executions.SSE_RECONNECT_BACKOFF_SECONDS", 30.0
    )
    gateway = FakeGateway(
        streams=[503], statuses=["DataIngesting", "DataIngesting", "Completed"]
    )

    with patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path):
        assert _wait(gateway, timeout=60)["status"] == "Completed"
    assert gateway.calls == ["stream", "search", "search", "search"]
    assert sleeps == [2.0, 2.0, 2.0]


def test_reconnect_pause_is_capped_by_deadline(mock_client_config, sleeps) -> None:
    """The pause never runs past the caller's deadline."""
    gateway = FakeGateway(
        streams=[HEARTBEAT],
        statuses=["DataIngesting", "Completed"],
    )

    with pytest.raises(TimeoutError, match=EXECUTION_ID):
        _wait(gateway, timeout=0.5)
    assert sleeps == [0.5]


def test_unsupported_include_hidden_falls_back(mock_client_config, tmp_path) -> None:
    """A backend without ``include_hidden`` is searched without it."""
    gateway = FakeGateway(
        streams=[HEARTBEAT], statuses=["Completed"], rejects_include_hidden=True
    )

    with patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path):
        assert _wait(gateway)["status"] == "Completed"
    assert gateway.calls == ["stream", "rejected", "search"]
    assert "include_hidden" not in gateway.search_bodies[0]


def test_unsupported_include_hidden_is_remembered(mock_client_config, tmp_path) -> None:
    """Later waits on the same client skip the rejected flag."""
    gateway = FakeGateway(
        streams=[HEARTBEAT], statuses=["Completed"], rejects_include_hidden=True
    )
    client = gateway.client()

    with patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path):
        for _ in range(2):
            client.executions.wait_for_ingestion(
                EXECUTION_ID, project_id=PROJECT_ID, timeout=5.0
            )
    assert gateway.calls.count("rejected") == 1


def test_hidden_run_without_flag_done_on_results(mock_client_config, tmp_path) -> None:
    """With no visible row, result-explorer rows mean ingestion is done."""
    gateway = FakeGateway(
        streams=[HEARTBEAT],
        statuses=[None],
        rejects_include_hidden=True,
        results=[{"id": "r-1"}],
    )

    with patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path):
        assert _wait(gateway) == {}
    assert gateway.calls == ["stream", "rejected", "search", "results"]


def test_hidden_run_without_flag_gives_up_on_row(
    mock_client_config, tmp_path, monkeypatch
) -> None:
    """With no visible row and no results, the wait ends after the no-row timeout."""
    monkeypatch.setattr(
        "deeporigin.platform.executions.DATA_PLATFORM_NO_ROW_TIMEOUT_SECONDS", 0.0
    )
    gateway = FakeGateway(
        streams=[HEARTBEAT], statuses=[None], rejects_include_hidden=True
    )

    with patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path):
        assert _wait(gateway) == {}


def test_hidden_run_with_flag_keeps_waiting_without_row(mock_client_config) -> None:
    """A backend with the flag never short-cuts a missing row."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=[None], results=[{"id": "r-1"}])

    with pytest.raises(TimeoutError):
        _wait(gateway, timeout=0.2)
    assert "results" not in gateway.calls


def test_other_search_error_raises(mock_client_config, tmp_path) -> None:
    """A search failure not about ``include_hidden`` is not swallowed."""
    gateway = FakeGateway(streams=[HEARTBEAT], statuses=["Completed"])
    real_handler = gateway.handler

    def broken(request: httpx.Request) -> httpx.Response:
        """Fail every search with an unrelated 400.

        Args:
            request: Incoming request.

        Returns:
            The scripted response.
        """
        if request.url.path == SEARCH_PATH:
            return httpx.Response(400, json={"message": "bad filter"})
        return real_handler(request)

    gateway.handler = broken

    with (
        patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path),
        pytest.raises(DeepOriginException),
    ):
        _wait(gateway)
