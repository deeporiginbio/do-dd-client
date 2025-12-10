"""this module handles authentication actions and interactions
with tokens"""

import json
import os
from pathlib import Path
import time

from beartype import beartype
import httpx
import jwt

from deeporigin.config import get_value as get_config
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import ENV_VARIABLES, ENVS
from deeporigin.utils.core import (
    _ensure_do_folder,
    _supports_unicode_output,
)

__all__ = [
    "get_token",
    "save_token",
]

AUTH_DOMAIN = {
    "dev": "https://login.dev.deeporigin.io",
    "prod": "https://login.deeporigin.io",
    "staging": "https://login.staging.deeporigin.io",
}


@beartype
def _get_api_tokens_filepath() -> Path:
    """get location of the api tokens file"""

    return _ensure_do_folder() / "api_tokens.json"


@beartype
def read_cached_token(*, env: ENVS | None = None) -> str | None:
    """Read cached API access token for a specific environment.

    Args:
        env: Environment name (e.g., 'prod', 'staging', 'edge').
            If None, reads from config.

    Returns:
        Access token string for the specified environment.
        Returns None if token does not exist for that environment.
    """
    if env is None:
        env = get_config()["env"]

    filepath = _get_api_tokens_filepath()

    if not filepath.exists():
        return None

    with open(filepath, "r") as file:
        all_tokens = json.load(file)

    # Return access token for the specific environment
    return all_tokens.get(env)


@beartype
def tokens_exist(*, env: ENVS | None = None) -> bool:
    """Check if cached API token exist for a specific environment.

    Args:
        env: Environment name. If None, checks for current config environment.

    Returns:
        True if token exists for the environment, False otherwise.
    """
    if env is None:
        env = get_config()["env"]

    filepath = _get_api_tokens_filepath()

    if not filepath.exists():
        return False

    with open(filepath, "r") as file:
        all_tokens = json.load(file)

    return bool(env in all_tokens and all_tokens[env])


@beartype
def get_token(*, env: ENVS | None = None) -> str:
    """Get access token for accessing the Deep Origin API

    Gets token to access Deep Origin API.


    If an access token exists in the ENV, then it is used before
    anything else. If not, then the tokens file is
    checked for access token, and used if they exist.

    Args:
        env: Environment name. If None, uses current config environment.

    Returns:
        API access token string
    """
    if env is None:
        env = get_config()["env"]

    token = None

    # Try to read from disk first
    if tokens_exist(env=env):
        token = read_cached_token(env=env)

    # tokens in env override tokens on disk
    if ENV_VARIABLES["access_token"] in os.environ:
        token = os.environ[ENV_VARIABLES["access_token"]]

    if not token:
        raise DeepOriginException(
            "No access token found. Failed to get a token from the environment or disk."
        )

    # check if the access token is expired
    if is_token_expired(token):
        raise DeepOriginException(
            title="Token Expired",
            message="Token is expired. Please refer to https://client-docs.deeporigin.io/how-to/auth.html to get a new token.",
            level="danger",
        )

    return token


@beartype
def token_to_env(token: str) -> ENVS:
    """Determine the environment from a token's issuer.

    Args:
        token: Access token string.

    Returns:
        Environment name ('dev', 'staging', or 'prod').
    """
    decoded_token = decode_access_token(token)
    if "dev" in decoded_token["iss"]:
        return "dev"
    elif "staging" in decoded_token["iss"]:
        return "staging"
    elif "local" in decoded_token["iss"]:
        return "local"
    else:
        return "prod"


@beartype
def save_token(token: str) -> None:
    """Save a long-lived token from the UI to disk.

    This function validates and saves a long-lived token obtained from the
    Deep Origin UI. The token will be stored in the api_tokens.json file
    and used by get_token() and client initialization.

    Args:
        token: Long-lived token string obtained from the UI.


    Raises:
        DeepOriginException: If token is invalid or cannot be decoded.
    """

    env = token_to_env(token)
    decoded_token = decode_access_token(token)

    # Save tokens to disk
    filepath = _get_api_tokens_filepath()

    # Load existing tokens for all environments
    all_tokens = {}
    if filepath.exists():
        with open(filepath, "r") as file:
            all_tokens = json.load(file)

    # Update tokens for the specific environment
    all_tokens[env] = token

    # Write back all environments
    with open(filepath, "w") as file:
        json.dump(all_tokens, file, indent=2)

    name = decoded_token.get("name", "Unknown User")

    # Print confirmation
    if _supports_unicode_output():
        check = "✔︎"
    else:
        check = "OK"
    print(
        f"{check} Long-lived token for {name} saved successfully for environment '{env}'"
    )


@beartype
def is_token_expired(token: str) -> bool:
    """
    Check if the JWT token is expired. The token is expected to have an 'exp' field as a Unix timestamp.

    Args:
        token: The JWT token string to check.

    Returns:
        bool: True if the token is expired, False otherwise.
    """
    decoded_token = decode_access_token(token)
    # Get the expiration time from the token, defaulting to 0 if not found.
    exp_time = decoded_token.get("exp", 0)
    current_time = time.time()  # Get current time in seconds since the epoch.

    # If current time is greater than the expiration time, it's expired.
    return current_time > exp_time


@beartype
def decode_access_token(token: str) -> dict:
    """decode access token into human readable data"""

    # Get the JWT header
    header = jwt.get_unverified_header(token)

    # Decode the JWT using the public key
    return jwt.decode(
        token, algorithms=header["alg"], options={"verify_signature": False}
    )


@beartype
def _get_keycloak_token(
    *,
    email: str,
    password: str,
    realm: str = "deeporigin",
    base_url: str = "https://login.dev.deeporigin.io",
    scope: str = "openid email super-user",
) -> dict:
    """get a token, with optional super user scope from keycloak

    This returns a super-user token (if possible) from keycloak. Do not use this function.

    Args:
        email: the email of the super user
        password: the password of the super user
        realm: the realm to get the token from
        base_url: the base url of the keycloak instance
        scope: the scope of the token

    Raises:
        DeepOriginException: If email or password is empty or not a string.
    """
    # Validate input parameters
    if not email.strip():
        raise DeepOriginException(
            title="Invalid email parameter",
            message="Email must be a non-empty string.",
        )
    if not password.strip():
        raise DeepOriginException(
            title="Invalid password parameter",
            message="Password must be a non-empty string.",
        )

    keycloak_url = f"{base_url}/realms/{realm}/protocol/openid-connect/token"

    data = {
        "grant_type": "password",
        "username": email,
        "password": password,
        "client_id": "do-app",
        "scope": scope,
    }

    response = httpx.post(
        keycloak_url,
        data=data,  # sent as application/x-www-form-urlencoded
        # Let httpx set Content-Type automatically for form data
    )

    response.raise_for_status()
    return response.json()
