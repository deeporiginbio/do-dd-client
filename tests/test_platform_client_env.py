"""Tests for environment variable fallbacks in platform DeepOriginClient."""

import os
from typing import Generator
from unittest.mock import patch

import pytest

from deeporigin.platform.client import DeepOriginClient


@pytest.fixture(autouse=True)
def clear_env() -> Generator[None, None, None]:
    """Clear relevant env vars for each test to avoid cross-test contamination."""
    keys = ["DEEPORIGIN_TOKEN", "DEEPORIGIN_ENV", "DEEPORIGIN_ORG_KEY"]
    old = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


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
        mock_get_value.assert_called_once()  # Called for org_key


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
