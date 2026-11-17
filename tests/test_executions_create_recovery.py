"""Tests for ``Executions.create`` recovering an execution whose response was lost.

QA-1000: a create POST's 201 can be lost between the platform edge and the
client. ``create`` sends a correlation id, and on a read timeout, read error or
protocol error it finds the execution by that id instead of failing. These tests
drive a real :class:`DeepOriginClient` over :class:`httpx.MockTransport`, the
library-native double at the HTTP boundary, and replace only the module clock.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
import uuid
import warnings

import httpx
import pytest

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import executions as executions_module
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.errors import PlatformRestrictionError
from deeporigin.utils.constants import (
    TOOL_EXECUTION_POST_TIMEOUT_SECONDS,
    TOOL_EXECUTION_RECOVERY_POLL_SECONDS,
)

TOOL_KEY = "deeporigin.system-prep"
TOOL_VERSION = "2"
EXECUTION_ID = "exec-1"
CREATE_PATH = f"/tools/test_org/tools/{TOOL_KEY}/{TOOL_VERSION}/executions"
LIST_PATH = "/tools/test_org/tools/executions"
GET_PATH = f"/tools/test_org/tools/executions/{EXECUTION_ID}"
RECOVERY_WARNING = "recovering it by its correlation id"
POLL = TOOL_EXECUTION_RECOVERY_POLL_SECONDS


class FakeToolsService:
    """In-memory stand-in for the tools-service endpoints ``create`` touches."""

    def __init__(
        self,
        *,
        post_error: Exception | None = None,
        list_rows: list[list[dict]] | None = None,
        dtos: list[dict] | None = None,
        list_status: int = 200,
        get_status: int = 200,
    ) -> None:
        """Configure the fake.

        Args:
            post_error: Raised by the create POST; ``None`` answers 201.
            list_rows: Rows returned by successive list calls (last one repeats).
            dtos: DTOs returned by successive GET-by-id calls (last one repeats).
            list_status: HTTP status of the list endpoint.
            get_status: HTTP status of the GET-by-id endpoint.
        """
        self.post_error = post_error
        self.list_rows = list_rows or [[]]
        self.dtos = dtos or []
        self.list_status = list_status
        self.get_status = get_status
        self.posts: list[httpx.Request] = []
        self.list_filters: list[dict] = []
        self.gets = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Answer one request like tools-service would.

        Args:
            request: The outgoing request.

        Returns:
            The canned response for the request's route.
        """
        path = request.url.path
        if request.method == "POST" and path == CREATE_PATH:
            self.posts.append(request)
            if self.post_error is not None:
                raise self.post_error
            return httpx.Response(
                201,
                json={"executionId": EXECUTION_ID, "status": "Completed"},
                request=request,
            )
        if request.method == "GET" and path == LIST_PATH:
            raw_filter = request.url.params.get("filter")
            self.list_filters.append(json.loads(raw_filter) if raw_filter else {})
            if self.list_status != 200:
                return httpx.Response(self.list_status, json={}, request=request)
            index = min(len(self.list_filters) - 1, len(self.list_rows) - 1)
            rows = self.list_rows[index]
            return httpx.Response(
                200, json={"data": rows, "count": len(rows)}, request=request
            )
        if request.method == "GET" and path == GET_PATH:
            self.gets += 1
            if self.get_status != 200:
                return httpx.Response(self.get_status, json={}, request=request)
            dto = self.dtos[min(self.gets - 1, len(self.dtos) - 1)]
            return httpx.Response(200, json=dto, request=request)
        return httpx.Response(404, json={"path": path}, request=request)


class FakeClock:
    """Monotonic clock whose ``sleep`` advances time instead of waiting."""

    def __init__(self) -> None:
        """Start the clock at zero."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        """Return the current fake time.

        Returns:
            Seconds since the fake clock started.
        """
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the fake time.

        Args:
            seconds: Seconds to advance.
        """
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Replace the executions module's clock with a fake one.

    Args:
        monkeypatch: pytest's monkeypatch fixture.

    Returns:
        The fake clock.
    """
    fake = FakeClock()
    monkeypatch.setattr(
        executions_module,
        "time",
        SimpleNamespace(monotonic=fake.monotonic, sleep=fake.sleep),
    )
    return fake


def make_client(fake: FakeToolsService) -> DeepOriginClient:
    """Build a client whose HTTP traffic goes to ``fake``.

    Args:
        fake: The fake tools-service.

    Returns:
        A client scoped to a project, so create can stamp ``projectId``.
    """
    client = DeepOriginClient.from_local(org_key="test_org", max_retries=0)
    client._client = httpx.Client(
        transport=httpx.MockTransport(fake.handler), base_url="http://test"
    )
    client.project_id = "proj-1"
    return client


def create(
    client: DeepOriginClient,
    *,
    timeout: float | None = None,
    approve_amount: float | None = None,
) -> dict:
    """Call ``create`` with a payload that needs no cluster lookup.

    Args:
        client: Client to call.
        timeout: Passed through to ``create``.
        approve_amount: Sent as ``approveAmount`` when set.

    Returns:
        Whatever ``create`` returns.
    """
    data: dict[str, Any] = {
        "inputs": {},
        "outputs": {},
        "metadata": {},
        "clusterId": "c1",
    }
    if approve_amount is not None:
        data["approveAmount"] = approve_amount
    return client.executions.create(  # ty:ignore[unresolved-attribute]
        tool_key=TOOL_KEY,
        tool_version=TOOL_VERSION,
        data=data,
        timeout=timeout,
    )


def row_for(client: DeepOriginClient, fake: FakeToolsService, **extra: Any) -> dict:
    """Return the list row tools-service would hold for the create call.

    Args:
        client: Client whose session the row belongs to.
        fake: Fake that captured the create POST.
        **extra: Fields that override the defaults.

    Returns:
        A list row matching the create's correlation id, session and tool.
    """
    correlation_id = fake.posts[0].headers["x-correlation-id"]
    return {
        "executionId": EXECUTION_ID,
        "correlationId": correlation_id,
        "session": client._session,
        "tool": {"key": TOOL_KEY, "version": TOOL_VERSION},
        "status": "Running",
        **extra,
    }


class LateRows(FakeToolsService):
    """Fake whose list rows are built after the POST, once the id is known."""

    def __init__(
        self, client_holder: dict, rows: list[list[dict]], **kwargs: Any
    ) -> None:
        """Configure the fake.

        Args:
            client_holder: Dict that will hold the client under ``"client"``.
            rows: Row templates per list call; each gets the call's id fields.
            **kwargs: Passed to :class:`FakeToolsService`.
        """
        super().__init__(**kwargs)
        self._holder = client_holder
        self._templates = rows

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Fill row templates with the create's ids, then answer.

        Args:
            request: The outgoing request.

        Returns:
            The canned response for the request's route.
        """
        if request.method == "GET" and request.url.path == LIST_PATH:
            client = self._holder["client"]
            self.list_rows = [
                [row_for(client, self, **template) for template in templates]
                for templates in self._templates
            ]
        return super().handler(request)


def recovering_fake(
    *,
    dtos: list[dict],
    rows: list[list[dict]] | None = None,
    error: Exception | None = None,
    get_status: int = 200,
) -> tuple[DeepOriginClient, LateRows]:
    """Build a client whose create POST fails and whose execution exists.

    Args:
        dtos: DTOs returned by successive GET-by-id calls.
        rows: Row templates per list call (default: one matching row).
        error: The transport error the POST raises (default: read timeout).
        get_status: HTTP status of the GET-by-id endpoint.

    Returns:
        The client and its fake.
    """
    holder: dict = {}
    fake = LateRows(
        holder,
        rows if rows is not None else [[{}]],
        post_error=error or httpx.ReadTimeout("The read operation timed out"),
        dtos=dtos,
        get_status=get_status,
    )
    client = make_client(fake)
    holder["client"] = client
    return client, fake


def recovery_warnings(record: list[warnings.WarningMessage]) -> list[str]:
    """Return the recovery warnings among ``record``.

    Args:
        record: Warnings captured while ``create`` ran.

    Returns:
        Messages of the warnings ``create`` emits when it recovers a run.
    """
    return [str(w.message) for w in record if RECOVERY_WARNING in str(w.message)]


def test_list_sends_correlation_id_filter() -> None:
    """``list(correlation_id=...)`` sends it as ``correlationId`` in the filter."""
    fake = FakeToolsService(list_rows=[[]])
    client = make_client(fake)

    client.executions.list(correlation_id="cid-1")  # ty:ignore[unresolved-attribute]

    assert fake.list_filters == [{"correlationId": "cid-1"}]


def test_create_sends_a_fresh_correlation_id_per_request() -> None:
    """Each create sends its own uuid, per request, not on the shared client."""
    fake = FakeToolsService()
    client = make_client(fake)

    create(client)
    create(client)

    sent = [request.headers["x-correlation-id"] for request in fake.posts]
    assert len(sent) == 2
    assert sent[0] != sent[1]
    assert all(str(uuid.UUID(value)) == value for value in sent)
    assert "x-correlation-id" not in client._client.headers


def test_create_keeps_the_post_timeout() -> None:
    """The POST still waits ``timeout`` (default 600 s) for its response."""
    fake = FakeToolsService()
    client = make_client(fake)

    create(client)
    create(client, timeout=900)

    reads = [request.extensions["timeout"]["read"] for request in fake.posts]
    assert reads == [TOOL_EXECUTION_POST_TIMEOUT_SECONDS, 900]


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("The read operation timed out"),
        httpx.ReadError("Connection reset by peer"),
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
    ],
    ids=["read-timeout", "read-error", "protocol-error"],
)
def test_create_recovers_a_finished_execution(
    clock: FakeClock, error: Exception
) -> None:
    """A lost response returns the finished execution, with one POST and one warning."""
    client, fake = recovering_fake(
        dtos=[{"executionId": EXECUTION_ID, "status": "Completed"}], error=error
    )

    with pytest.warns(UserWarning) as record:
        result = create(client)

    assert result == {"executionId": EXECUTION_ID, "status": "Completed"}
    assert len(fake.posts) == 1
    messages = recovery_warnings(record)
    assert len(messages) == 1
    assert EXECUTION_ID in messages[0]
    assert str(error) not in messages[0]
    sent = fake.posts[0].headers["x-correlation-id"]
    lookup = fake.list_filters[0]
    assert lookup["correlationId"] == sent
    assert lookup["session"] == client._session
    assert lookup["tool"] == {"toolManifest": {"key": TOOL_KEY}}
    assert "$gt" in lookup["createdAt"]


def test_create_polls_a_direct_run_until_it_finishes(clock: FakeClock) -> None:
    """A direct run still ``Running`` is read again until it is terminal."""
    direct = {"method": "direct"}
    client, fake = recovering_fake(
        dtos=[
            {"status": "Running", "estimatorOutput": direct},
            {"status": "Running", "estimatorOutput": direct},
            {"executionId": EXECUTION_ID, "status": "Completed"},
        ]
    )

    with pytest.warns(UserWarning) as record:
        result = create(client)

    assert result["status"] == "Completed"
    assert fake.gets == 3
    assert clock.sleeps == [POLL, POLL]
    assert len(fake.posts) == 1
    assert len(recovery_warnings(record)) == 1


def test_create_waits_out_created_and_quoted(clock: FakeClock) -> None:
    """``Quoted`` and ``Created`` are never handed back; a later state is."""
    client, fake = recovering_fake(
        dtos=[
            {"status": "Quoted"},
            {"status": "Created", "estimatorOutput": {"method": "workflow"}},
            {"status": "Running", "estimatorOutput": {"method": "workflow"}},
        ]
    )

    with pytest.warns(UserWarning):
        result = create(client)

    assert result["status"] == "Running"
    assert fake.gets == 3
    assert len(fake.posts) == 1


def test_create_returns_the_quote_of_a_quote_only_request(clock: FakeClock) -> None:
    """A quote-only create (``approveAmount`` below zero) is answered by ``Quoted``."""
    quoted = {
        "executionId": EXECUTION_ID,
        "status": "Quoted",
        "quotationResult": {"successfulQuotations": [{"priceTotal": 1}]},
    }
    client, fake = recovering_fake(dtos=[quoted])

    with pytest.warns(UserWarning):
        result = create(client, approve_amount=-1)

    assert result == quoted
    assert fake.gets == 1
    assert clock.sleeps == []
    assert len(fake.posts) == 1


@pytest.mark.parametrize(
    ("approve_amount", "quoted"),
    [
        (0, {"status": "Quoted", "quotationResult": {"successfulQuotations": []}}),
        (True, {"status": "Quoted", "quotationResult": {"successfulQuotations": []}}),
        (-1, {"status": "Quoted"}),
    ],
    ids=["zero", "bool", "quote-only-billing-skipped"],
)
def test_create_waits_out_quoted_when_the_request_may_still_run(
    clock: FakeClock, approve_amount: float, quoted: dict
) -> None:
    """``Quoted`` is not the answer when the run may still go ahead.

    ``approveAmount`` 0 can auto-confirm a $0 quote, a bool is no amount, and a
    quote-only ``Quoted`` row without a ``quotationResult`` belongs to a tool
    whose billing is skipped, which tools-service runs anyway.
    """
    client, fake = recovering_fake(
        dtos=[quoted, {"executionId": EXECUTION_ID, "status": "Completed"}]
    )

    with pytest.warns(UserWarning):
        result = create(client, approve_amount=approve_amount)

    assert result["status"] == "Completed"
    assert fake.gets == 2
    assert len(fake.posts) == 1


@pytest.mark.parametrize(
    "dto",
    [
        {"status": "Running", "estimatorOutput": {"method": "workflow"}},
        {"status": "PendingCallback", "estimatorOutput": {"method": "deferred"}},
        {"status": "Failed", "statusReason": "boom"},
        {"status": "Completed"},
    ],
    ids=["workflow-running", "pending-callback", "failed", "completed"],
)
def test_create_returns_settled_rows_at_once(clock: FakeClock, dto: dict) -> None:
    """Rows written only after the POST answered are returned without waiting."""
    client, fake = recovering_fake(dtos=[dto])

    with pytest.warns(UserWarning):
        result = create(client)

    assert result == dto
    assert fake.gets == 1
    assert clock.sleeps == []
    assert len(fake.posts) == 1


@pytest.mark.parametrize(
    "dto",
    [
        {"status": "Running", "estimatorOutput": {"method": "deferred"}},
        {"status": "Running"},
    ],
    ids=["deferred-running", "running-without-method"],
)
def test_create_keeps_reading_running_rows_still_in_the_request(
    clock: FakeClock, dto: dict
) -> None:
    """A deferred run before its 202, or a run with no method, is not settled."""
    client, fake = recovering_fake(dtos=[dto, {"status": "Completed"}])

    with pytest.warns(UserWarning):
        result = create(client)

    assert result == {"status": "Completed"}
    assert fake.gets == 2
    assert len(fake.posts) == 1


def test_create_names_the_execution_when_it_stays_quoted(clock: FakeClock) -> None:
    """Still ``Quoted`` once the budget is spent raises with the id; one POST only."""
    client, fake = recovering_fake(dtos=[{"status": "Quoted"}])

    with pytest.warns(UserWarning), pytest.raises(DeepOriginException) as raised:
        create(client, timeout=20)

    assert EXECUTION_ID in str(raised.value)
    assert "Quoted" in str(raised.value)
    assert isinstance(raised.value.__cause__, httpx.ReadTimeout)
    assert len(fake.posts) == 1
    assert sum(clock.sleeps) == pytest.approx(20)


def test_create_counts_the_recheck_against_the_budget(clock: FakeClock) -> None:
    """The pause before the second lookup is spent from the same budget."""
    client, fake = recovering_fake(dtos=[{"status": "Quoted"}], rows=[[], [{}]])

    with pytest.warns(UserWarning), pytest.raises(DeepOriginException):
        create(client, timeout=8)

    assert clock.sleeps == [POLL, pytest.approx(8 - POLL)]
    assert len(fake.list_filters) == 2
    assert len(fake.posts) == 1


def test_create_names_the_execution_when_reading_it_fails(clock: FakeClock) -> None:
    """Once the execution is known, a failed read names it instead of hiding it."""
    client, fake = recovering_fake(dtos=[{"status": "Completed"}], get_status=400)

    with pytest.warns(UserWarning), pytest.raises(DeepOriginException) as raised:
        create(client)

    assert EXECUTION_ID in str(raised.value)
    assert isinstance(raised.value.__cause__, DeepOriginException)
    assert len(fake.posts) == 1


def test_create_names_the_execution_when_its_read_times_out(clock: FakeClock) -> None:
    """A transport error on the read is handled like an HTTP error."""

    class TimingOutReads(LateRows):
        """Fake whose GET-by-id times out."""

        def handler(self, request: httpx.Request) -> httpx.Response:
            """Time out on the GET by id, answer everything else.

            Args:
                request: The outgoing request.

            Returns:
                The canned response for any other route.
            """
            if request.method == "GET" and request.url.path == GET_PATH:
                raise httpx.ReadTimeout("read timed out")
            return super().handler(request)

    holder: dict = {}
    fake = TimingOutReads(
        holder,
        [[{}]],
        post_error=httpx.ReadTimeout("The read operation timed out"),
        dtos=[{"status": "Completed"}],
    )
    client = make_client(fake)
    holder["client"] = client

    with pytest.warns(UserWarning), pytest.raises(DeepOriginException) as raised:
        create(client)

    assert EXECUTION_ID in str(raised.value)
    assert isinstance(raised.value.__cause__, httpx.TransportError)
    assert len(fake.posts) == 1


def test_create_caps_the_recheck_by_a_short_budget(clock: FakeClock) -> None:
    """A budget under the poll interval is not overrun by the re-check pause."""
    error = httpx.ReadTimeout("The read operation timed out")
    fake = FakeToolsService(post_error=error, list_rows=[[]])
    client = make_client(fake)

    with pytest.raises(httpx.ReadTimeout):
        create(client, timeout=2)

    assert clock.sleeps == [pytest.approx(2)]


def test_create_reraises_the_original_error_when_nothing_was_created(
    clock: FakeClock,
) -> None:
    """No row after one re-check: the original read timeout comes back, unwarned."""
    error = httpx.ReadTimeout("The read operation timed out")
    fake = FakeToolsService(post_error=error, list_rows=[[]])
    client = make_client(fake)

    with (
        warnings.catch_warnings(record=True) as record,
        pytest.raises(httpx.ReadTimeout) as raised,
    ):
        warnings.simplefilter("always")
        create(client)

    assert raised.value is error
    sent = fake.posts[0].headers["x-correlation-id"]
    assert any(sent in note for note in getattr(error, "__notes__", []))
    assert recovery_warnings(record) == []
    assert len(fake.list_filters) == 2
    assert clock.sleeps == [POLL]
    assert fake.gets == 0
    assert len(fake.posts) == 1


def test_create_reraises_at_once_when_two_rows_match(clock: FakeClock) -> None:
    """Two matching rows are ambiguous: re-raise without a second lookup."""
    client, fake = recovering_fake(
        dtos=[{"status": "Completed"}], rows=[[{}, {"executionId": "exec-2"}]]
    )

    with (
        warnings.catch_warnings(record=True) as record,
        pytest.raises(httpx.ReadTimeout),
    ):
        warnings.simplefilter("always")
        create(client)

    assert recovery_warnings(record) == []
    assert len(fake.list_filters) == 1
    assert clock.sleeps == []
    assert fake.gets == 0
    assert len(fake.posts) == 1


@pytest.mark.parametrize(
    "templates",
    [
        [{"correlationId": None}],
        [{"session": "someone-else"}],
        [{"tool": {"key": "deeporigin.docking"}}],
    ],
    ids=["null-correlation-id", "other-session", "other-tool"],
)
def test_create_never_recovers_a_foreign_row(
    clock: FakeClock, templates: list[dict]
) -> None:
    """Rows that do not carry this call's identity are never recovered."""
    client, fake = recovering_fake(
        dtos=[{"status": "Completed"}], rows=[templates, templates]
    )

    with (
        warnings.catch_warnings(record=True) as record,
        pytest.raises(httpx.ReadTimeout),
    ):
        warnings.simplefilter("always")
        create(client)

    assert recovery_warnings(record) == []
    assert fake.gets == 0
    assert len(fake.posts) == 1


def test_create_reraises_the_original_error_when_the_lookup_fails(
    clock: FakeClock,
) -> None:
    """A failing lookup surfaces the original error, chained from the lookup's."""
    error = httpx.ReadTimeout("The read operation timed out")
    fake = FakeToolsService(post_error=error, list_status=400)
    client = make_client(fake)

    with pytest.raises(httpx.ReadTimeout) as raised:
        create(client)

    assert raised.value is error
    assert isinstance(raised.value.__cause__, DeepOriginException)
    assert len(fake.posts) == 1


def test_create_raises_the_restriction_of_a_recovered_execution(
    clock: FakeClock,
) -> None:
    """A recovered ``InsufficientFunds`` row raises like the 201 would."""
    client, fake = recovering_fake(
        dtos=[{"executionId": EXECUTION_ID, "status": "InsufficientFunds"}]
    )

    with pytest.warns(UserWarning), pytest.raises(PlatformRestrictionError):
        create(client)

    assert len(fake.posts) == 1


def test_create_does_not_recover_a_connect_error(clock: FakeClock) -> None:
    """A connect error means nothing was sent, so there is nothing to look up."""
    fake = FakeToolsService(post_error=httpx.ConnectError("Connection refused"))
    client = make_client(fake)

    with pytest.raises(httpx.ConnectError):
        create(client)

    assert fake.list_filters == []
    assert len(fake.posts) == 1
