"""this module handles authentication actions and interactions
with tokens"""

from functools import lru_cache
import json
import os
import time
from typing import Optional
from urllib.parse import urljoin

from beartype import beartype
import jwt
from jwt.algorithms import RSAAlgorithm
import requests

from deeporigin.config import get_value as get_config
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import ENV_VARIABLES, ENVS
from deeporigin.utils.core import _get_api_tokens_filepath, read_cached_tokens

__all__ = [
    "get_tokens",
    "cache_tokens",
    "remove_cached_tokens",
    "authenticate",
    "refresh_tokens",
]

AUTH_DOMAIN = {
    "prod": "https://formicbio.us.auth0.com",
    "staging": "https://formicbio.us.auth0.com",
    "edge": "https://edge.login.deeporigin.io",
}

AUTH_DEVICE_CODE_ENDPOINT = "/oauth/device/code"
AUTH_TOKEN_ENDPOINT = "/oauth/token"
AUTH_AUDIENCE = "https://os.deeporigin.io/api"


AUTH_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

AUTH_CLIENT_ID = {
    "prod": "m3iyUcrANcIap2ogzWKpnYxCNujOrW3s",
    "staging": "2AMGd2bJnKjMtd7QBvJYlGPqb9vtntsY",
    "edge": "jbYq4bkeX2UJb1bePH1ci172KbUMVyak",
}

AUTH_CLIENT_SECRET = {
    "prod": "cQcZclTqMHMuovyXV-DD15tEiL-KH_2XD36vsppULRBuq7AjwyI4dh5ag11O_K1S",
    "staging": "WNoSHfEIBfM8cSpwhU2k30uGaCD3Uo6KhyklSYsWecrPKHjR9MEdeP3YF094GvZt",
    "edge": "dyXkC91flTvTrqnFDAheysQeUHMT97B8Ah47OssdMjTFDTSdkYq8cqhCASb_fTBK",
}


@beartype
def tokens_exist() -> bool:
    """Check if the cached API tokens exist"""

    return os.path.isfile(_get_api_tokens_filepath())


def get_tokens(never_prompt: bool = False) -> dict:
    """Get access token for accessing the Deep Origin API

    Gets tokens to access Deep Origin API.


    If an access token exists in the ENV, then it is used before
    anything else. If not, then tokens file is
    checked for access tokens, and used if they exist.

    Args:
        never_prompt: when True, will not prompt the user to sign in

    Returns:
        API access and refresh tokens
    """

    tokens = {}

    if tokens_exist():
        # tokens exist on disk
        tokens = read_cached_tokens()

    # tokens in env override tokens on disk
    # try to read from env
    if ENV_VARIABLES["access_token"] in os.environ:
        tokens["access"] = os.environ[ENV_VARIABLES["access_token"]]
    if ENV_VARIABLES["refresh_token"] in os.environ:
        tokens["refresh"] = os.environ[ENV_VARIABLES["refresh_token"]]

    if "access" not in tokens.keys() and not never_prompt:
        # no tokens in env. have to sign into the platform to get tokens
        tokens = authenticate()

    if "access" not in tokens.keys():
        raise DeepOriginException(
            "No access token found. Failed to get a token from the environment or disk."
        )

    # check if the access token is expired
    try:
        if is_token_expired(decode_access_token(tokens["access"])):
            tokens["access"] = refresh_tokens(tokens["refresh"])
            cache_tokens(tokens)
    except jwt.DecodeError:
        # token decoding failed. issue a warning
        print("⚠️ Token decoding failed. Please sign in again.")

    return tokens


@beartype
def cache_tokens(tokens: dict) -> None:
    """Save access and refresh tokens to a local file, for example, to
    enable variables/secrets to be regularly pulled without the user
    needing to regularly re-login.

    Args:
        token: dictionary with access and refresh tokens
    """

    with open(_get_api_tokens_filepath(), "w") as file:
        json.dump(tokens, file)


def remove_cached_tokens() -> None:
    """Remove cached API tokens"""

    if os.path.isfile(_get_api_tokens_filepath()):
        os.remove(_get_api_tokens_filepath())


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

    response = requests.post(AUTH_DOMAIN[env] + AUTH_DEVICE_CODE_ENDPOINT, json=body)
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
        response = requests.post(AUTH_DOMAIN[env] + AUTH_TOKEN_ENDPOINT, json=body)
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
        cache_tokens(tokens)

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
    response = requests.post(AUTH_DOMAIN[env] + AUTH_TOKEN_ENDPOINT, json=body)
    response.raise_for_status()
    response_json = response.json()
    api_access_token = response_json["access_token"]

    return api_access_token


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
    data = requests.get(jwks_url).json()
    return data["keys"]


@beartype
def decode_access_token(
    token: Optional[str] = None,
    env: Optional[ENVS] = None,
) -> dict:
    """decode access token into human readable data"""

    if env == "local":
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
        tokens = get_tokens()
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
