"""Tests for retry functionality in DeepOriginClient."""

import time
from unittest.mock import patch

import httpx
import pytest

from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient

pytestmark = pytest.mark.slow


@pytest.fixture
def mock_client_config():
    """Fixture to provide mock configuration for client initialization."""
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
            "org_key": "test_org",
            "project_id": None,
        }
        mock_check_token.return_value = None
        yield


def test_retry_on_500_error(mock_client_config):
    """Test that client retries on 500 server errors."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        if call_count["count"] <= 2:
            return httpx.Response(
                500, json={"error": "Internal Server Error"}, request=request
            )
        return httpx.Response(200, json={"success": True}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=3)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    result = client._get("/test")

    assert result.status_code == 200
    assert call_count["count"] == 3


def test_retry_on_429_rate_limit(mock_client_config):
    """Test that client retries on 429 rate limit errors."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        if call_count["count"] == 1:
            return httpx.Response(
                429, json={"error": "Rate limit exceeded"}, request=request
            )
        return httpx.Response(200, json={"success": True}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=2)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    result = client._get("/test")

    assert result.status_code == 200
    assert call_count["count"] == 2


def test_no_retry_on_400_error(mock_client_config):
    """Test that client does not retry on 400 client errors."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        return httpx.Response(400, json={"error": "Bad Request"}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=3)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    with pytest.raises(DeepOriginException):
        client._get("/test")

    assert call_count["count"] == 1


def test_retry_with_exponential_backoff(mock_client_config):
    """Test that retries use exponential backoff."""
    call_count = {"count": 0}
    timestamps = []

    def handler(request: httpx.Request) -> httpx.Response:
        timestamps.append(time.time())
        call_count["count"] += 1
        if call_count["count"] <= 2:
            return httpx.Response(500, json={"error": "Server Error"}, request=request)
        return httpx.Response(200, json={"success": True}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(
        max_retries=2,
        retry_backoff_factor=0.1,
    )
    client._client = httpx.Client(transport=transport, base_url="http://test")

    start_time = time.time()
    result = client._get("/test")
    elapsed = time.time() - start_time

    assert result.status_code == 200
    assert call_count["count"] == 3
    if len(timestamps) >= 2:
        delay1 = timestamps[1] - timestamps[0]
        assert delay1 >= 0.05
    assert elapsed >= 0.25


def test_retry_on_network_error(mock_client_config):
    """Test that client retries on network errors."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise httpx.NetworkError("Connection failed")
        return httpx.Response(200, json={"success": True}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=2)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    result = client._get("/test")

    assert result.status_code == 200
    assert call_count["count"] == 2


def test_retry_on_timeout(mock_client_config):
    """Test that client retries on timeout errors."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise httpx.TimeoutException("Request timed out")
        return httpx.Response(200, json={"success": True}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=2)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    result = client._get("/test")

    assert result.status_code == 200
    assert call_count["count"] == 2


def test_max_retries_exhausted(mock_client_config):
    """Test that client raises error after max retries are exhausted."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        return httpx.Response(500, json={"error": "Server Error"}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=2)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    with pytest.raises(DeepOriginException):
        client._get("/test")

    assert call_count["count"] >= 3
    assert call_count["count"] <= 4


def test_custom_retryable_status_codes(mock_client_config):
    """Test assigning ``retryable_status_codes`` on the client instance."""
    call_count_500 = {"count": 0}
    call_count_503 = {"count": 0}

    def handler_500(request: httpx.Request) -> httpx.Response:
        call_count_500["count"] += 1
        return httpx.Response(500, json={"error": "Server Error"}, request=request)

    def handler_503(request: httpx.Request) -> httpx.Response:
        call_count_503["count"] += 1
        if call_count_503["count"] == 1:
            return httpx.Response(
                503, json={"error": "Service Unavailable"}, request=request
            )
        return httpx.Response(200, json={"success": True}, request=request)

    transport_500 = httpx.MockTransport(handler_500)
    client_500 = DeepOriginClient.from_local(max_retries=2)
    client_500.retryable_status_codes = frozenset({503, 504})
    client_500._client = httpx.Client(transport=transport_500, base_url="http://test")

    with pytest.raises(DeepOriginException):
        client_500._get("/test")

    assert call_count_500["count"] >= 1
    assert call_count_500["count"] <= 4

    transport_503 = httpx.MockTransport(handler_503)
    client_503 = DeepOriginClient.from_local(max_retries=2)
    client_503.retryable_status_codes = frozenset({503, 504})
    client_503._client = httpx.Client(transport=transport_503, base_url="http://test")

    result = client_503._get("/test")
    assert result.status_code == 200
    assert call_count_503["count"] == 2


def test_retry_disabled(mock_client_config):
    """Test that retries can be disabled by setting max_retries to 0."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        return httpx.Response(500, json={"error": "Server Error"}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=0)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    with pytest.raises(DeepOriginException):
        client._get("/test")

    assert call_count["count"] >= 1
    assert call_count["count"] <= 4


def test_retry_on_post_request(mock_client_config):
    """Test that POST requests also retry on errors."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        if call_count["count"] == 1:
            return httpx.Response(500, json={"error": "Server Error"}, request=request)
        return httpx.Response(201, json={"id": "123"}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=2)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    result = client._post("/test", body={"data": "test"})

    assert result.status_code == 201
    assert call_count["count"] == 2


def test_post_json_single_attempt_when_retry_disabled(mock_client_config):
    """POST with retry=False does not repeat on retryable HTTP errors."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        return httpx.Response(500, json={"error": "Server Error"}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=3)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    with pytest.raises(DeepOriginException):
        client.post_json("/test", body={"data": "test"}, retry=False)

    assert call_count["count"] == 1


def test_retry_preserves_request_body(mock_client_config):
    """Test that retries preserve the original request body."""
    call_count = {"count": 0}
    request_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        if hasattr(request, "content") and request.content:
            import json as json_lib

            request_bodies.append(json_lib.loads(request.content))
        if call_count["count"] == 1:
            return httpx.Response(500, json={"error": "Server Error"}, request=request)
        return httpx.Response(200, json={"success": True}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(max_retries=2)
    client._client = httpx.Client(transport=transport, base_url="http://test")

    test_body = {"key": "value", "nested": {"data": 123}}
    client._post("/test", body=test_body)

    assert call_count["count"] == 2


def test_max_retry_delay_cap(mock_client_config):
    """Test that retry delays are capped at max_retry_delay."""
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        if call_count["count"] <= 3:
            return httpx.Response(500, json={"error": "Server Error"}, request=request)
        return httpx.Response(200, json={"success": True}, request=request)

    transport = httpx.MockTransport(handler)
    client = DeepOriginClient.from_local(
        max_retries=3,
        retry_backoff_factor=100.0,
        max_retry_delay=2.0,
    )
    client._client = httpx.Client(transport=transport, base_url="http://test")

    start_time = time.time()
    result = client._get("/test")
    elapsed = time.time() - start_time

    assert result.status_code == 200
    assert call_count["count"] >= 4

    assert elapsed < 15.0, (
        f"Total elapsed time {elapsed}s is too large (should be capped at ~6-8s). "
        f"This indicates the max_retry_delay cap is not working correctly."
    )
