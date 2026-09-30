"""Restrictions are interpreted once, automatically at SDK boundaries."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from deeporigin.drug_discovery.execution import Execution
from deeporigin.exceptions import PlatformRestrictionError
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


@pytest.mark.parametrize(
    "code",
    [
        "LICENSE.FEATURE_NOT_LICENSED",
        "LICENSE.INSUFFICIENT_AVAILABILITY",
        "LICENSE.RESERVE.FEATURE_NOT_LICENSED",
        "LICENSE.RESERVE.EXCEEDS_MAX",
        "MASON.TOOL_EXECUTION.BILLING_REJECTED",
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
    assert str(caught.value) == f"{MESSAGE} {ACTION}"
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
        == "Payment method required; Insufficient purchasing power Add a card; Add funds"
    )


def test_plain_execution_reason_is_preserved():
    with pytest.raises(PlatformRestrictionError, match="Payment method required"):
        raise_for_platform_restriction(
            {"status": "InsufficientFunds", "statusReason": "Payment method required"}
        )


@pytest.mark.parametrize("status", [400, 403, 429, 503])
def test_http_restriction_stops_before_retry_or_diagnostic_file(status):
    client = object.__new__(DeepOriginClient)
    client.max_retries = 3
    response = httpx.Response(
        status, json=PAYLOAD, request=httpx.Request("POST", "https://platform.test")
    )
    request = MagicMock(return_value=response)
    with (
        patch("deeporigin.platform.client.time.sleep") as sleep,
        patch("deeporigin.platform.client._ensure_do_folder") as folder,
    ):
        with pytest.raises(PlatformRestrictionError, match=MESSAGE):
            client._retry_request(request, "POST", "/tools")
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
    assert str(caught.value) == f"{MESSAGE} {ACTION}"


def test_reading_rejected_execution_history_remains_possible(api):
    with patch.object(api._c, "get_json", return_value=DTO):
        assert api.get("exec-1") == DTO


def test_polling_execution_instance_raises_and_retains_state():
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
    with pytest.raises(PlatformRestrictionError, match=MESSAGE):
        job.sync()
    assert job.status == "InsufficientFunds"


@pytest.mark.parametrize(
    "status", ["Completed", "Running", "Quoted", "Failed", "Cancelled"]
)
def test_non_restricted_execution_response_retains_existing_behavior(api, status):
    dto = {"executionId": "exec-1", "status": status}
    api._c.post_json.return_value = dto
    assert api.create(tool_key="deeporigin.test", tool_version="1", data={}) == dto


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
    assert caught.value.user_message == f"{MESSAGE} {ACTION}"


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
    with pytest.raises(PlatformRestrictionError) as caught:
        if stage == "create":
            job._create_execution(data={})
        else:
            getattr(job, stage)()
    assert caught.value is error
    assert job.id == "exec-1"
    assert job.status == "InsufficientFunds"
    assert job.dto is dto


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
