"""this module contains constants used in the rest of this library"""

from beartype.typing import Literal

FileStatus = Literal["ready", "archived"]
"""Status of a file. Ready files are ready to be used, downloaded, and operated on."""


DATAFRAME_ATTRIBUTE_KEYS = {
    "metadata",
    "id",
    "reference_ids",
    "last_updated_row",
}


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


ENV_VARIABLES = {
    "access_token": "DO_AUTH_TOKEN",
    "org_key": "DO_ORG_KEY",
    "env": "DO_ENV",
    "base_url": "DO_BASE_URL",
}
