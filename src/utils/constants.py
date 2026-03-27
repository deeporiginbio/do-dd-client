"""this module contains constants used in the rest of this library"""

from beartype.typing import Literal

number = int | float

ENVS = Literal["dev", "prod", "staging", "local"]

LOCAL_ENDPOINT_GATEWAY = "http://127.0.0.1:6010"
"""Platform API gateway when running the full stack locally (use via ``DO_BASE_URL``)."""

LOCAL_ENDPOINT_MOCK = "http://127.0.0.1:4931"
"""Default base URL for ``DO_ENV=local`` (API mock server; ``make mock-server``)."""

LOCAL_ENDPOINT_DEFAULT = LOCAL_ENDPOINT_MOCK
"""Deprecated alias for ``LOCAL_ENDPOINT_MOCK``. Use ``LOCAL_ENDPOINT_MOCK`` or ``LOCAL_ENDPOINT_GATEWAY``."""

API_ENDPOINT = {
    "prod": "https://api.deeporigin.io",
    "staging": "https://api.staging.deeporigin.io",
    "dev": "https://api.dev.deeporigin.io",
    "local": LOCAL_ENDPOINT_MOCK,
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

SYSPREP_NO_OUTPUT_PATHS_MSG = (
    "System preparation did not return output paths. "
    "The function run may have failed or returned an unexpected format."
)
"""Used by ``SystemPrep.run`` when binding/solvation/PDB paths are missing."""

BOOTSTRAP_5_CSS_CDN_URL = (
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
)
"""Bootstrap 5 stylesheet URL for self-contained HTML fragments (e.g. notebook cards)."""

TOOL_EXECUTION_POST_TIMEOUT_SECONDS = 120.0
"""HTTP timeout (seconds) for POST ``/tools/.../executions`` (quote and run).

Matches ``Functions.run`` long-timeout behavior: 120s allows the server time to
respond while the execution is created or quoted, beyond the client's default
short timeout."""
