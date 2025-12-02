"""Tests for environment variable fallbacks in platform DeepOriginClient."""

import os
from typing import Generator

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
