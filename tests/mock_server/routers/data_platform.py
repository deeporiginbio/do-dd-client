"""Data-platform routes for the mock server."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Request


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


def _make_ligand_record(smiles: str, extra: dict[str, Any]) -> dict[str, Any]:
    """Build a new ligand record, generating a fresh ID and timestamp.

    Args:
        smiles: The SMILES string for the ligand.
        extra: Additional fields to merge into the record (from ``set`` or
            a batch row).

    Returns:
        Complete ligand record dict.
    """
    now = datetime.now(timezone.utc)
    ligand_id = "08" + str(uuid.uuid4()).replace("-", "").upper()[:11]
    record: dict[str, Any] = {
        "id": ligand_id,
        "version": 1,
        "valid_from": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "valid_to": None,
        "modified_by": "test-user",
        "deleted": False,
        "project_id": None,
        "subtable_name": "ligands",
        "canonical_smiles": smiles,
        "smiles": smiles,
        "inchi_key": None,
        "inchi": None,
        "log_p": None,
        "structure_key": None,
    }
    record.update(extra)
    return record


def create_data_platform_router(
    *,
    ligands: dict[str, dict[str, Any]],
    proteins: dict[str, dict[str, Any]],
    load_fixture: Callable[[str], dict[str, Any]],
) -> APIRouter:
    """Create a router for data-platform endpoints.

    Args:
        ligands: In-memory storage for ligands.
        proteins: In-memory storage for proteins.
        load_fixture: Callable to load fixture data by name.

    Returns:
        APIRouter instance with data-platform routes.
    """
    router = APIRouter()

    _entity_stores: dict[str, dict[str, dict[str, Any]]] = {
        "ligands": ligands,
        "proteins": proteins,
    }

    # Reverse index: canonical_smiles → ligand_id (enforces uniqueness).
    _smiles_index: dict[str, str] = {
        record["canonical_smiles"]: lid
        for lid, record in ligands.items()
        if record.get("canonical_smiles")
    }

    def _upsert_ligand(smiles: str, extra: dict[str, Any]) -> dict[str, Any]:
        """Insert a ligand or return the existing one if canonical_smiles matches.

        Args:
            smiles: The SMILES string (used as canonical_smiles).
            extra: Additional fields from the request payload.

        Returns:
            The stored ligand record (full, unfiltered).
        """
        existing_id = _smiles_index.get(smiles)
        if existing_id is not None and existing_id in ligands:
            existing = ligands[existing_id]
            existing.update(extra)
            return existing

        record = _make_ligand_record(smiles, extra)
        ligands[record["id"]] = record
        _smiles_index[smiles] = record["id"]
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
        return _apply_search_filters(store, filter_dict, limit=limit, offset=offset)

    @router.post("/data-platform/{org_key}/projects/search")
    async def list_projects(org_key: str, request: Request) -> dict[str, Any]:
        """List projects."""
        await request.json()
        return {
            "data": [],
            "count": 0,
        }

    @router.post("/data-platform/{org_key}/ligands")
    async def create_ligand(org_key: str, request: Request) -> dict[str, Any]:
        """Create a new ligand (upserts on canonical_smiles)."""
        body = await request.json()
        set_data = body.get("set", {})
        returning = body.get("returning", [])

        smiles = set_data.get("smiles", "")
        record = _upsert_ligand(smiles, set_data)

        response_data = record.copy()
        if returning:
            response_data = {k: v for k, v in response_data.items() if k in returning}

        return {"data": response_data, "meta": {"inserted": 1}}

    @router.post("/data-platform/{org_key}/ligands/batch/create")
    async def batch_create_ligands(org_key: str, request: Request) -> dict[str, Any]:
        """Batch-create ligands (upserts on canonical_smiles)."""
        body = await request.json()
        rows = body.get("rows", [])
        returning = body.get("returning", [])

        created: list[dict[str, Any]] = []
        for row in rows:
            smiles = row.get("smiles", "")
            record = _upsert_ligand(smiles, row)

            response_data = record.copy()
            if returning:
                response_data = {
                    k: v for k, v in response_data.items() if k in returning
                }
            created.append(response_data)

        return {"data": created, "meta": {"inserted": len(created)}}

    # Reverse index: file_path → protein_id (enforces uniqueness).
    _file_path_index: dict[str, str] = {
        record["file_path"]: pid
        for pid, record in proteins.items()
        if record.get("file_path")
    }

    def _upsert_protein(set_data: dict[str, Any]) -> dict[str, Any]:
        """Insert a protein or return the existing one if file_path matches.

        Args:
            set_data: Fields from the request payload.

        Returns:
            The stored protein record (full, unfiltered).
        """
        fp = set_data.get("file_path", "")
        existing_id = _file_path_index.get(fp)
        if existing_id is not None and existing_id in proteins:
            existing = proteins[existing_id]
            existing.update(set_data)
            return existing

        now = datetime.now(timezone.utc)
        protein_id = "08" + str(uuid.uuid4()).replace("-", "").upper()[:11]

        record: dict[str, Any] = {
            "id": protein_id,
            "version": 1,
            "valid_from": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "valid_to": None,
            "modified_by": "6b96d8f8-0f55-474c-a86c-e09651ba4b20",
            "deleted": False,
            "project_id": None,
            "subtable_name": "proteins",
            "uniprot_accession": None,
            "file_path": fp,
            "gene_symbol": None,
            "pdb_id": None,
            "refseq_protein_id": None,
            "ensembl_protein_id": None,
            "alpha_fold_id": None,
            "fasta_sequence": None,
            "protein_name": None,
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
        record.update(set_data)

        proteins[protein_id] = record
        if fp:
            _file_path_index[fp] = protein_id
        return record

    @router.post("/data-platform/{org_key}/proteins")
    async def create_protein(org_key: str, request: Request) -> dict[str, Any]:
        """Create a new protein (upserts on file_path)."""
        body = await request.json()
        set_data = body.get("set", {})
        returning = body.get("returning", [])

        record = _upsert_protein(set_data)

        response_data = record.copy()
        if returning:
            response_data = {k: v for k, v in response_data.items() if k in returning}

        return {
            "data": response_data,
            "meta": {"inserted": 1},
        }

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
