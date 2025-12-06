"""this module handles authentication actions and interactions
with tokens"""

from functools import lru_cache
import json
import os
from pathlib import Path
import time
from typing import Optional
from urllib.parse import urljoin

from beartype import beartype
import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from deeporigin.config import get_value as get_config
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import ENV_VARIABLES, ENVS
from deeporigin.utils.core import (
    _ensure_do_folder,
    _supports_unicode_output,
)

__all__ = [
    "get_tokens",
    "cache_tokens",
    "remove_cached_tokens",
    "authenticate",
    "refresh_tokens",
    "save_token",
]

AUTH_DOMAIN = {
    "dev": "https://login.dev.deeporigin.io",
    "prod": "https://formicbio.us.auth0.com",
    "staging": "https://formicbio.us.auth0.com",
}

AUTH_DEVICE_CODE_ENDPOINT = "/oauth/device/code"
AUTH_TOKEN_ENDPOINT = "/oauth/token"
AUTH_AUDIENCE = "https://os.deeporigin.io/api"


AUTH_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

AUTH_CLIENT_ID = {
    "prod": "m3iyUcrANcIap2ogzWKpnYxCNujOrW3s",
}

AUTH_CLIENT_SECRET = {
    "prod": "cQcZclTqMHMuovyXV-DD15tEiL-KH_2XD36vsppULRBuq7AjwyI4dh5ag11O_K1S",
}


@beartype
def _get_api_tokens_filepath() -> Path:
    """get location of the api tokens file"""

    return _ensure_do_folder() / "api_tokens.json"


@beartype
def read_cached_tokens(*, env: ENVS | None = None) -> dict:
    """Read cached API tokens for a specific environment.

    Args:
        env: Environment name (e.g., 'prod', 'staging', 'edge').
            If None, reads from config.

    Returns:
        Dictionary with 'access' and 'refresh' tokens for the specified environment.
        Returns empty dict if tokens don't exist for that environment.
    """
    if env is None:
        env = get_config()["env"]

    filepath = _get_api_tokens_filepath()

    if not filepath.exists():
        return {}

    with open(filepath, "r") as file:
        all_tokens = json.load(file)

    # Return tokens for the specific environment
    return all_tokens.get(env, {})


@beartype
def tokens_exist(*, env: ENVS | None = None) -> bool:
    """Check if cached API tokens exist for a specific environment.

    Args:
        env: Environment name. If None, checks for current config environment.

    Returns:
        True if tokens exist for the environment, False otherwise.
    """
    if env is None:
        env = get_config()["env"]

    filepath = _get_api_tokens_filepath()

    if not filepath.exists():
        return False

    with open(filepath, "r") as file:
        all_tokens = json.load(file)

    return bool(env in all_tokens and all_tokens[env])


def get_tokens(never_prompt: bool = False, *, env: ENVS | None = None) -> dict:
    """Get access token for accessing the Deep Origin API

    Gets tokens to access Deep Origin API.


    If an access token exists in the ENV, then it is used before
    anything else. If not, then tokens file is
    checked for access tokens, and used if they exist.

    Args:
        never_prompt: when True, will not prompt the user to sign in
        env: Environment name. If None, uses current config environment.

    Returns:
        API access and refresh tokens
    """
    if env is None:
        env = get_config()["env"]

    tokens = {}

    if tokens_exist(env=env):
        # tokens exist on disk
        tokens = read_cached_tokens(env=env)

    # tokens in env override tokens on disk
    # try to read from env
    if ENV_VARIABLES["access_token"] in os.environ:
        tokens["access"] = os.environ[ENV_VARIABLES["access_token"]]
    if ENV_VARIABLES["refresh_token"] in os.environ:
        tokens["refresh"] = os.environ[ENV_VARIABLES["refresh_token"]]

    if env in ["dev", "local", "staging"]:
        return tokens

    if "access" not in tokens.keys() and not never_prompt:
        # no tokens in env. have to sign into the platform to get tokens
        tokens = authenticate(env=env)

    if "access" not in tokens.keys():
        raise DeepOriginException(
            "No access token found. Failed to get a token from the environment or disk."
        )

    # check if the access token is expired
    try:
        if is_token_expired(decode_access_token(tokens["access"], env=env)):
            tokens["access"] = refresh_tokens(tokens["refresh"], env=env)
            cache_tokens(tokens, env=env)
    except jwt.DecodeError:
        # token decoding failed. issue a warning
        print("⚠️ Token decoding failed. Please sign in again.")

    return tokens


@beartype
def cache_tokens(tokens: dict, *, env: ENVS | None = None) -> None:
    """Save access and refresh tokens to a local file, for example, to
    enable variables/secrets to be regularly pulled without the user
    needing to regularly re-login.

    Args:
        tokens: dictionary with access and refresh tokens
        env: Environment name. If None, uses current config environment.
    """
    if env is None:
        env = get_config()["env"]

    filepath = _get_api_tokens_filepath()

    # Load existing tokens for all environments
    all_tokens = {}
    if filepath.exists():
        with open(filepath, "r") as file:
            all_tokens = json.load(file)

    # Update tokens for the specific environment
    all_tokens[env] = {
        "access": tokens["access"],
        "refresh": tokens.get("refresh", ""),
    }

    # Write back all environments
    with open(filepath, "w") as file:
        json.dump(all_tokens, file, indent=2)


def remove_cached_tokens(*, env: ENVS | None = None, remove_all: bool = False) -> None:
    """Remove cached API tokens for a specific environment or all environments.

    Args:
        env: Environment name. If None and remove_all is False, removes tokens for current config environment.
        remove_all: If True, removes all tokens and deletes the file regardless of env parameter.
    """
    filepath = _get_api_tokens_filepath()

    if remove_all:
        # Remove entire file
        if filepath.exists():
            filepath.unlink()
        return

    if env is None:
        env = get_config()["env"]

    # Remove tokens for specific environment
    if filepath.exists():
        with open(filepath, "r") as file:
            all_tokens = json.load(file)

        # Remove specific environment
        if env in all_tokens:
            del all_tokens[env]

        # Write back (or remove file if empty)
        if all_tokens:
            with open(filepath, "w") as file:
                json.dump(all_tokens, file, indent=2)
        else:
            filepath.unlink()


@beartype
def authenticate(
    *,
    env: Optional[ENVS] = None,
    save_tokens: bool = True,
) -> dict:
    """Get an access token for use with the Deep Origin API.
    The tokens are also cached to file

    Returns:
        :obj:`tuple`: API access token, API refresh token
    """

    if env is None:
        env = get_config()["env"]

    # Get a link for the user to sign into the Deep Origin platform

    body = {
        "client_id": AUTH_CLIENT_ID[env],
        "scope": "offline_access",
        "audience": AUTH_AUDIENCE,
    }

    response = httpx.post(AUTH_DOMAIN[env] + AUTH_DEVICE_CODE_ENDPOINT, json=body)
    response.raise_for_status()
    response_json = response.json()
    device_code = response_json["device_code"]
    user_code = response_json["user_code"]
    verification_url = response_json["verification_uri_complete"]
    sign_in_poll_interval_sec = response_json["interval"]

    # Prompt the user to sign into the Deep Origin platform
    print(
        (
            "To connect to the Deep Origin Platform API, "
            f"navigate your browser to \n\n{verification_url}\n\n"
            f'and verify the confirmation code is "{user_code}", '
            'and click the "Confirm" button.'
        )
    )

    body = {
        "grant_type": AUTH_GRANT_TYPE,
        "device_code": device_code,
        "client_id": AUTH_CLIENT_ID[env],
    }
    # Wait for the user to sign into the Deep Origin platform
    while True:
        response = httpx.post(AUTH_DOMAIN[env] + AUTH_TOKEN_ENDPOINT, json=body)
        if response.status_code == 200:
            break
        if (
            response.status_code != 403
            or response.json().get("error", None) != "authorization_pending"
        ):
            raise DeepOriginException(
                message="Sign in to Deep Origin failed. Please try again."
            )
        time.sleep(sign_in_poll_interval_sec)

    response_json = response.json()
    api_access_token = response_json["access_token"]
    api_refresh_token = response_json["refresh_token"]

    tokens = {
        "access": api_access_token,
        "refresh": api_refresh_token,
    }

    if save_tokens:
        cache_tokens(tokens, env=env)

    return tokens


@beartype
def refresh_tokens(api_refresh_token: str, *, env: Optional[ENVS] = None) -> str:
    """Refresh the access token for the Deep Origin OS

    Args:
        api_refresh_token: API refresh token

    Returns:
        new API access token
    """

    if env is None:
        env = get_config()["env"]

    body = {
        "grant_type": "refresh_token",
        "client_id": AUTH_CLIENT_ID[env],
        "client_secret": AUTH_CLIENT_SECRET[env],
        "refresh_token": api_refresh_token,
    }
    response = httpx.post(AUTH_DOMAIN[env] + AUTH_TOKEN_ENDPOINT, json=body)
    response.raise_for_status()
    response_json = response.json()
    api_access_token = response_json["access_token"]

    return api_access_token


@beartype
def save_token(token: str, *, env: ENVS | None = None) -> None:
    """Save a long-lived token from the UI to disk.

    This function validates and saves a long-lived token obtained from the
    Deep Origin UI. The token will be stored in the api_tokens.json file
    and used by get_tokens() and client initialization.

    Args:
        token: Long-lived token string obtained from the UI.
        env: Environment name. If None, reads from config.

    Raises:
        DeepOriginException: If token is invalid or cannot be decoded.
    """
    if env is None:
        env = get_config()["env"]

    # Store in same format as current tokens (environment-specific)
    tokens = {"access": token}
    cache_tokens(tokens, env=env)

    # Print confirmation
    if _supports_unicode_output():
        check = "✔︎"
    else:
        check = "OK"
    print(f"{check} Long-lived token saved successfully for environment '{env}'")


@beartype
def is_token_expired(token: dict) -> bool:
    """
    Check if the JWT token is expired. The token is expected to have an 'exp' field as a Unix timestamp. This dict can be obtained from the `decode_access_token` function.

    Args:
        token (dict): The JWT token with an 'exp' field as a Unix timestamp.

    Returns:
        bool: True if the token is expired, False otherwise.
    """
    # Get the expiration time from the token, defaulting to 0 if not found.
    exp_time = token.get("exp", 0)
    current_time = time.time()  # Get current time in seconds since the epoch.

    # If current time is greater than the expiration time, it's expired.
    return current_time > exp_time


@lru_cache(maxsize=3)
@beartype
def get_public_keys(env: Optional[ENVS] = None) -> list[dict]:
    """get public keys from public endpoint"""

    if env is None:
        env = get_config()["env"]

    jwks_url = urljoin(AUTH_DOMAIN[env], ".well-known/jwks.json")
    data = httpx.get(jwks_url).json()
    return data["keys"]


@beartype
def decode_access_token(
    token: Optional[str] = None,
    env: Optional[ENVS] = None,
) -> dict:
    """decode access token into human readable data"""

    if env == "local":
        # we fake a decoded token for local development
        now = int(time.time())
        one_year_seconds = 365 * 24 * 60 * 60
        return {
            "https://deeporigin.io/claims/id/userHandle": "user-deeporigin-com",
            "https://deeporigin.io/claims/id/userid": "google-apps|user@deeporigin.com",
            "https://deeporigin.io/claims/id/email": "user@deeporigin.com",
            "https://deeporigin.io/claims/id/emailVerified": True,
            "userHandle": "user-deeporigin-com",
            "userid": "google-apps|user@deeporigin.com",
            "emailVerified": True,
            "iss": "https://formicbio.us.auth0.com/",
            "sub": "google-apps|user@deeporigin.com",
            "aud": "https://os.deeporigin.io/api",
            "iat": now,
            "exp": now + one_year_seconds,
            "scope": "offline_access",
        }

    if token is None:
        tokens = get_tokens(env=env)
        token = tokens["access"]

    # Get the JWT header to extract the Key ID
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header["kid"]

    # Get the public key using the Key ID
    public_keys = get_public_keys(env=env)
    for key in public_keys:
        if key["kid"] == kid:
            public_key = RSAAlgorithm.from_jwk(key)
            break
        raise DeepOriginException(f"Key ID {kid} not found in JWKS.")

    # Decode the JWT using the public key
    return jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        options={
            "verify_aud": False,  # matches what platform does
            "verify_exp": False,  # we want to decode this no matter what, because we'll check the expiration in the caller
        },
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
