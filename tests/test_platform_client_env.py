"""Tests for environment variable fallbacks in platform DeepOriginClient."""

import os
import time
from typing import Generator
from unittest.mock import patch

import jwt
import pytest

from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import ENV_VARIABLES


@pytest.fixture(autouse=True)
def clear_env_and_cache() -> Generator[None, None, None]:
    """Clear relevant env vars and client cache for each test."""
    keys = list(ENV_VARIABLES.values())
    old = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    DeepOriginClient.close_all()
    try:
        yield
    finally:
        DeepOriginClient.close_all()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---- No-arg constructor priority chain ----


def test_do_env_local_defaults_to_mock_base_url() -> None:
    """``DO_ENV=local`` with no auth vars routes DeepOriginClient() through from_disk."""
    os.environ["DO_ENV"] = "local"
    client = DeepOriginClient()

    assert client.env == "local"
    assert client.base_url.rstrip("/") == "http://127.0.0.1:4931"


def test_do_base_url_env_sets_base_url_and_env() -> None:
    """All three required env vars set → DeepOriginClient() uses from_env_variables."""
    os.environ["DO_BASE_URL"] = "https://api.dev.deeporigin.io"
    os.environ["DO_AUTH_TOKEN"] = "test-token"
    os.environ["DO_ORG_KEY"] = "test-org"

    client = DeepOriginClient()

    assert client.base_url.rstrip("/") == "https://api.dev.deeporigin.io"
    assert client.env == "dev"


def test_do_base_url_takes_priority_over_do_env() -> None:
    """DO_BASE_URL wins when both DO_BASE_URL and DO_ENV are set (via from_env_variables)."""
    os.environ["DO_BASE_URL"] = "https://api.staging.deeporigin.io"
    os.environ["DO_ENV"] = "prod"
    os.environ["DO_AUTH_TOKEN"] = "test-token"
    os.environ["DO_ORG_KEY"] = "test-org"

    client = DeepOriginClient()

    assert client.env == "staging"
    assert "staging" in client.base_url


# ---- from_env_variables ----


def test_from_env_variables_with_base_url() -> None:
    """Test from_env_variables with DO_BASE_URL set."""
    os.environ["DO_AUTH_TOKEN"] = "tok-123"
    os.environ["DO_ORG_KEY"] = "my-org"
    os.environ["DO_BASE_URL"] = "https://api.dev.deeporigin.io"

    client = DeepOriginClient.from_env_variables()

    assert client.token == "tok-123"
    assert client.org_key == "my-org"
    assert client.env == "dev"
    assert client.base_url.rstrip("/") == "https://api.dev.deeporigin.io"


def test_from_env_variables_infers_staging() -> None:
    """Test from_env_variables infers staging env from URL."""
    os.environ["DO_AUTH_TOKEN"] = "tok-456"
    os.environ["DO_ORG_KEY"] = "other-org"
    os.environ["DO_BASE_URL"] = "https://api.staging.deeporigin.io"

    client = DeepOriginClient.from_env_variables()

    assert client.token == "tok-456"
    assert client.org_key == "other-org"
    assert client.env == "staging"
    assert "staging" in client.base_url


def test_from_env_variables_missing_token_raises() -> None:
    """Test that missing DO_AUTH_TOKEN raises ValueError."""
    os.environ["DO_ORG_KEY"] = "my-org"
    os.environ["DO_ENV"] = "prod"

    with pytest.raises(ValueError, match="DO_AUTH_TOKEN"):
        DeepOriginClient.from_env_variables()


def test_from_env_variables_missing_org_key_raises() -> None:
    """Test that missing DO_ORG_KEY raises ValueError."""
    os.environ["DO_AUTH_TOKEN"] = "tok"
    os.environ["DO_ENV"] = "prod"

    with pytest.raises(ValueError, match="DO_ORG_KEY"):
        DeepOriginClient.from_env_variables()


def test_from_env_variables_infers_base_url_from_token_when_missing() -> None:
    """When DO_BASE_URL is unset, infer API URL from the JWT issuer."""
    token = jwt.encode(
        {
            "iss": "https://login.dev.deeporigin.io/realms/deeporigin",
            "exp": int(time.time()) + 3600,
        },
        "secret",
        algorithm="HS256",
    )
    os.environ["DO_AUTH_TOKEN"] = token
    os.environ["DO_ORG_KEY"] = "org"

    client = DeepOriginClient.from_env_variables()

    assert client.base_url.rstrip("/") == "https://api.dev.deeporigin.io"
    assert client.env == "dev"


def test_explicit_constructor_infers_base_url_from_token() -> None:
    """``DeepOriginClient(token=..., org_key=...)`` may omit ``base_url``."""
    token = jwt.encode(
        {
            "iss": "https://login.staging.deeporigin.io/realms/deeporigin",
            "exp": int(time.time()) + 3600,
        },
        "secret",
        algorithm="HS256",
    )

    client = DeepOriginClient(token=token, org_key="my-org")

    assert client.base_url.rstrip("/") == "https://api.staging.deeporigin.io"
    assert client.env == "staging"
    assert client.org_key == "my-org"


# ---- from_disk ----


def test_from_disk_reads_token_and_org_key_from_files() -> None:
    """Test that from_disk reads token from api_tokens.json and org_key from config."""
    with (
        patch("deeporigin.platform.client.get_token") as mock_get_token,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_token.return_value = "token_from_file"
        mock_get_value.return_value = {
            "env": "prod",
            "org_key": "org_from_config",
            "project_id": None,
        }

        client = DeepOriginClient.from_disk(env="prod")

        assert client.token == "token_from_file"
        assert client.org_key == "org_from_config"
        assert client.env == "prod"
        mock_get_token.assert_called_once_with(env="prod")
        mock_get_value.assert_called_once()


def test_from_disk_with_explicit_env() -> None:
    """Test that from_disk uses explicit env parameter when provided."""
    with (
        patch("deeporigin.platform.client.get_token") as mock_get_token,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_token.return_value = "token_staging"
        mock_get_value.return_value = {
            "env": "prod",
            "org_key": "org_from_config",
            "project_id": None,
        }

        client = DeepOriginClient.from_disk(env="staging")

        assert client.token == "token_staging"
        assert client.org_key == "org_from_config"
        assert client.env == "staging"
        mock_get_token.assert_called_once_with(env="staging")


def test_from_disk_reads_token_from_file() -> None:
    """Test that from_disk reads token from file."""
    with (
        patch("deeporigin.platform.client.get_token") as mock_get_token,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_token.return_value = "token_from_file"
        mock_get_value.return_value = {
            "env": "prod",
            "org_key": "org_from_config",
            "project_id": None,
        }

        client = DeepOriginClient.from_disk(env="prod")

        assert client.token == "token_from_file"
