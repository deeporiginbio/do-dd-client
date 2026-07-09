"""Tests for authentication token handling on disk."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Generator

import jwt
import pytest

from deeporigin.auth import (
    _get_keycloak_token,
    decode_access_token,
    get_token,
    is_token_expired,
    read_cached_token,
    save_token,
    token_to_env,
    tokens_exist,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import ENV_VARIABLES


def _jwt_str(token: str | bytes) -> str:
    """Normalize PyJWT output for env vars and disk storage."""
    return token.decode("utf-8") if isinstance(token, bytes) else token


def _make_token(
    *,
    issuer: str = "https://login.dev.deeporigin.io/realms/deeporigin",
    exp_offset: int = 3600,
    name: str = "Test User",
) -> str:
    """Build a signed HS256 JWT for auth unit tests."""
    return _jwt_str(
        jwt.encode(
            {
                "iss": issuer,
                "exp": int(time.time()) + exp_offset,
                "name": name,
            },
            "secret",
            algorithm="HS256",
        )
    )


@pytest.fixture(autouse=True)
def isolated_tokens_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect api_tokens.json to a temporary file for every auth test."""
    path = tmp_path / "api_tokens.json"
    monkeypatch.setattr(
        "deeporigin.auth._get_api_tokens_filepath",
        lambda: path,
    )
    return path


@pytest.fixture
def auth_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin config env to dev for auth tests."""
    monkeypatch.setattr(
        "deeporigin.auth.get_config",
        lambda: {"env": "dev", "org_key": "test-org"},
    )


@pytest.fixture(autouse=True)
def clear_access_token_env() -> Generator[None, None, None]:
    """Clear DO_AUTH_TOKEN between tests."""
    key = ENV_VARIABLES["access_token"]
    old = os.environ.get(key)
    os.environ.pop(key, None)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def test_tokens_exist_false_when_missing(auth_config: None) -> None:
    """tokens_exist returns False when the tokens file is absent."""
    assert tokens_exist(env="dev") is False


def test_read_cached_token_round_trip(auth_config: None) -> None:
    """save_token persists a token readable via read_cached_token."""
    token = _make_token()
    save_token(token)

    assert tokens_exist(env="dev") is True
    assert read_cached_token(env="dev") == token


def test_get_token_from_disk(
    isolated_tokens_file: Path,
    auth_config: None,
) -> None:
    """get_token returns a valid cached token."""
    token = _make_token()
    isolated_tokens_file.write_text(json.dumps({"dev": token}), encoding="utf-8")

    assert get_token(env="dev") == token


def test_get_token_env_overrides_disk(
    isolated_tokens_file: Path,
    auth_config: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment access token overrides the on-disk cache."""
    disk_token = _make_token(name="Disk")
    env_token = _make_token(name="Env")
    isolated_tokens_file.write_text(json.dumps({"dev": disk_token}), encoding="utf-8")
    monkeypatch.setenv(ENV_VARIABLES["access_token"], env_token)

    assert get_token(env="dev") == env_token


def test_get_token_missing_raises(auth_config: None) -> None:
    """get_token raises when no token is available."""
    with pytest.raises(DeepOriginException, match="No access token found"):
        get_token(env="dev")


def test_get_token_expired_raises(
    isolated_tokens_file: Path,
    auth_config: None,
) -> None:
    """get_token rejects expired tokens."""
    expired = _make_token(exp_offset=-60)
    isolated_tokens_file.write_text(json.dumps({"dev": expired}), encoding="utf-8")

    with pytest.raises(DeepOriginException, match="Token Expired"):
        get_token(env="dev")


@pytest.mark.parametrize(
    ("issuer", "expected"),
    [
        ("https://login.dev.deeporigin.io/realms/deeporigin", "dev"),
        ("https://login.staging.deeporigin.io/realms/deeporigin", "staging"),
        ("https://login.local.deeporigin.io/realms/deeporigin", "local"),
        ("https://login.deeporigin.io/realms/deeporigin", "prod"),
    ],
)
def test_token_to_env(issuer: str, expected: str) -> None:
    """token_to_env maps JWT issuer URLs to environment names."""
    token = _make_token(issuer=issuer)
    assert token_to_env(token) == expected


def test_decode_access_token() -> None:
    """decode_access_token returns the JWT payload without verification."""
    token = _make_token(name="Alice")
    payload = decode_access_token(token)

    assert payload["name"] == "Alice"
    assert "exp" in payload


def test_is_token_expired() -> None:
    """is_token_expired distinguishes valid and expired tokens."""
    valid = _make_token(exp_offset=3600)
    expired = _make_token(exp_offset=-10)

    assert is_token_expired(valid) is False
    assert is_token_expired(expired) is True


def test_get_keycloak_token_rejects_empty_email() -> None:
    """_get_keycloak_token validates email before calling Keycloak."""
    with pytest.raises(DeepOriginException, match="Invalid email"):
        _get_keycloak_token(email="  ", password="secret")


def test_get_keycloak_token_rejects_empty_password() -> None:
    """_get_keycloak_token validates password before calling Keycloak."""
    with pytest.raises(DeepOriginException, match="Invalid password"):
        _get_keycloak_token(email="user@example.com", password="")
