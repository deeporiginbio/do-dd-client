"""Structured evidence survives SDK transport and execution failures."""

from unittest.mock import patch

import httpx
import pytest

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient

PAYLOAD = {
    "errors": [
        {"code": "LICENSE.INSUFFICIENT_AVAILABILITY", "title": "Allowance exhausted"}
    ]
}


def test_optional_fields_do_not_change_legacy_exception_display():
    old = DeepOriginException("Title", "Body", "Fix", "warning")
    new = DeepOriginException(
        "Title", "Body", "Fix", "warning", http_status=400, response_data=PAYLOAD
    )
    assert str(old) == str(new)
    assert old.http_status is None and old.response_data is None
    assert new.args == old.args


@pytest.mark.parametrize("payload", [PAYLOAD, ["unusual", "payload"], None])
def test_http_error_preserves_payload_without_adding_it_to_display(tmp_path, payload):
    response = httpx.Response(
        400, json=payload, request=httpx.Request("POST", "https://platform.test/tools")
    )
    client = object.__new__(DeepOriginClient)
    client._base_url = "https://platform.test"
    client._client = httpx.Client()
    error = httpx.HTTPStatusError(
        "rejected", request=response.request, response=response
    )
    with patch("deeporigin.platform.client._ensure_do_folder", return_value=tmp_path):
        with pytest.raises(DeepOriginException) as caught:
            client._handle_request_error("POST", "/tools", error)
    assert caught.value.http_status == 400
    assert caught.value.response_data == payload
    client._client.close()


def test_unknown_execution_failure_preserves_details():
    dto = {
        "status": "Failed",
        "statusReason": {"message": "Compute unavailable"},
        "executionId": "exec-1",
    }
    exc = DeepOriginException.from_execution(
        dto, title="Execution failed", message="Compute unavailable"
    )
    assert type(exc) is DeepOriginException
    assert exc.response_data == dto
    assert exc.user_message == "Compute unavailable"
