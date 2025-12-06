"""Tests for environment variable fallbacks in platform DeepOriginClient."""

import json
import os
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

from deeporigin.exceptions import DeepOriginException
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


def test_env_fallbacks_with_defaults() -> None:
    os.environ["DEEPORIGIN_TOKEN"] = "tok_abc"
    os.environ["DEEPORIGIN_ORG_KEY"] = "org_123"
    # DEEPORIGIN_ENV intentionally not set -> defaults to prod

    client = DeepOriginClient()

    assert client.token == "tok_abc"
    assert client.org_key == "org_123"
    assert client.base_url.endswith("deeporigin.io/")


def test_kwarg_overrides_env() -> None:
    os.environ["DEEPORIGIN_TOKEN"] = "tok_env"
    os.environ["DEEPORIGIN_ORG_KEY"] = "org_env"
    os.environ["DEEPORIGIN_ENV"] = "staging"

    client = DeepOriginClient(token="tok_kw", org_key="org_kw", env="dev")

    assert client.token == "tok_kw"
    assert client.org_key == "org_kw"
    assert "dev" in client.base_url or client.base_url.endswith("dev.deeporigin.io/")


def test_org_key_raises_when_empty_string() -> None:
    """Test that accessing org_key raises DeepOriginException when it's an empty string."""
    os.environ["DEEPORIGIN_TOKEN"] = "tok_abc"
    os.environ["DEEPORIGIN_ENV"] = "prod"

    client = DeepOriginClient(token="tok_abc", org_key="", env="prod")

    with pytest.raises(DeepOriginException, match="not set or is empty"):
        _ = client.org_key


def test_org_key_returns_valid_value() -> None:
    """Test that accessing org_key returns the value when it's valid."""
    os.environ["DEEPORIGIN_TOKEN"] = "tok_abc"
    os.environ["DEEPORIGIN_ENV"] = "prod"

    client = DeepOriginClient(token="tok_abc", org_key="org_valid", env="prod")

    assert client.org_key == "org_valid"


def test_from_env_reads_token_and_org_key_from_files() -> None:
    """Test that from_env reads token from api_tokens.json and org_key from config."""
    with (
        patch("deeporigin.platform.client.get_tokens") as mock_get_tokens,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_tokens.return_value = {
            "access": "token_from_file",
            "refresh": "refresh_from_file",
        }
        mock_get_value.return_value = {"env": "prod", "org_key": "org_from_config"}

        client = DeepOriginClient.from_env(env="prod")

        assert client.token == "token_from_file"
        assert client.org_key == "org_from_config"
        assert client.env == "prod"
        mock_get_tokens.assert_called_once_with(env="prod")
        mock_get_value.assert_called_once()  # Called for org_key


def test_from_env_with_explicit_env() -> None:
    """Test that from_env uses explicit env parameter when provided."""
    with (
        patch("deeporigin.platform.client.get_tokens") as mock_get_tokens,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_tokens.return_value = {
            "access": "token_staging",
            "refresh": "refresh_staging",
        }
        mock_get_value.return_value = {"env": "prod", "org_key": "org_from_config"}

        client = DeepOriginClient.from_env(env="staging")

        assert client.token == "token_staging"
        assert client.org_key == "org_from_config"
        assert client.env == "staging"
        mock_get_tokens.assert_called_once_with(env="staging")


def test_from_env_uses_refresh_token_from_file() -> None:
    """Test that from_env includes refresh token when available."""
    with (
        patch("deeporigin.platform.client.get_tokens") as mock_get_tokens,
        patch("deeporigin.platform.client.get_value") as mock_get_value,
    ):
        mock_get_tokens.return_value = {
            "access": "token_from_file",
            "refresh": "refresh_from_file",
        }
        mock_get_value.return_value = {"env": "prod", "org_key": "org_from_config"}

        client = DeepOriginClient.from_env(env="prod")

        assert client.refresh_token == "refresh_from_file"
