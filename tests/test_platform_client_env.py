"""Tests for environment variable fallbacks in platform DeepOriginClient."""

import os
from typing import Generator
from unittest.mock import patch

import pytest

from deeporigin.platform.client import (
    DeepOriginClient,
    _infer_env_from_base_url,
)
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


# ---- _infer_env_from_base_url ----


def test_infer_env_dev() -> None:
    """Test that a dev URL is identified as dev."""
    assert _infer_env_from_base_url("https://api.dev.deeporigin.io") == "dev"


def test_infer_env_staging() -> None:
    """Test that a staging URL is identified as staging."""
    assert _infer_env_from_base_url("https://api.staging.deeporigin.io") == "staging"


def test_infer_env_prod() -> None:
    """Test that a prod URL is identified as prod."""
    assert _infer_env_from_base_url("https://api.deeporigin.io") == "prod"


def test_infer_env_local() -> None:
    """Test that localhost URLs are identified as local."""
    assert _infer_env_from_base_url("http://127.0.0.1:4931") == "local"
    assert _infer_env_from_base_url("http://localhost:4931") == "local"


# ---- DO_BASE_URL in constructor ----


def test_do_base_url_env_sets_base_url_and_env() -> None:
    """Test that DO_BASE_URL overrides default env/base_url resolution."""
    os.environ["DO_BASE_URL"] = "https://api.dev.deeporigin.io"
    os.environ["DO_AUTH_TOKEN"] = "test-token"
    os.environ["DO_ORG_KEY"] = "test-org"

    client = DeepOriginClient()

    assert client.base_url.rstrip("/") == "https://api.dev.deeporigin.io"
    assert client.env == "dev"


def test_do_base_url_takes_priority_over_do_env() -> None:
    """Test that DO_BASE_URL wins when both DO_BASE_URL and DO_ENV are set."""
    os.environ["DO_BASE_URL"] = "https://api.staging.deeporigin.io"
    os.environ["DO_ENV"] = "prod"
    os.environ["DO_AUTH_TOKEN"] = "test-token"
    os.environ["DO_ORG_KEY"] = "test-org"

    client = DeepOriginClient()

    assert client.env == "staging"
    assert "staging" in client.base_url


def test_do_base_url_with_from_env() -> None:
    """Test that from_env respects DO_BASE_URL."""
    os.environ["DO_BASE_URL"] = "https://api.dev.deeporigin.io"

    with (
        patch("deeporigin.platform.client.get_token") as mock_get_token,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_token.return_value = "token-dev"
        mock_get_value.return_value = {"env": "prod", "org_key": "test-org"}

        client = DeepOriginClient.from_env()

        assert client.env == "dev"
        assert client.base_url.rstrip("/") == "https://api.dev.deeporigin.io"


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


def test_from_env_variables_missing_base_url_raises() -> None:
    """Test that missing DO_BASE_URL raises ValueError."""
    os.environ["DO_AUTH_TOKEN"] = "tok"
    os.environ["DO_ORG_KEY"] = "org"

    with pytest.raises(ValueError, match="DO_BASE_URL"):
        DeepOriginClient.from_env_variables()


# ---- Existing from_env tests ----


def test_from_env_reads_token_and_org_key_from_files() -> None:
    """Test that from_env reads token from api_tokens.json and org_key from config."""
    with (
        patch("deeporigin.platform.client.get_token") as mock_get_token,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_token.return_value = "token_from_file"
        mock_get_value.return_value = {"env": "prod", "org_key": "org_from_config"}

        client = DeepOriginClient.from_env(env="prod")

        assert client.token == "token_from_file"
        assert client.org_key == "org_from_config"
        assert client.env == "prod"
        mock_get_token.assert_called_once_with(env="prod")
        mock_get_value.assert_called_once()


def test_from_env_with_explicit_env() -> None:
    """Test that from_env uses explicit env parameter when provided."""
    with (
        patch("deeporigin.platform.client.get_token") as mock_get_token,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_token.return_value = "token_staging"
        mock_get_value.return_value = {"env": "prod", "org_key": "org_from_config"}

        client = DeepOriginClient.from_env(env="staging")

        assert client.token == "token_staging"
        assert client.org_key == "org_from_config"
        assert client.env == "staging"
        mock_get_token.assert_called_once_with(env="staging")


def test_from_env_reads_token_from_file() -> None:
    """Test that from_env reads token from file."""
    with (
        patch("deeporigin.platform.client.get_token") as mock_get_token,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_token.return_value = "token_from_file"
        mock_get_value.return_value = {"env": "prod", "org_key": "org_from_config"}

        client = DeepOriginClient.from_env(env="prod")

        assert client.token == "token_from_file"
