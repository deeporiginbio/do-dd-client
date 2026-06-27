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

_FIELD_MISSING = object()


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
        The value found in the top-level record or nested ``data``, or
        ``_FIELD_MISSING`` when the key is absent from both.
    """
    val = record.get(key, _FIELD_MISSING)
    if val is not _FIELD_MISSING:
        return val
    data = record.get("data")
    if isinstance(data, dict):
        return data.get(key, _FIELD_MISSING)
    return _FIELD_MISSING


def _normalize_result_type_value(value: Any) -> Any:
    """Normalize result-type filter operands for case-insensitive matching."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


def _numeric_value(value: Any) -> float | None:
    """Coerce a field value to float when possible."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _validate_filter_condition(key: str, condition: dict[str, Any]) -> None:
    """Raise ValueError when a filter condition has invalid operator combinations."""
    membership_ops = {"eq", "in"} & set(condition.keys())
    comparison_ops = {"lt", "lte", "gt", "gte"} & set(condition.keys())

    if not membership_ops and not comparison_ops:
        raise ValueError(f"Filter condition for field '{key}' must include an operator")

    if membership_ops and comparison_ops:
        raise ValueError(
            f"Filter condition for field '{key}' cannot mix membership "
            f"operators with comparison operators"
        )

    if len(membership_ops) > 1:
        raise ValueError(
            f"Filter condition for field '{key}' cannot include both "
            f"'eq' and 'in' operators"
        )


def _matches_condition(
    record: dict[str, Any],
    key: str,
    condition: dict[str, Any],
) -> bool:
    """Return whether *record* satisfies a single-field filter condition."""
    raw_value = _field_value(record, key)
    if raw_value is _FIELD_MISSING:
        return False

    if key == "result_type":
        actual = _normalize_result_type_value(raw_value)
    else:
        actual = raw_value

    if not condition:
        return False

    if "eq" in condition:
        expected = condition["eq"]
        if key == "result_type":
            expected = _normalize_result_type_value(expected)
        return actual == expected

    if "in" in condition:
        allowed = condition["in"]
        if not isinstance(allowed, list):
            allowed = [allowed]
        if key == "result_type":
            allowed_set = {_normalize_result_type_value(item) for item in allowed}
            return actual in allowed_set
        return actual in set(allowed)

    comparison_ops = {
        "lt": lambda actual_num, bound: actual_num < bound,
        "lte": lambda actual_num, bound: actual_num <= bound,
        "gt": lambda actual_num, bound: actual_num > bound,
        "gte": lambda actual_num, bound: actual_num >= bound,
    }
    actual_num = _numeric_value(actual)
    saw_comparison = False
    for op, compare in comparison_ops.items():
        if op not in condition:
            continue
        saw_comparison = True
        bound_num = _numeric_value(condition[op])
        if actual_num is None or bound_num is None:
            return False
        if not compare(actual_num, bound_num):
            return False

    return saw_comparison


def _sort_key_component(value: Any) -> tuple[int, Any]:
    """Build a sort key that avoids mixed-type comparisons."""
    if value is _FIELD_MISSING or value is None:
        return (2, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, float(value))
    if isinstance(value, str):
        return (1, value)
    if isinstance(value, (dict, list)):
        return (1, str(value))
    return (1, str(value))


def _apply_sort(
    records: list[dict[str, Any]],
    sort_dict: dict[str, Any],
) -> list[dict[str, Any]]:
    """Sort records by one or more fields (top-level or nested ``data``)."""
    if not sort_dict:
        return records

    sorted_records = list(records)
    for field, direction in reversed(list(sort_dict.items())):
        reverse = isinstance(direction, str) and direction.lower() == "desc"
        sorted_records.sort(
            key=lambda record: _sort_key_component(_field_value(record, field)),
            reverse=reverse,
        )
    return sorted_records


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
    results = list(records)
    allowed_ops = {"eq", "in", "lt", "lte", "gt", "gte"}
    skip_keys = {"props"}

    for prop in filter_dict.get("props", []):
        col = prop["column"]
        op = prop["op"]
        val = prop["value"]

        if op not in allowed_ops:
            raise ValueError(
                f"Unsupported filter operator(s) for props column '{col}': {op}"
            )

        if op in {"eq", "in"}:
            condition = {op: val}
            results = [r for r in results if _matches_condition(r, col, condition)]
        elif op in {"lt", "lte", "gt", "gte"}:
            condition = {op: val}
            results = [r for r in results if _matches_condition(r, col, condition)]

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

        _validate_filter_condition(key, condition)
        results = [r for r in results if _matches_condition(r, key, condition)]

    return results


def create_data_platform_router(
    *,
    ligands: dict[str, dict[str, Any]],
    proteins: dict[str, dict[str, Any]],
    projects: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
    executions: dict[str, dict[str, Any]] | None = None,
    datasets: dict[str, dict[str, Any]] | None = None,
    user_logs: dict[str, dict[str, Any]] | None = None,
    load_fixture: Callable[[str], dict[str, Any]],
) -> APIRouter:
    """Create a router for data-platform endpoints.

    Args:
        ligands: In-memory storage for ligands.
        proteins: In-memory storage for proteins.
        projects: In-memory storage for data platform projects.
        results: In-memory list of result-explorer records.
        executions: In-memory storage for executions (keyed by executionId).
        datasets: In-memory storage for datasets (keyed by dataset ID).
        user_logs: In-memory storage for user_logs rows (keyed by row id).
        load_fixture: Callable to load fixture data by name.

    Returns:
        APIRouter instance with data-platform routes.
    """
    router = APIRouter()

    _datasets: dict[str, dict[str, Any]] = datasets if datasets is not None else {}

    _user_logs_store = user_logs if user_logs is not None else {}

    _entity_stores: dict[str, dict[str, dict[str, Any]]] = {
        "ligands": ligands,
        "proteins": proteins,
        "projects": projects,
        "user_logs": _user_logs_store,
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

    def _patch_entity_record(
        entity: str,
        entity_id: str,
        set_data: dict[str, Any],
        returning: list[str],
    ) -> dict[str, Any]:
        """Apply an immutable-style PATCH to an in-memory entity record.

        Args:
            entity: Entity table name (e.g. ``ligands``, ``proteins``).
            entity_id: ID of the row to update.
            set_data: Fields to merge into the record.
            returning: Optional field allow-list for the response row.

        Returns:
            Updated record (filtered by ``returning`` when provided).

        Raises:
            HTTPException: 404 when the entity or record is unknown.
        """
        from fastapi import HTTPException

        store = _entity_stores.get(entity)
        if store is None:
            raise HTTPException(status_code=404, detail=f"Unknown entity '{entity}'")

        if entity_id not in store:
            raise HTTPException(
                status_code=404,
                detail=f"{entity} record '{entity_id}' not found",
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        prev = store[entity_id]
        record = copy.deepcopy(prev)
        patch_data = dict(set_data)

        if entity == "ligands" and (
            "smiles" in patch_data or "variant_name_tag" in patch_data
        ):
            old_key = (
                prev.get("canonical_smiles"),
                prev.get("variant_name_tag", ""),
            )
            new_smiles = patch_data.get("smiles", prev.get("smiles"))
            new_tag = patch_data.get(
                "variant_name_tag", prev.get("variant_name_tag", "")
            )
            if "smiles" in patch_data and new_smiles is not None:
                patch_data["canonical_smiles"] = _canonicalize_smiles(new_smiles)
            new_canonical = patch_data.get(
                "canonical_smiles", prev.get("canonical_smiles")
            )
            new_key = (new_canonical, new_tag)
            if new_key != old_key:
                if _ligand_key_index.get(old_key) == entity_id:
                    del _ligand_key_index[old_key]
                conflict_id = _ligand_key_index.get(new_key)
                if conflict_id is not None and conflict_id != entity_id:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Key (project_scope_key, canonical_smiles, variant_name_tag)"
                            f"=(__unscoped__, {new_canonical}, {new_tag}) already exists."
                        ),
                    )
                _ligand_key_index[new_key] = entity_id

        record.update(patch_data)
        record["version"] = prev.get("version", 1) + 1
        record["valid_from"] = now
        record["valid_to"] = None
        record["modified_by"] = "mock-server"
        store[entity_id] = record

        response_data = record.copy()
        if returning:
            response_data = {k: v for k, v in response_data.items() if k in returning}

        return response_data

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

        Supports ``offset``/``limit`` pagination (including ``meta.hasMore`` for
        offset pages). When neither is sent, returns every matching row in one
        response so legacy callers receive full pose sets in a single request.
        """
        body = await request.json()
        filter_dict = body.get("filter", {})
        select = body.get("select")
        sort_dict = body.get("sort", {})

        measured_at_pocket = "2026-01-02T12:00:00.000Z"
        measured_at_pose = "2026-01-01T12:00:00.000Z"
        measured_at_prepared = "2026-01-03T12:00:00.000Z"

        # Build the full pool of fixture-backed results first, then filter.
        all_results: list[dict[str, Any]] = []

        def _job_outputs(fixture: dict[str, Any]) -> Any:
            """Read ``jobOutputs`` from a fixture, falling back to legacy ``functionOutputs``."""
            return fixture.get("jobOutputs", fixture.get("functionOutputs"))

        def _tool_block(fixture: dict[str, Any]) -> dict[str, Any]:
            """Return the canonical ``{key, version}`` for a tool fixture.

            Prefers the new ``tool`` block; falls back to the legacy ``function``
            block during the transition.
            """
            tool = fixture.get("tool")
            if isinstance(tool, dict):
                return {
                    "key": tool.get("key", ""),
                    "version": tool.get("version", "0.0.0"),
                }
            func = fixture.get("function") or {}
            manifest = func.get("manifestBody") or {}
            return {
                "key": manifest.get("key") or func.get("key", ""),
                "version": (func.get("version") or manifest.get("version") or "0.0.0"),
            }

        run_pf = load_fixture("tool-runs/deeporigin.pocketfinder/run")
        pf_tool = _tool_block(run_pf)
        pf_outputs = _job_outputs(run_pf) or {}
        all_results.extend(
            {
                "id": run_pf.get("id") or run_pf.get("executionId"),
                "tool_key": pf_tool["key"],
                "tool_version": pf_tool["version"],
                "result_type": "pocket",
                "measured_at": measured_at_pocket,
                "data": pocket,
                "compute_job_id": run_pf.get("id") or run_pf.get("executionId"),
            }
            for pocket in pf_outputs.get("pockets", [])
        )

        try:
            run_dk = load_fixture("tool-runs/deeporigin.docking/run")
            dk_tool = _tool_block(run_dk)
            dk_outputs = _job_outputs(run_dk) or {}
            all_results.extend(
                {
                    "id": run_dk.get("id") or run_dk.get("executionId"),
                    "tool_key": dk_tool["key"] or "deeporigin.docking",
                    "tool_version": dk_tool["version"],
                    "result_type": "pose",
                    "measured_at": measured_at_pose,
                    "data": pose,
                    "compute_job_id": run_dk.get("id") or run_dk.get("executionId"),
                }
                for pose in dk_outputs.get("poses", [])
            )
        except FileNotFoundError:
            pass

        try:
            run_sp = load_fixture("tool-runs/deeporigin.system-prep/run")
            sp_tool = _tool_block(run_sp)
            sp_outputs = _job_outputs(run_sp) or {}
            system_out = sp_outputs.get("system")
            if isinstance(system_out, dict):
                all_results.append(
                    {
                        "id": run_sp.get("id") or run_sp.get("executionId"),
                        "tool_key": sp_tool["key"] or "deeporigin.system-prep",
                        "tool_version": sp_tool["version"],
                        "result_type": "preparedsystem",
                        "measured_at": measured_at_prepared,
                        "data": system_out,
                        "compute_job_id": run_sp.get("id") or run_sp.get("executionId"),
                    }
                )
        except FileNotFoundError:
            pass

        # Records injected by tool executions (same list the tools router appends to).
        all_results.extend(results)

        filtered = _apply_eq_filters(all_results, filter_dict)
        if not filtered and filter_dict.get("compute_job_id", {}).get("eq") is not None:
            # Fixture IDs won't match dynamic execution IDs; keep legacy behaviour
            # when no injected row matches.
            safe_filter = {
                k: v for k, v in filter_dict.items() if k != "compute_job_id"
            }
            filtered = _apply_eq_filters(all_results, safe_filter)

        if sort_dict:
            filtered = _apply_sort(filtered, sort_dict)

        offset = body.get("offset", 0)
        limit = body.get("limit")
        cursor_raw = body.get("cursor")
        total = len(filtered)

        if "offset" in body:
            page_size = limit if limit is not None else total
            page = filtered[offset : offset + page_size]
            meta = {
                "count": len(page),
                "hasMore": offset + len(page) < total,
            }
        elif cursor_raw is not None or limit is not None:
            start = int(cursor_raw) if cursor_raw else 0
            page_size = limit if limit is not None else total
            page = filtered[start : start + page_size]
            meta = {"count": len(page)}
            if start + len(page) < total:
                meta["nextCursor"] = str(start + len(page))
        else:
            page = filtered
            meta = {"count": len(page)}

        if select:
            page = [{k: v for k, v in r.items() if k in select} for r in page]

        return {"data": page, "meta": meta}

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

    # ---- Admin dataset endpoints (registered before catch-all entity routes) ----

    @router.post("/data-platform/admin/datasets/search")
    async def admin_search_datasets(request: Request) -> dict[str, Any]:
        """Search datasets (admin)."""
        body = await request.json()
        filter_dict = body.get("filter", {})
        limit = body.get("limit", 100)
        offset = body.get("offset", 0)
        search_term = body.get("search")

        results_list = list(_datasets.values())

        if search_term:
            term = search_term.lower()
            results_list = [
                r
                for r in results_list
                if term in (r.get("name") or "").lower()
                or term in (r.get("summary") or "").lower()
                or term in (r.get("description") or "").lower()
            ]

        for key, value in filter_dict.items():
            if isinstance(value, dict) and "in" in value:
                allowed = value["in"]

                def _record_tag_values(record: dict[str, Any], field: str) -> list[Any]:
                    raw = record.get(field)
                    if isinstance(raw, list):
                        return raw
                    if isinstance(raw, dict):
                        dataset_tags = raw.get("dataset_tags")
                        if isinstance(dataset_tags, list):
                            return dataset_tags
                    return []

                results_list = [
                    r
                    for r in results_list
                    if all(t in _record_tag_values(r, key) for t in allowed)
                ]
            elif isinstance(value, dict) and "eq" in value:
                results_list = [r for r in results_list if r.get(key) == value["eq"]]
            elif not isinstance(value, dict):
                results_list = [r for r in results_list if r.get(key) == value]

        total = len(results_list)

        if body.get("with_total_count"):
            return {"data": [], "meta": {"count": 0, "limit": 0, "total_count": total}}

        page = results_list[offset : offset + limit]
        return {"data": page, "meta": {"count": total, "limit": limit}}

    @router.get("/data-platform/admin/datasets/{dataset_id}")
    def admin_get_dataset(dataset_id: str) -> dict[str, Any]:
        """Get a dataset by ID (admin)."""
        from fastapi import HTTPException

        if dataset_id not in _datasets:
            raise HTTPException(
                status_code=404, detail=f"Dataset {dataset_id} not found"
            )
        return {"data": _datasets[dataset_id]}

    def _flatten_dataset_admin_set(set_data: dict[str, Any]) -> dict[str, Any]:
        """Expand admin bundle ``set`` into flat mock row fields."""
        if "datasetMeta" not in set_data:
            return set_data
        meta = set_data.get("datasetMeta") or {}
        flat: dict[str, Any] = {
            "name": meta.get("name"),
            "file_path": set_data.get("file_path"),
            "dataset_key": set_data.get("dataset_key"),
            "dataset_version": set_data.get("dataset_version"),
            "description": meta.get("description"),
            "source_url": meta.get("source_url"),
            "source_name": meta.get("source_label"),
            "compound_count": meta.get("compound_count"),
            "file_size_bytes": meta.get("file_size_bytes"),
            "tags": meta.get("tags"),
            "sample_rows": meta.get("datasetPreview"),
            "changelog": meta.get("changelog"),
            "dataset_schema": set_data.get("datasetSchema"),
        }
        return {k: v for k, v in flat.items() if v is not None}

    @router.post("/data-platform/admin/datasets")
    async def admin_create_dataset(request: Request) -> dict[str, Any]:
        """Create a dataset (admin)."""
        body = await request.json()
        set_data = _flatten_dataset_admin_set(body.get("set", {}))
        did = "ds-" + str(uuid.uuid4()).replace("-", "")[:12]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        record: dict[str, Any] = {
            "id": did,
            "version": 1,
            "valid_from": now,
            "valid_to": None,
            "modified_by": "mock-server",
            "deleted": False,
            **set_data,
        }
        _datasets[did] = record
        return {"data": record, "meta": {"inserted": 1}}

    @router.patch("/data-platform/admin/datasets/{dataset_id}")
    async def admin_update_dataset(dataset_id: str, request: Request) -> dict[str, Any]:
        """Update a dataset (admin)."""
        from fastapi import HTTPException

        if dataset_id not in _datasets:
            raise HTTPException(
                status_code=404, detail=f"Dataset {dataset_id} not found"
            )
        body = await request.json()
        set_data = _flatten_dataset_admin_set(body.get("set", {}))
        _datasets[dataset_id].update(set_data)
        return {"data": _datasets[dataset_id], "meta": {"affected": 1}}

    @router.post("/data-platform/admin/datasets/{dataset_id}/import")
    async def admin_trigger_import(dataset_id: str, request: Request) -> dict[str, Any]:
        """Trigger a dataset import (admin)."""
        from fastapi import HTTPException

        if dataset_id not in _datasets:
            raise HTTPException(
                status_code=404, detail=f"Dataset {dataset_id} not found"
            )
        body = await request.json()
        if not body.get("orgKey") or not body.get("clusterId"):
            raise HTTPException(
                status_code=400, detail="orgKey and clusterId are required"
            )
        return {"executionId": f"exec-{uuid.uuid4().hex[:12]}"}

    # ---- Generic entity search (catch-all, must come after static routes) ----

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
            "tags": set_data.get("tags"),
            "notes": set_data.get("notes"),
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

    @router.patch("/data-platform/{org_key}/{entity}/{entity_id}")
    async def update_entity(
        org_key: str, entity: str, entity_id: str, request: Request
    ) -> dict[str, Any]:
        """Update a single entity record (immutable version bump)."""
        from fastapi import HTTPException

        body = await request.json()
        set_data = body.get("set", {})
        returning = body.get("returning", [])
        if not set_data:
            raise HTTPException(
                status_code=400, detail="set must contain at least one field"
            )

        row = _patch_entity_record(entity, entity_id, set_data, returning)
        return {"data": [row], "meta": {"affected": 1}}

    @router.patch("/data-platform/{org_key}/{entity}/batch/update")
    async def batch_update_entity(
        org_key: str, entity: str, request: Request
    ) -> dict[str, Any]:
        """Batch-update entity records (immutable version bump per row)."""
        from fastapi import HTTPException

        body = await request.json()
        updates = body.get("updates", [])
        returning = body.get("returning", [])
        if not updates:
            raise HTTPException(
                status_code=400, detail="'updates' must be a non-empty array"
            )

        rows: list[dict[str, Any]] = []
        for entry in updates:
            entry_set = entry.get("set", {})
            if not entry_set:
                raise HTTPException(
                    status_code=400,
                    detail="each update must include a non-empty 'set' object",
                )
            rows.append(_patch_entity_record(entity, entry["id"], entry_set, returning))

        return {"data": rows, "meta": {"affected": len(rows)}}

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
