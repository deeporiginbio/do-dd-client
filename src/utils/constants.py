"""this module contains constants used in the rest of this library"""

from beartype.typing import Literal

number = int | float

ENVS = Literal["dev", "prod", "staging", "local"]

LOCAL_ENDPOINT_DEFAULT = "http://127.0.0.1:6010"
"""Default local API base URL (platform gateway)."""

LOCAL_ENDPOINT_MOCK = "http://127.0.0.1:4931"
"""Local mock server URL used by unit tests."""

API_ENDPOINT = {
    "prod": "https://api.deeporigin.io",
    "staging": "https://api.staging.deeporigin.io",
    "dev": "https://api.dev.deeporigin.io",
    "local": LOCAL_ENDPOINT_DEFAULT,
}


DEFAULT_SEARCH_PAGE_SIZE = 100
"""Default page size for paginated entity search requests."""

ENV_VARIABLES = {
    "access_token": "DO_AUTH_TOKEN",
    "org_key": "DO_ORG_KEY",
    "env": "DO_ENV",
    "base_url": "DO_BASE_URL",
}

UFA_PROVIDER = "ufa"
"""Provider identifier for UFA (Unified File Access) storage."""

DEFAULT_APP_NAME = "do-dd-client"
"""Default app name sent with tools/executions and functions API calls."""
