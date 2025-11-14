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

ENVS = Literal["edge", "prod", "staging", "local"]

API_ENDPOINT = {
    "prod": "https://api.deeporigin.io",
    "staging": "https://api.staging.deeporigin.io",
    "edge": "https://api.edge.deeporigin.io",
}


ENV_VARIABLES = {
    "access_token": "DEEPORIGIN_TOKEN",
    "refresh_token": "DEEPORIGIN_REFRESH_TOKEN",
    "org_key": "DEEPORIGIN_ORG_KEY",
    "env": "DEEPORIGIN_ENV",
}
