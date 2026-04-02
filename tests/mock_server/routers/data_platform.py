"""Data-platform routes for the mock server."""

from __future__ import annotations

from collections.abc import Callable
import copy
from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Request
from rdkit import Chem

MOCK_CANONICAL_PROTEIN_ID = "brd"
MOCK_CANONICAL_PROTEIN_FILE_PATH = "testing/brd.pdb"

# Pocket id aligned with ``tests/fixtures/tool-runs/deeporigin.bulk-docking/quote.json``
# and PocketFinder-style mocks (``pocket.id`` on tool inputs).
MOCK_CANONICAL_POCKET_ID = "pocket-test-id"

MOCK_DEFAULT_PROJECT_NAME = "python-client-test-project-kfsresf"
# Stable id for the in-memory mock data platform only (not a public SDK constant).
MOCK_DEFAULT_PROJECT_ID = "09DEFAULTPROJECT00"


def _base_default_project_record() -> dict[str, Any]:
    """Return the default in-memory project row pre-seeded in the mock server."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {
        "id": MOCK_DEFAULT_PROJECT_ID,
        "canonical_id": MOCK_DEFAULT_PROJECT_ID,
        "version": 1,
        "valid_from": now,
        "valid_to": None,
        "modified_by": "mock-server",
        "deleted": False,
        "project_id": None,
        "subtable_name": "projects",
        "name": MOCK_DEFAULT_PROJECT_NAME,
        "slug": "python-client-test-project",
        "description": None,
        "tags": None,
        "notes": None,
        "url_token": None,
    }


def _base_canonical_protein_record() -> dict[str, Any]:
    """Return the default in-memory protein row for the mock canonical BRD structure."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {
        "id": MOCK_CANONICAL_PROTEIN_ID,
        "version": 1,
        "valid_from": now,
        "valid_to": None,
        "modified_by": "mock-server",
        "deleted": False,
        "project_id": None,
        "subtable_name": "proteins",
        "uniprot_accession": None,
        "file_path": MOCK_CANONICAL_PROTEIN_FILE_PATH,
        "gene_symbol": None,
        "pdb_id": None,
        "refseq_protein_id": None,
        "ensembl_protein_id": None,
        "alpha_fold_id": None,
        "fasta_sequence": None,
        "protein_name": "brd",
        "kegg_gene_id": None,
        "chembl_target_id": None,
        "binding_db_target_id": None,
        "drugbank_target_id": None,
        "pfam_id": None,
        "interpro_id": None,
        "ec_number": None,
        "ncbi_taxonomy_id": None,
        "protein_family": None,
        "ligandability_score": None,
        "protein_length": None,
    }


def _apply_search_filters(
    records: dict[str, dict[str, Any]],
    filter_dict: dict[str, Any],
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Apply search filters to an in-memory record store.

    Supports top-level equality filters (e.g. ``deleted``, ``smiles``) and
    ``props``-style operators (``in``, ``gte``, ``lte``, ``eq``).

    Args:
        records: Mapping of entity IDs to record dicts.
        filter_dict: Filter criteria from the search request body.
        limit: Maximum number of results to return.
        offset: Number of results to skip.

    Returns:
        Dict with ``data`` (list of matching records) and ``count``
        (total matches before pagination).
    """
    results = list(records.values())

    skip_keys = {"props"}
    for key, value in filter_dict.items():
        if key in skip_keys:
            continue
        # Fixture ligands use ``MOCK_DEFAULT_PROJECT_ID`` (or legacy None).
        # When the client searches with a different concrete project_id, still
        # match those rows so sync() can resolve pre-seeded BRD ligands without
        # a duplicate insert.
        if key == "project_id":
            if isinstance(value, dict) and "eq" in value:
                target = value["eq"]
            else:
                target = value
            results = [
                r
                for r in results
                if r.get("project_id") == target
                or r.get("project_id") is None
                or r.get("project_id") == MOCK_DEFAULT_PROJECT_ID
            ]
            continue
        if isinstance(value, dict):
            if "in" in value:
                allowed = (
                    set(value["in"]) if isinstance(value["in"], list) else {value["in"]}
                )
                results = [r for r in results if r.get(key) in allowed]
            elif "eq" in value:
                results = [r for r in results if r.get(key) == value["eq"]]
            elif "icontains" in value:
                needle = value["icontains"]
                if isinstance(needle, str):
                    n = needle.lower()
                    results = [
                        r
                        for r in results
                        if isinstance(r.get(key), str) and n in r.get(key, "").lower()
                    ]
            elif "gte" in value:
                results = [
                    r
                    for r in results
                    if r.get(key) is not None and r.get(key) >= value["gte"]
                ]
            elif "lte" in value:
                results = [
                    r
                    for r in results
                    if r.get(key) is not None and r.get(key) <= value["lte"]
                ]
        else:
            results = [r for r in results if r.get(key) == value]

    for prop in filter_dict.get("props", []):
        col = prop["column"]
        op = prop["op"]
        val = prop["value"]

        if op == "in":
            allowed = set(val) if isinstance(val, list) else {val}
            results = [r for r in results if r.get(col) in allowed]
        elif op == "gte":
            results = [
                r for r in results if r.get(col) is not None and r.get(col) >= val
            ]
        elif op == "lte":
            results = [
                r for r in results if r.get(col) is not None and r.get(col) <= val
            ]
        elif op == "eq":
            results = [r for r in results if r.get(col) == val]

    total = len(results)
    page = results[offset : offset + limit]

    return {"data": page, "count": total}


def _canonicalize_smiles(smiles: str) -> str:
    """Return the RDKit canonical SMILES for *smiles*, or the input unchanged.

    Args:
        smiles: Input SMILES string.

    Returns:
        Canonical SMILES, or the original string if RDKit cannot parse it.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is not None:
        return Chem.MolToSmiles(mol)
    return smiles


def _make_ligand_record(smiles: str, extra: dict[str, Any]) -> dict[str, Any]:
    """Build a new ligand record, generating a fresh ID and timestamp.

    Uses ``name`` from *extra* as the record ID when provided, otherwise
    falls back to a random UUID-based ID.  This makes mock IDs
    deterministic and easy to assert against in tests.

    Args:
        smiles: The SMILES string for the ligand.
        extra: Additional fields to merge into the record (from ``set`` or
            a batch row).

    Returns:
        Complete ligand record dict.
    """
    canonical = _canonicalize_smiles(smiles)
    now = datetime.now(timezone.utc)
    name = extra.get("name")
    ligand_id = name if name else "08" + str(uuid.uuid4()).replace("-", "").upper()[:11]
    record: dict[str, Any] = {
        "id": ligand_id,
        "version": 1,
        "valid_from": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "valid_to": None,
        "modified_by": "test-user",
        "deleted": False,
        "project_id": MOCK_DEFAULT_PROJECT_ID,
        "subtable_name": "ligands",
        "canonical_smiles": canonical,
        "smiles": smiles,
        "inchi_key": None,
        "inchi": None,
        "log_p": None,
        "structure_key": None,
    }
    record.update(extra)
    return record


def _field_value(record: dict[str, Any], key: str) -> Any:
    """Return the value for *key* from a record or its nested ``data`` dict.

    Args:
        record: A single record dict.
        key: The field name to look up.

    Returns:
        The value found in the top-level record or nested ``data``, or a
        sentinel ``_MISSING`` object when the key is absent from both.
    """
    _MISSING = object()
    val = record.get(key, _MISSING)
    if val is not _MISSING:
        return val
    data = record.get("data")
    if isinstance(data, dict):
        return data.get(key, _MISSING)
    return _MISSING


def _apply_eq_filters(
    records: list[dict[str, Any]],
    filter_dict: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply equality-style filters to a list of records.

    Supports ``{"field": {"eq": value}}``, ``{"field": {"in": [values]}}``
    style filters and ``props``-style column/op/value filters.  Values are
    compared against top-level record fields *and* nested ``data`` fields
    when present.

    Args:
        records: List of record dicts to filter.
        filter_dict: Mapping of field names to operator dicts, e.g.
            ``{"field": {"eq": value}}`` or ``{"field": {"in": [values]}}``.
            May also include a ``"props"`` key with a list of
            ``{"column": ..., "op": ..., "value": ...}`` dicts.

    Returns:
        Filtered list of records.

    Raises:
        ValueError: If a filter condition uses an unsupported operator.
    """
    _MISSING = object()
    results = list(records)
    allowed_ops = {"eq", "in"}
    skip_keys = {"props"}

    for prop in filter_dict.get("props", []):
        col = prop["column"]
        op = prop["op"]
        val = prop["value"]

        if op == "eq":
            results = [r for r in results if _field_value(r, col) == val]
        elif op == "in":
            value_set = set(val) if isinstance(val, list) else {val}
            results = [
                r
                for r in results
                if _field_value(r, col) is not _MISSING
                and _field_value(r, col) in value_set
            ]

    for key, condition in filter_dict.items():
        if key in skip_keys:
            continue

        if not isinstance(condition, dict):
            condition = {"eq": condition}

        unknown_ops = set(condition.keys()) - allowed_ops
        if unknown_ops:
            raise ValueError(
                f"Unsupported filter operator(s) for field '{key}': "
                f"{', '.join(sorted(unknown_ops))}"
            )

        if "eq" in condition:
            expected = condition["eq"]
            results = [r for r in results if _field_value(r, key) == expected]
        elif "in" in condition:
            value_set = set(condition["in"])
            results = [
                r
                for r in results
                if _field_value(r, key) is not _MISSING
                and _field_value(r, key) in value_set
            ]

    return results


def create_data_platform_router(
    *,
    ligands: dict[str, dict[str, Any]],
    proteins: dict[str, dict[str, Any]],
    projects: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
    executions: dict[str, dict[str, Any]] | None = None,
    load_fixture: Callable[[str], dict[str, Any]],
) -> APIRouter:
    """Create a router for data-platform endpoints.

    Args:
        ligands: In-memory storage for ligands.
        proteins: In-memory storage for proteins.
        projects: In-memory storage for data platform projects.
        results: In-memory list of result-explorer records.
        executions: In-memory storage for executions (keyed by executionId).
        load_fixture: Callable to load fixture data by name.

    Returns:
        APIRouter instance with data-platform routes.
    """
    router = APIRouter()

    _entity_stores: dict[str, dict[str, dict[str, Any]]] = {
        "ligands": ligands,
        "proteins": proteins,
        "projects": projects,
    }

    # Reverse index: (canonical_smiles, variant_name_tag) → ligand_id.
    _ligand_key_index: dict[tuple[str, str], str] = {
        (record["canonical_smiles"], record.get("variant_name_tag", "")): lid
        for lid, record in ligands.items()
        if record.get("canonical_smiles")
    }

    def _insert_ligand(smiles: str, extra: dict[str, Any]) -> dict[str, Any]:
        """Insert a ligand, raising 409 if the unique key already exists.

        Args:
            smiles: The SMILES string (canonicalized before keying).
            extra: Additional fields from the request payload.

        Returns:
            The newly created ligand record.

        Raises:
            HTTPException: 409 if (canonical_smiles, variant_name_tag) already exists.
        """
        from fastapi import HTTPException

        canonical = _canonicalize_smiles(smiles)
        tag = extra.get("variant_name_tag", "")
        key = (canonical, tag)
        if key in _ligand_key_index:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Key (project_scope_key, canonical_smiles, variant_name_tag)"
                    f"=(__unscoped__, {canonical}, {tag}) already exists."
                ),
            )

        record = _make_ligand_record(smiles, extra)
        ligands[record["id"]] = record
        _ligand_key_index[key] = record["id"]
        return record

    @router.get("/data-platform/health")
    def data_platform_health() -> dict[str, str]:
        """Data platform health check endpoint."""
        return {"status": "ok"}

    @router.post("/data-platform/{org_key}/ligands_with_results/search")
    async def search_ligands_with_results(
        org_key: str, request: Request
    ) -> dict[str, Any]:
        """Search ligands joined with tool results."""
        body = await request.json()
        filter_dict = body.get("filter", {})
        limit = body.get("limit", 100)
        offset = body.get("offset", 0)
        return _apply_search_filters(ligands, filter_dict, limit=limit, offset=offset)

    @router.post("/data-platform/{org_key}/result-explorer/search")
    async def search_result_explorer(org_key: str, request: Request) -> dict[str, Any]:
        """Search result-explorer records with ``{"field": {"eq": value}}`` filters.

        The local mock returns every matching row in one response (no ``limit`` /
        pagination cap) so callers such as :meth:`Docking.get_results` receive full
        pose sets (e.g. 128 bulk-docking rows) in a single request.
        """
        body = await request.json()
        filter_dict = body.get("filter", {})
        select = body.get("select")

        # Build the full pool of fixture-backed results first, then filter.
        all_results: list[dict[str, Any]] = []

        run_pf = load_fixture("function-runs/deeporigin.pocketfinder/run")
        manifest_pf = run_pf["function"]["manifestBody"]
        all_results.extend(
            {
                "id": run_pf["id"],
                "tool_key": manifest_pf["key"],
                "tool_version": run_pf["function"]["version"],
                "result_type": "pocket",
                "data": pocket,
                "compute_job_id": run_pf["id"],
            }
            for pocket in run_pf["functionOutputs"]["pockets"]
        )

        try:
            run_dk = load_fixture("function-runs/deeporigin.docking/run")
            manifest_dk = run_dk.get("function", {}).get("manifestBody", {})
            all_results.extend(
                {
                    "id": run_dk["id"],
                    "tool_key": manifest_dk.get("key", "deeporigin.docking"),
                    "tool_version": manifest_dk.get("version", "0.0.0"),
                    "result_type": "pose",
                    "data": pose,
                    "compute_job_id": run_dk["id"],
                }
                for pose in run_dk.get("functionOutputs", {}).get("poses", [])
            )
        except FileNotFoundError:
            pass

        # Records injected by function runs (same list the tools router appends to).
        all_results.extend(results)

        filtered = _apply_eq_filters(all_results, filter_dict)
        if not filtered and filter_dict.get("compute_job_id", {}).get("eq") is not None:
            # Fixture IDs won't match dynamic execution IDs; keep legacy behaviour
            # when no injected row matches.
            safe_filter = {
                k: v for k, v in filter_dict.items() if k != "compute_job_id"
            }
            filtered = _apply_eq_filters(all_results, safe_filter)

        page = filtered
        if select:
            page = [{k: v for k, v in r.items() if k in select} for r in page]

        return {"data": page, "meta": {"count": len(page)}}

    @router.post("/data-platform/{org_key}/executions/search")
    async def search_executions(org_key: str, request: Request) -> dict[str, Any]:
        """Search executions by compute_job_id with optional history."""
        body = await request.json()
        filter_dict = body.get("filter", {})
        with_history = body.get("with_history", False)

        store = executions or {}
        records = list(store.values())

        compute_job_id_filter = filter_dict.get("compute_job_id", {})
        if "eq" in compute_job_id_filter:
            target_id = compute_job_id_filter["eq"]
            records = [r for r in records if r.get("executionId") == target_id]

        response: dict[str, Any] = {"data": records, "count": len(records)}
        if with_history:
            response["with_history"] = True
        return response

    @router.post("/data-platform/{org_key}/{entity}/search")
    async def search_entity(
        org_key: str, entity: str, request: Request
    ) -> dict[str, Any]:
        """Search an entity with optional filters and pagination."""
        body = await request.json()
        filter_dict = body.get("filter", {})
        limit = body.get("limit", 100)
        offset = body.get("offset", 0)
        store = _entity_stores.get(entity, {})

        # Protein.sync() searches by uploaded file_path (hash-based or custom).
        # Always resolve to the canonical BRD fixture + stable ID when unscoped.
        if (
            entity == "proteins"
            and "file_path" in filter_dict
            and "project_id" not in filter_dict
        ):
            if MOCK_CANONICAL_PROTEIN_ID not in proteins:
                proteins[MOCK_CANONICAL_PROTEIN_ID] = copy.deepcopy(
                    _base_canonical_protein_record()
                )
            return {
                "data": [copy.deepcopy(proteins[MOCK_CANONICAL_PROTEIN_ID])],
                "count": 1,
            }

        if entity == "executions" and executions is not None:
            dp_rows: dict[str, dict[str, Any]] = {}
            for _ex_key, ex in executions.items():
                eid = ex.get("executionId") or _ex_key
                tool = ex.get("tool") or {}
                dp_rows[str(eid)] = {
                    "id": str(eid),
                    "tool_key": tool.get("key"),
                    "tool_version": tool.get("version"),
                    "status": ex.get("status"),
                    "started_at": ex.get("startedAt"),
                    "completed_at": ex.get("completedAt"),
                    "compute_job_id": ex.get("executionId"),
                    "project_id": ex.get("projectId"),
                    "deleted": False,
                }
            return _apply_search_filters(
                dp_rows, filter_dict, limit=limit, offset=offset
            )

        return _apply_search_filters(store, filter_dict, limit=limit, offset=offset)

    @router.post("/data-platform/{org_key}/projects")
    async def create_project(org_key: str, request: Request) -> dict[str, Any]:
        """Create a project row."""
        body = await request.json()
        set_data = body.get("set", {})
        returning = body.get("returning", [])

        name = set_data.get("name", "")
        slug = set_data.get("slug") or f"proj-{uuid.uuid4().hex[:12]}"
        pid = "09" + str(uuid.uuid4()).replace("-", "").upper()[:11]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        record: dict[str, Any] = {
            "id": pid,
            "canonical_id": pid,
            "version": 1,
            "valid_from": now,
            "valid_to": None,
            "modified_by": "mock-server",
            "deleted": False,
            "project_id": None,
            "subtable_name": "projects",
            "name": name,
            "slug": slug,
            "description": set_data.get("description"),
            "tags": None,
            "notes": None,
            "url_token": None,
        }
        projects[pid] = record

        response_data = record.copy()
        if returning:
            response_data = {k: v for k, v in response_data.items() if k in returning}

        return {"data": response_data, "meta": {"inserted": 1}}

    @router.post("/data-platform/{org_key}/ligands")
    async def create_ligand(org_key: str, request: Request) -> dict[str, Any]:
        """Create a new ligand (returns 409 on duplicate key)."""
        body = await request.json()
        set_data = body.get("set", {})
        returning = body.get("returning", [])

        smiles = set_data.get("smiles", "")
        record = _insert_ligand(smiles, set_data)

        response_data = record.copy()
        if returning:
            response_data = {k: v for k, v in response_data.items() if k in returning}

        return {"data": response_data, "meta": {"inserted": 1}}

    @router.post("/data-platform/{org_key}/ligands/batch/create")
    async def batch_create_ligands(org_key: str, request: Request) -> dict[str, Any]:
        """Batch-create ligands (returns 409 on duplicate key)."""
        body = await request.json()
        rows = body.get("rows", [])
        returning = body.get("returning", [])

        created: list[dict[str, Any]] = []
        for row in rows:
            smiles = row.get("smiles", "")
            record = _insert_ligand(smiles, row)

            response_data = record.copy()
            if returning:
                response_data = {
                    k: v for k, v in response_data.items() if k in returning
                }
            created.append(response_data)

        return {"data": created, "meta": {"inserted": len(created)}}

    @router.post("/data-platform/{org_key}/proteins")
    async def create_protein(org_key: str, request: Request) -> dict[str, Any]:
        """Create or update the canonical mock protein (stable ID, BRD fixture file_path).

        Every register/sync flow maps to the same platform row so tests and
        notebooks get deterministic IDs and ``tests/brd.pdb`` content.
        """
        body = await request.json()
        set_data = body.get("set", {})
        returning = body.get("returning", [])

        now = datetime.now(timezone.utc)
        now_s = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        base = proteins.get(MOCK_CANONICAL_PROTEIN_ID, _base_canonical_protein_record())
        record = copy.deepcopy(base)
        record["valid_from"] = now_s
        record.update(set_data)
        record["id"] = MOCK_CANONICAL_PROTEIN_ID
        record["file_path"] = MOCK_CANONICAL_PROTEIN_FILE_PATH
        record["deleted"] = False

        proteins[MOCK_CANONICAL_PROTEIN_ID] = record

        response_data = record.copy()
        if returning:
            response_data = {k: v for k, v in response_data.items() if k in returning}

        return {
            "data": response_data,
            "meta": {"inserted": 1},
        }

    @router.delete("/data-platform/{org_key}/{entity}/{entity_id}")
    def delete_entity(org_key: str, entity: str, entity_id: str) -> dict[str, Any]:
        """Delete an entity record by ID."""
        from fastapi import HTTPException

        store = _entity_stores.get(entity)
        if store is None:
            raise HTTPException(status_code=404, detail=f"Unknown entity '{entity}'")

        if entity_id not in store:
            raise HTTPException(
                status_code=404,
                detail=f"{entity} record '{entity_id}' not found",
            )

        del store[entity_id]

        if entity == "ligands":
            keys_to_remove = [k for k, v in _ligand_key_index.items() if v == entity_id]
            for k in keys_to_remove:
                del _ligand_key_index[k]

        return {"deleted": 1}

    @router.get("/data-platform/{org_key}/ligands/{ligand_id}")
    def get_ligand(org_key: str, ligand_id: str) -> dict[str, Any]:
        """Get a ligand by ID."""
        if ligand_id in ligands:
            return ligands[ligand_id]
        try:
            return load_fixture(f"ligand_{ligand_id}")
        except FileNotFoundError:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=404, detail=f"Ligand {ligand_id} not found"
            ) from None

    @router.get("/data-platform/{org_key}/proteins/{protein_id}")
    def get_protein(org_key: str, protein_id: str) -> dict[str, Any]:
        """Get a protein by ID."""
        if protein_id in proteins:
            return proteins[protein_id]
        try:
            return load_fixture(f"protein_{protein_id}")
        except FileNotFoundError:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=404, detail=f"Protein {protein_id} not found"
            ) from None

    @router.get("/data-platform/{org_key}/meta/models")
    def list_models(org_key: str) -> dict[str, Any]:
        """List public models."""
        return {
            "models": [
                {"tableName": "ligands", "visibility": "public"},
                {"tableName": "proteins", "visibility": "public"},
                {"tableName": "patents", "visibility": "public"},
                {"tableName": "projects", "visibility": "public"},
                {"tableName": "ui_settings", "visibility": "public"},
                {"tableName": "executions", "visibility": "public"},
                {"tableName": "execution_subjects", "visibility": "public"},
                {"tableName": "results", "visibility": "public"},
                {"tableName": "result_table_catalog", "visibility": "public"},
            ]
        }

    return router
