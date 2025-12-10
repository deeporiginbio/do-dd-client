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

API_ENDPOINT = {
    "prod": "https://api.deeporigin.io",
    "staging": "https://api.staging.deeporigin.io",
    "dev": "https://api.dev.deeporigin.io",
    "local": "http://127.0.0.1:4931",
}


ENV_VARIABLES = {
    "access_token": "DEEPORIGIN_TOKEN",
    "org_key": "DEEPORIGIN_ORG_KEY",
    "env": "DEEPORIGIN_ENV",
}
