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

HTTP_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset((429, 500, 502, 503, 504))
"""HTTP status codes for which :class:`~deeporigin.platform.client.DeepOriginClient` retries requests."""

ENV_VARIABLES = {
    "access_token": "DO_AUTH_TOKEN",
    "org_key": "DO_ORG_KEY",
    "env": "DO_ENV",
    "base_url": "DO_BASE_URL",
    "project_id": "DO_PROJECT_ID",
}

UFA_PROVIDER = "ufa"
"""Provider identifier for UFA (Unified File Access) storage."""

PROJECTS_UNAVAILABLE_TITLE = "Projects unavailable"
"""Title for errors when ``DeepOriginClient.projects`` is missing."""

PROJECTS_UNAVAILABLE_DETAIL = (
    "DeepOriginClient was created without platform projects support."
)
"""Detail message when the client has no projects API."""

ENTITIES_UNAVAILABLE_TITLE = "Entities unavailable"
"""Title for errors when ``DeepOriginClient.entities`` is missing."""

ENTITIES_UNAVAILABLE_DETAIL = "DeepOriginClient was created without entities support."
"""Detail message when the client has no entities API."""

SYSPREP_NO_OUTPUT_PATHS_MSG = (
    "System preparation did not return output paths. "
    "The tool execution may have failed or returned an unexpected format."
)
"""Used by ``SystemPrep.run`` / ``get_results`` when output paths are missing."""

BOOTSTRAP_5_CSS_CDN_URL = (
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
)
"""Bootstrap 5 stylesheet URL for self-contained HTML fragments (e.g. notebook cards)."""

DOCKING_RESULTS_DATAFRAME_COLUMNS: tuple[str, ...] = (
    "ID",
    "protein ID",
    "ligand ID",
    "pocket ID",
    "binding energy",
    "pose_score",
    "best_pose",
)
"""Column order for :meth:`deeporigin.drug_discovery.docking.Docking.get_results`."""

TOOL_EXECUTION_POST_TIMEOUT_SECONDS = 600.0
"""HTTP timeout (seconds) for POST ``/tools/.../executions`` (quote and run).

600s aligns with typical server-side ``timeoutSeconds`` for tool workloads such
as molprops and protonation, where synchronous executions can take longer than
the client's default short timeout."""

EXECUTION_LIST_ORDER_CREATED_DESC = "createdAt desc"
"""Tools-service ``order`` query value for most-recently-created executions first."""

TOOL_KEY_PREFIX = "deeporigin."
"""Platform tool-key prefix omitted in compact display (e.g. user log tables)."""

MOLPROPS_PROPERTY_KEYS: frozenset[str] = frozenset(
    ("ames", "cyp", "herg", "logd", "logp", "logs", "pains"),
)
"""Allowed molprops tool suffix keys (``deeporigin.mol-props-<key>``)."""

MOLPROPS_DEFAULT_PROPERTIES: frozenset[str] = MOLPROPS_PROPERTY_KEYS
"""Default full ADMET bundle for :class:`~deeporigin.drug_discovery.molprops.Molprops`."""

JOB_WATCH_BLOCK_ENV = "JOB_WATCH_BLOCK"
"""Env var for blocking :meth:`~deeporigin.drug_discovery.notebook_watch_mixin.NotebookWatchMixin.watch`.

When set to a truthy value (``1``, ``true``, ``yes``, ``on``), ``watch()`` blocks the
notebook cell until the execution reaches a terminal state. Used by doc notebook CI
(``scripts/build_docs.sh``) and ``nbconvert --execute``."""
