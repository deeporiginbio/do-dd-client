"""Restrictions are interpreted once, automatically at SDK boundaries."""

import asyncio
from contextlib import ExitStack
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.exceptions import DeepOriginException, PlatformRestrictionError
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.errors import raise_for_platform_restriction
from deeporigin.platform.executions import Executions

MESSAGE = "Insufficient availability for feature ADMET: requested 33, available 20"
ACTION = "Review your plan in Settings → Billing."
PAYLOAD = {
    "errors": [
        {
            "code": "LICENSE.INSUFFICIENT_AVAILABILITY",
            "title": MESSAGE,
            "action_request": ACTION,
        }
    ]
}
DTO = {
    "executionId": "exec-1",
    "status": "InsufficientFunds",
    "statusReason": {
        "code": "FailedQuotation",
        "message": MESSAGE,
        "items": [{"actionRequest": ACTION}],
    },
}

TIER_LIMIT_PAYLOADS = [
    {
        "errors": [
            {
                "code": "MASON.TOOL_EXECUTION.TIER_LIMIT_EXCEEDED",
                "title": message,
                "meta": {
                    "reason": "tier_limit",
                    "itemCode": "DO_TOGO",
                    "limit": limit,
                    "remaining": remaining,
                    "requested": 8,
                    "upgradeTo": "Teams",
                },
            }
        ]
    }
    for limit, remaining, message in [
        (0, 0, "Your plan does not include ADMET. Upgrade to Teams to run it."),
        (20, 5, "This run needs 8 ADMET actions, but only 5 remain this month."),
    ]
]


@pytest.mark.parametrize(
    "code",
    [
        "LICENSE.FEATURE_NOT_LICENSED",
        "LICENSE.INSUFFICIENT_AVAILABILITY",
        "LICENSE.RESERVE.FEATURE_NOT_LICENSED",
        "LICENSE.RESERVE.EXCEEDS_MAX",
        "MASON.TOOL_EXECUTION.BILLING_REJECTED",
        "MASON.TOOL_EXECUTION.TIER_LIMIT_EXCEEDED",
        "CREDITS_TX.PREPARE.INSUFFICIENT",
    ],
)
def test_explicit_codes_preserve_reason_without_inventing_an_action(code):
    with pytest.raises(PlatformRestrictionError) as caught:
        raise_for_platform_restriction({"errors": [{"code": code, "title": MESSAGE}]})
    assert str(caught.value) == MESSAGE
    assert caught.value.action is None
    assert "upgrade" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "limit exceeded",
        {},
        {"errors": [None, "quota", {"code": []}]},
        {"code": "CRMQ.RESOURCE_LEDGER.ORG_QUOTA_EXCEEDED", "message": MESSAGE},
        {
            "status": "Failed",
            "statusReason": {
                "code": "FailedQuotation",
                "message": "Service unavailable",
            },
        },
        {"errors": [{"status": 403, "title": MESSAGE}]},
        {"purchase_approved": True},
        {"purchase_approved": "false"},
    ],
)
def test_unknown_malformed_transient_and_resource_quota_errors_are_not_restrictions(
    payload,
):
    raise_for_platform_restriction(payload, http_status=403)


@pytest.mark.parametrize(
    "payload",
    [
        PAYLOAD,
        DTO,
        {
            "purchase_approved": False,
            "purchase_approval_comment": MESSAGE,
            "action_request": ACTION,
        },
        {
            "is_approved": False,
            "purchase_approval_comment": MESSAGE,
            "action_request": ACTION,
        },
        {
            "status": "Failed",
            "statusReason": {
                "code": "MASON.TOOL_EXECUTION.BILLING_REJECTED",
                "message": MESSAGE,
                "actionRequest": ACTION,
            },
        },
    ],
)
def test_platform_reason_action_and_evidence_survive(payload):
    with pytest.raises(PlatformRestrictionError) as caught:
        raise_for_platform_restriction(payload, http_status=400)
    assert str(caught.value) == f"{MESSAGE}. {ACTION}"
    assert caught.value.user_message == str(caught.value)
    assert caught.value.response_data is payload
    assert caught.value.http_status == 400


def test_multiple_item_reasons_and_actions_are_preserved():
    payload = {
        "status": "InsufficientFunds",
        "statusReason": {
            "items": [
                {
                    "purchaseApprovalComment": "Payment method required",
                    "actionRequest": "Add a card",
                },
                {
                    "purchaseApprovalComment": "Insufficient purchasing power",
                    "actionRequest": "Add funds",
                },
            ]
        },
    }
    with pytest.raises(PlatformRestrictionError) as caught:
        raise_for_platform_restriction(payload)
    assert (
        str(caught.value)
        == "Payment method required; Insufficient purchasing power. Add a card; Add funds"
    )


def test_plain_execution_reason_is_preserved():
    with pytest.raises(PlatformRestrictionError, match="Payment method required"):
        raise_for_platform_restriction(
            {"status": "InsufficientFunds", "statusReason": "Payment method required"}
        )


@pytest.mark.parametrize("status", [400, 403, 429, 503])
@pytest.mark.parametrize("payload", [PAYLOAD, *TIER_LIMIT_PAYLOADS])
def test_http_restriction_stops_before_retry_or_diagnostic_file(status, payload):
    client = object.__new__(DeepOriginClient)
    client.max_retries = 3
    client.retryable_status_codes = {429, 503}
    response = httpx.Response(
        status, json=payload, request=httpx.Request("POST", "https://platform.test")
    )
    request = MagicMock(return_value=response)
    with (
        patch("deeporigin.platform.client.time.sleep") as sleep,
        patch("deeporigin.platform.client._ensure_do_folder") as folder,
    ):
        with pytest.raises(PlatformRestrictionError) as caught:
            client._retry_request(request, "POST", "/tools")
    assert caught.value.body == payload["errors"][0]["title"]
    assert caught.value.response_data == payload
    assert caught.value.http_status == status
    request.assert_called_once()
    sleep.assert_not_called()
    folder.assert_not_called()


@pytest.fixture
def api():
    client = MagicMock(
        project_id="project",
        org_key="org",
        tag=None,
        billing_tag=None,
        _visibility=None,
    )
    client.post_json.return_value = DTO
    client._patch.return_value.json.return_value = DTO
    client.get_json.return_value = DTO
    return Executions(client)


@pytest.mark.parametrize("stage", ["create", "confirm", "wait"])
def test_execution_boundaries_reject_http_success_dto(api, stage):
    with pytest.raises(PlatformRestrictionError) as caught:
        if stage == "create":
            api.create(tool_key="deeporigin.test", tool_version="1", data={})
        elif stage == "confirm":
            api.confirm("exec-1")
        else:
            with patch.object(api, "get", return_value=DTO) as get:
                api.wait("exec-1")
            get.assert_called_once()
    assert caught.value.response_data is DTO
    assert str(caught.value) == f"{MESSAGE}. {ACTION}"


def test_reading_rejected_execution_history_remains_possible(api):
    with patch.object(api._c, "get_json", return_value=DTO):
        assert api.get("exec-1") == DTO


def test_sync_refreshes_rejected_execution_without_raising():
    class Job(Execution):
        tool_key = "deeporigin.test"
        tool_version = "1"

    job = Job()
    job._id = "exec-1"
    job.client = MagicMock()
    job.client.executions.get.return_value = {
        **DTO,
        "tool": {"key": "deeporigin.test", "version": "1"},
    }
    job.sync()
    assert job.status == "InsufficientFunds"


@pytest.mark.parametrize(
    "status", ["Completed", "Running", "Quoted", "Failed", "Cancelled"]
)
def test_non_restricted_execution_response_retains_existing_behavior(api, status):
    dto = {"executionId": "exec-1", "status": status}
    api._c.post_json.return_value = dto
    assert api.create(tool_key="deeporigin.test", tool_version="1", data={}) == dto


def test_quote_remains_available_when_confirmation_rejects_insufficient_funds(
    client, test_server
):
    from deeporigin.drug_discovery import Admet, Ligand
    from tests.conftest import assert_quote_only_execution

    if test_server is None:
        pytest.skip("Requires a controlled billing rejection on the local mock server")

    reason = {
        "code": "FailedQuotation",
        "message": "Insufficient purchasing power",
        "items": [{"actionRequest": "Add funds"}],
    }
    test_server._confirmation_rejections[client.org_key] = reason
    try:
        job = Admet(ligands=[Ligand.from_smiles("CCO")], client=client)
        assert job.run(quote=True) is job
        assert_quote_only_execution(job)
        estimate = job.estimate
        assert estimate > 0
        quoted = client.executions.get(job.id)
        assert quoted["status"] == "Quoted"
        assert quoted["approveAmount"] == -1
        assert job.id not in test_server._execution_start_times

        with pytest.raises(PlatformRestrictionError) as caught:
            job.confirm()

        assert caught.value.body == "Insufficient purchasing power"
        assert caught.value.action == "Add funds"
        assert caught.value.response_data == job.dto
        assert job.status == "InsufficientFunds"
        assert job.estimate == estimate
        assert job.cost is None
        rejected = client.executions.get(job.id)
        assert rejected["status"] == "InsufficientFunds"
        assert rejected["statusReason"] == reason
        assert rejected["startedAt"] is None
        assert rejected["jobOutputs"] is None
        assert job.id not in test_server._execution_start_times
    finally:
        test_server._confirmation_rejections.pop(client.org_key)


@pytest.mark.parametrize("stage", ["result", "execution", "fallback"])
def test_pocket_results_preserve_restrictions_before_fallback(stage):
    from deeporigin.drug_discovery.pocket_finder import PocketFinder
    from deeporigin.drug_discovery.structures.pocket import Pocket

    finder = object.__new__(PocketFinder)
    finder._id = "exec-1"
    finder.client = MagicMock()
    with pytest.raises(PlatformRestrictionError) as original:
        raise_for_platform_restriction(PAYLOAD)
    error = original.value
    finder.client.executions.get.side_effect = error if stage == "execution" else None
    finder.client.executions.get.return_value = {"jobOutputs": {"pockets": []}}
    with (
        patch.object(
            Pocket,
            "from_result",
            side_effect=error if stage == "result" else ValueError("No rows"),
        ),
        patch.object(Pocket, "from_json", side_effect=error) as fallback,
    ):
        with pytest.raises(PlatformRestrictionError) as caught:
            finder.get_results()
    assert caught.value is error
    assert fallback.call_count == (stage == "fallback")
    assert finder.client.executions.get.call_count == (stage != "result")


@pytest.mark.parametrize(
    "method", ["upload_many", "upload_tree", "download_many", "delete_many"]
)
@pytest.mark.parametrize("skip_errors", [False, True])
def test_bulk_file_operations_preserve_platform_rejection(
    method, skip_errors, tmp_path
):
    from deeporigin.platform.files import Files

    local = tmp_path / "input.txt"
    local.write_text("input")
    client = MagicMock(org_key="org")

    def reject(*args, **kwargs):
        raise_for_platform_restriction(PAYLOAD, http_status=403)

    client._put.side_effect = client._delete.side_effect = (
        client.get_json.side_effect
    ) = reject
    files = Files(client)
    kwargs = {"max_workers": 1}
    if method != "upload_many":
        kwargs["skip_errors"] = skip_errors
    with pytest.raises(PlatformRestrictionError) as caught:
        if method == "upload_many":
            files.upload_many(files={str(local): "remote/input.txt"}, **kwargs)
        elif method == "upload_tree":
            files.upload_tree(local, "remote", **kwargs)
        elif method == "download_many":
            files.download_many(
                files={"remote/input.txt": str(tmp_path / "output.txt")}, **kwargs
            )
        else:
            files.delete_many(["remote/input.txt"], **kwargs)
    assert caught.value.response_data is PAYLOAD
    assert caught.value.user_message == f"{MESSAGE}. {ACTION}"


def test_bulk_upload_keeps_ordinary_error_aggregation(tmp_path):
    from deeporigin.platform.files import Files

    files = Files(MagicMock())
    with pytest.raises(RuntimeError, match="Some uploads failed in upload_many"):
        files.upload_many(files={str(tmp_path / "missing"): "remote/missing"})


@pytest.mark.parametrize("stage", ["create", "confirm", "wait"])
@pytest.mark.parametrize("full_dto", [False, True])
def test_execution_retains_rejected_identity_and_state(stage, full_dto):
    class Job(Execution):
        tool_key = "deeporigin.test"
        tool_version = "1"

    client = MagicMock(project_id="project")
    dto = dict(DTO)
    if full_dto:
        dto["tool"] = {"key": Job.tool_key, "version": Job.tool_version}
    error = PlatformRestrictionError(MESSAGE, response_data=dto)
    getattr(client.executions, stage).side_effect = error
    job = Job(client=client)
    if stage != "create":
        job._id = "exec-1"
        job.status = "Quoted"
    job._estimate = 12
    job._cost = 8
    with pytest.raises(PlatformRestrictionError) as caught:
        if stage == "create":
            job._create_execution(data={})
        else:
            getattr(job, stage)()
    assert caught.value is error
    assert job.id == "exec-1"
    assert job.status == "InsufficientFunds"
    assert job.dto is dto
    assert job.estimate is None
    assert job.cost is None


def test_direct_file_stream_preserves_restriction_and_closes_response():
    from deeporigin.platform.files import Files

    client = MagicMock(org_key="org")
    response = httpx.Response(
        403, json=PAYLOAD, request=httpx.Request("GET", "https://platform.test/file")
    )
    client._client.send.return_value = response
    with pytest.raises(PlatformRestrictionError) as caught:
        Files(client).download_stream("file", direct=True)
    assert caught.value.response_data == PAYLOAD
    assert response.is_closed


@pytest.mark.parametrize("ids", [["exec-1"], ["completed", "exec-1", "pending"]])
def test_batch_wait_returns_every_terminal_result_in_input_order(api, ids):
    pending_polls = 0

    def get(exec_id):
        nonlocal pending_polls
        if exec_id == "exec-1":
            return DTO
        if exec_id == "pending":
            pending_polls += 1
            status = "Running" if pending_polls == 1 else "Completed"
        else:
            status = "Completed"
        return {"executionId": exec_id, "status": status}

    with (
        patch.object(api, "get", side_effect=get) as fetch,
        patch("deeporigin.platform.executions.time.sleep"),
    ):
        results = api.wait(ids)
    assert [result["executionId"] for result in results] == ids
    assert results[ids.index("exec-1")] is DTO
    assert all(
        result["status"] in {"Completed", "InsufficientFunds"} for result in results
    )
    assert fetch.call_args_list.count(call("exec-1")) == 1
    if len(ids) > 1:
        assert pending_polls == 2
        assert fetch.call_args_list.count(call("completed")) == 1


@pytest.fixture
def rejected_abfe():
    from deeporigin.drug_discovery.abfe import ABFE

    job = object.__new__(ABFE)
    client = MagicMock()
    Execution.__init__(job, client=client)
    job._id = "exec-1"
    client.executions.get.return_value = {
        **DTO,
        "tool": {"key": ABFE.tool_key, "version": "1"},
    }
    return job


def test_rejected_abfe_results_remain_inspectable(rejected_abfe):
    assert rejected_abfe.get_results() is None
    assert rejected_abfe.status == "InsufficientFunds"
    assert rejected_abfe.dto["statusReason"] == DTO["statusReason"]
    rejected_abfe.client.results.get.assert_not_called()


@pytest.mark.parametrize("blocking", [False, True])
def test_watch_displays_rejected_history_without_background_error(
    rejected_abfe, blocking
):
    job = rejected_abfe

    async def watch():
        task = await job.watch(blocking=blocking)
        if not blocking:
            assert isinstance(task, asyncio.Task)
            await task
            assert task.exception() is None
        else:
            assert task is None

    with (
        patch.object(
            job, "_render_execution_html", return_value="<div>Rejected</div>"
        ) as render,
        patch("deeporigin.drug_discovery.notebook_watch_mixin.display") as display,
        patch(
            "deeporigin.drug_discovery.notebook_watch_mixin.get_bool_env",
            return_value=False,
        ),
    ):
        asyncio.run(watch())
    render.assert_called_once_with(will_auto_update=False)
    assert display.call_count == 2
    assert "Rejected" in display.call_args.args[0].data
    assert job.status == "InsufficientFunds"


@pytest.mark.parametrize(
    "tool",
    [
        None,
        {},
        {"key": "deeporigin.foreign", "version": "1"},
        {"key": "deeporigin.test"},
    ],
)
def test_rejection_does_not_adopt_foreign_or_malformed_tool_metadata(tool):
    class Job(Execution):
        tool_key = "deeporigin.test"
        tool_version = "1"

    client = MagicMock(project_id="project")
    job = Job(client=client)
    previous = {
        "executionId": "original",
        "status": "Quoted",
        "tool": {"key": job.tool_key, "version": "1"},
    }
    job.update_from_dto(previous)
    job._estimate = 12
    error = PlatformRestrictionError(MESSAGE, response_data={**DTO, "tool": tool})
    client.executions.confirm.side_effect = error
    with pytest.raises(PlatformRestrictionError) as caught:
        job.confirm()
    assert caught.value is error
    assert job.dto is previous
    assert job.id == "original"
    assert job.status == "Quoted"
    assert job.estimate == 12


@pytest.mark.parametrize(
    "body", [b"not json", b'{"message": "upstream unavailable"}', b"dropped stream"]
)
def test_direct_stream_retains_http_failure_and_closes_even_if_body_is_unreadable(body):
    from deeporigin.platform.files import Files

    class Stream(httpx.SyncByteStream):
        def __init__(self):
            self.closed = False

        def __iter__(self):
            if body == b"dropped stream":
                raise httpx.ReadError("connection dropped")
            yield body

        def close(self):
            self.closed = True

    stream = Stream()
    response = httpx.Response(
        503, stream=stream, request=httpx.Request("GET", "https://platform.test/file")
    )
    client = MagicMock(org_key="org")
    client._client.send.return_value = response
    with pytest.raises(httpx.HTTPStatusError) as caught:
        Files(client).download_stream("file", direct=True)
    assert caught.value.response is response
    assert response.is_closed and stream.closed


def test_jsonapi_detail_is_preferred_to_generic_title():
    payload = {
        "errors": [
            {
                "code": "LICENSE.FEATURE_NOT_LICENSED",
                "title": "Forbidden",
                "detail": MESSAGE,
            }
        ]
    }
    with pytest.raises(PlatformRestrictionError) as caught:
        raise_for_platform_restriction(payload)
    assert caught.value.body == MESSAGE


@pytest.mark.parametrize(
    "message",
    [
        "Allowance exhausted",
        "Allowance exhausted.",
        "Allowance exhausted!",
        "Allowance exhausted?",
        "Next step:",
    ],
)
def test_restriction_display_separates_reason_and_action(message):
    error = PlatformRestrictionError(message, action=ACTION)
    separator = " " if message[-1] in ".!?:" else ". "
    assert str(error) == message + separator + ACTION
    assert error.body == message and error.action == ACTION


@pytest.mark.parametrize("tool_name", ["admet", "docking", "constrained_docking"])
@pytest.mark.parametrize("restricted", [True, False])
def test_scientific_run_preserves_restriction_or_ordinary_failure(
    tool_name, restricted
):
    from deeporigin.drug_discovery.admet import Admet
    from deeporigin.drug_discovery.constrained_docking import ConstrainedDocking
    from deeporigin.drug_discovery.docking import Docking

    cls, setup, payload = {
        "admet": (
            Admet,
            [
                "_ensure_run_ligand_count",
                "_ensure_properties_for_run",
                "_ensure_platform_inputs",
            ],
            "_make_payload",
        ),
        "docking": (
            Docking,
            ["_ensure_inputs_for_sync_run"],
            "_build_docking_create_payload",
        ),
        "constrained_docking": (
            ConstrainedDocking,
            ["_validate_sync_run_params", "_ensure_platform_inputs"],
            "_build_create_payload",
        ),
    }[tool_name]
    job = object.__new__(cls)
    Execution.__init__(job, client=MagicMock())
    dto = {
        **DTO,
        "tool": {"key": cls.tool_key, "version": "1"},
    }
    if not restricted:
        dto.update(status="Failed", statusReason={"message": "Compute unavailable"})
    with ExitStack() as stack:
        for method in setup:
            stack.enter_context(patch.object(job, method))
        stack.enter_context(patch.object(job, payload, return_value={}))
        stack.enter_context(patch.object(job, "_create_execution", return_value=dto))
        results = stack.enter_context(patch.object(job, "get_results"))
        with pytest.raises(DeepOriginException) as caught:
            job.run()
    assert job.dto is dto
    results.assert_not_called()
    if restricted:
        assert caught.value.response_data is dto
        assert isinstance(caught.value, PlatformRestrictionError)
        assert caught.value.body == MESSAGE and caught.value.action == ACTION
    else:
        assert type(caught.value) is DeepOriginException
        assert caught.value.response_data is None
        assert "Failed" in caught.value.body


@pytest.mark.parametrize("status", [400, 503])
def test_exhausted_http_error_is_parsed_and_classified_once(status, tmp_path):
    from deeporigin.platform import errors

    client = object.__new__(DeepOriginClient)
    client.max_retries = 0
    client._base_url = "https://platform.test"
    client._client = MagicMock(headers={})
    response = httpx.Response(
        status,
        json={"message": "Unrelated failure"},
        request=httpx.Request("POST", "https://platform.test"),
    )
    with (
        patch.object(response, "json", wraps=response.json) as parse,
        patch(
            "deeporigin.platform.client.raise_for_platform_restriction",
            wraps=errors.raise_for_platform_restriction,
        ) as classify,
        patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path),
    ):
        with pytest.raises(DeepOriginException) as caught:
            client._retry_request(lambda: response, "POST", "/tools")
    parse.assert_called_once()
    classify.assert_called_once()
    assert type(caught.value) is DeepOriginException
    assert caught.value.http_status == status
    assert caught.value.response_data == {"message": "Unrelated failure"}


def test_confirm_checks_rejection_after_refresh_when_response_is_empty(rejected_abfe):
    rejected_abfe.status = "Quoted"
    rejected_abfe.client.executions.confirm.return_value = None
    with pytest.raises(PlatformRestrictionError) as caught:
        rejected_abfe.confirm()
    assert caught.value.response_data is rejected_abfe.dto
    assert rejected_abfe.status == "InsufficientFunds"
