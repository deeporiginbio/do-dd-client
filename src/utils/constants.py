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

ENTITY_SEARCH_TIMEOUT_SECONDS = 60.0
"""HTTP timeout (seconds) for data-platform entity search requests.

Some filter combinations (e.g. ``molecular_weight`` range on ligands) can take
longer than the client's default 10s read timeout on dev and staging."""

LIGAND_MOLPROPS_SET_FIELDS: frozenset[str] = frozenset(
    (
        "molecular_weight",
        "hbond_donor_count",
        "hbond_acceptor_count",
        "rotatable_bond_count",
        "tpsa",
    )
)
"""Ligand ``set`` fields computed by molprops; not writable on create/update."""

RESULT_EXPLORER_CANONICAL_SORT_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "modified_by",
        "deleted",
        "project_id",
        "execution_id",
        "tool_id",
        "tool_key",
        "tool_version",
        "measured_at",
        "ligand_canonical_id",
        "protein_canonical_id",
        "result_table_name",
        "compute_job_id",
        "execution_name",
        "tool_name",
    }
)
"""Scalar result-explorer columns that support cursor pagination in ``sort``.

Whole JSON payload columns such as ``data`` and ``parameters`` are excluded:
sorting by them requires offset pagination (same as nested tool-data keys).
"""

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

PROTEIN_PREP_PDB_ID_PATTERN = r"^[A-Za-z0-9]{4}$"
"""JSON Schema pattern for Protein Prep ``pdb_id`` (loop-modelling templates)."""

PROTEIN_PREP_NO_OUTPUT_PATHS_MSG = (
    "Protein preparation did not return a prepared PDB path. "
    "The tool execution may have failed or returned an unexpected format."
)
"""Used by ``ProteinPrep.get_results`` when the prepared PDB path is missing."""

PROTEIN_PREP_PDB_ID_REQUIRED_MSG = (
    "pdb_id is required when preparing with loop modelling. "
    "Pass pdb_id= as a 4-character PDB identifier, or set protein.pdb_id. "
    "To skip loop modelling, pass model_missing_loops=False."
)
"""Used by ``ProteinPrep`` when prepare + loops-on is missing ``pdb_id``."""

PROTEIN_PREP_NO_RECOMMENDATION_MSG = (
    "Protein Prep did not return a recommendation. "
    "This execution may have used action='prepare', failed, or returned an "
    "unexpected format."
)
"""Used by ``ProteinPrep.get_recommendation`` when the inventory is missing."""

PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG = (
    "This ProteinPrep ran action='recommend' and did not produce a prepared "
    "protein. Call get_recommendation(), then as_prepare() (or "
    "ProteinPrep.from_recommendation) to submit a prepare run."
)
"""Used by ``ProteinPrep.get_results`` on a recommend execution."""

PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG = (
    "run() is only valid for prepare with model_missing_loops=False. "
    "Use start() for recommend or for prepare with loop modelling, or call "
    "as_prepare(model_missing_loops=False) first."
)
"""Used by ``ProteinPrep.run`` when the instance is not loops-off prepare."""

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

TOOL_EXECUTION_GET_ACCEPT_HEADER = "application/json;v=2.0"
"""Accept header for tools-service ``GET .../executions/{id}`` (v2 execution DTO)."""

TOOL_KEY_PREFIX = "deeporigin."
"""Platform tool-key prefix omitted in compact display (e.g. user log tables)."""

MOLPROPS_PROPERTY_KEYS: frozenset[str] = frozenset(
    ("logd", "logp", "logs", "pains"),
)
"""Allowed molprops tool suffix keys (``deeporigin.mol-props-<key>``)."""

MOLPROPS_DEFAULT_PROPERTIES: frozenset[str] = MOLPROPS_PROPERTY_KEYS
"""Default full ADMET bundle for :class:`~deeporigin.drug_discovery.molprops.Molprops`."""

ADMET_EXECUTION_TIMEOUT_SECONDS = 900.0
"""HTTP timeout (seconds) for ``deeporigin.admet-properties`` sync runs.

Cold-start model loading in the admet-now served image can exceed the default
600s POST timeout."""

JOB_WATCH_BLOCK_ENV = "JOB_WATCH_BLOCK"
"""Env var for blocking :meth:`~deeporigin.drug_discovery.notebook_watch_mixin.NotebookWatchMixin.watch`.

When set to a truthy value (``1``, ``true``, ``yes``, ``on``), ``watch()`` blocks the
notebook cell until the execution reaches a terminal state. Used by doc notebook CI
(``scripts/build_docs.sh``) and ``nbconvert --execute``."""

PROGRESS_TREE_DISPLAY_ACRONYMS: frozenset[str] = frozenset({"abfe", "rbfe"})
"""Workflow step tokens uppercased in progress-tree node labels (e.g. RBFE, ABFE)."""

ENUMERATOR_JOB_TYPES: frozenset[str] = frozenset(
    {"SCAFFOLD", "ANALOGUE", "AVAILABLE_REACTIONS", "REACTION"}
)
"""Valid ``job_type`` values for ``deeporigin.enumerator``.

``SCAFFOLD`` and ``ANALOGUE`` are the two CReM matched-molecular-pair (MMP)
flavors; ``AVAILABLE_REACTIONS`` discovers named-reaction sites; ``REACTION``
enumerates products against the Enamine fragment library."""

ENUMERATOR_MMP_JOB_TYPES: frozenset[str] = frozenset({"SCAFFOLD", "ANALOGUE"})
"""``job_type`` values that run CReM MMP enumeration (require ``replace_ix``)."""

ENUMERATOR_RADIUS_MIN = 1
"""Minimum CReM environment ``radius`` accepted by the enumerator (MMP modes)."""

ENUMERATOR_RADIUS_MAX = 5
"""Maximum CReM environment ``radius`` accepted by the enumerator (MMP modes)."""

ENUMERATOR_MAX_FRAGMENT_SIZE_MIN = 1
"""Minimum ``max_fragment_size`` accepted by the enumerator (MMP modes)."""

ENUMERATOR_MAX_FRAGMENT_SIZE_MAX = 15
"""Maximum ``max_fragment_size`` accepted by the enumerator (MMP modes)."""

ENUMERATOR_MAX_REACTION_SITES = 16
"""Maximum number of ``reaction_sites`` accepted per REACTION enumeration."""

ENUMERATOR_RESULTS_CSV_COLUMNS: tuple[str, ...] = (
    "row_id",
    "smiles",
    "parent_smiles",
    "enumeration_mode",
    "parent_ligand_id",
    "job_type",
    "replace_ix",
    "radius",
    "max_fragment_size",
    "reaction_id",
    "reactant_role",
    "atom_indices",
    "building_block_id",
)
"""Base column order of the enumerator ``results.csv`` (before RDKit descriptors)."""

ENUMERATOR_RDKIT_DESCRIPTOR_COLUMNS: tuple[str, ...] = (
    "molecular_weight",
    "hbond_donor_count",
    "hbond_acceptor_count",
    "logp",
    "tpsa",
    "rotatable_bond_count",
)
"""RDKit descriptor columns appended to the enumerator ``results.csv``."""

ENUMERATOR_AVAILABLE_REACTIONS_COLUMNS: tuple[str, ...] = (
    "reaction_id",
    "reaction_name",
    "reactant_role",
    "atom_indices",
)
"""Column order for the DataFrame built from AVAILABLE_REACTIONS ``jobOutputs``."""
