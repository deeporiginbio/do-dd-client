"""Tests for protein CSV import against the local mock server."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
import uuid
import zipfile

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.protein_csv_import import (
    ProteinCsvImport,
    build_protein_csv_import_inputs,
    protein_csv_mapper,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.constants import (
    IMPORT_DATASET_PROTEINS_DATABASE_KEY,
    IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
)

_SERVED_ROUTE_INPUT_KEYS = ("rows", "sync", "result_lane")
_SERVED_ROUTE_INPUT_PREFIXES = ("process_", "register_")
_WAIT_TIMEOUT_SECONDS = 30.0
_PROTEIN_CSV_COLUMNS = ["protein_name", "fasta_sequence", "pdb_id", "file_path"]
_PROTEIN_CSV_MAPPER = [
    {"field": column, "json-path": f"proteins.{column}"}
    for column in _PROTEIN_CSV_COLUMNS
]


def _write_protein_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    """Write a protein CSV whose columns are platform protein fields.

    Args:
        path: Destination file.
        rows: Row dicts keyed by the names in ``_PROTEIN_CSV_COLUMNS``.

    Returns:
        Path: ``path``, for chaining.
    """
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_PROTEIN_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _assert_routes_to_workflow(inputs: dict[str, Any]) -> None:
    """Assert the inputs carry none of the keys that force the served route.

    Args:
        inputs: import-dataset ``inputs`` object.
    """
    for key in inputs:
        assert key not in _SERVED_ROUTE_INPUT_KEYS, key
        assert not key.startswith(_SERVED_ROUTE_INPUT_PREFIXES), key


def test_protein_csv_mapper_maps_each_column_to_same_named_field(
    tmp_path: Path,
) -> None:
    """Each header column becomes ``proteins.<column>``, in order, trimmed."""
    path = tmp_path / "proteins.csv"
    path.write_text("protein_name, fasta_sequence,gene_symbol\nkinase,MKV,ABL1\n")

    assert protein_csv_mapper(path) == [
        {"field": "protein_name", "json-path": "proteins.protein_name"},
        {"field": "fasta_sequence", "json-path": "proteins.fasta_sequence"},
        {"field": "gene_symbol", "json-path": "proteins.gene_symbol"},
    ]


def test_protein_csv_mapper_rejects_csv_without_header(tmp_path: Path) -> None:
    """An empty CSV has no columns to map and raises before any upload."""
    path = tmp_path / "empty.csv"
    path.write_text("")

    with pytest.raises(DeepOriginException, match="no header row"):
        protein_csv_mapper(path)


def test_protein_csv_mapper_rejects_csv_without_identity_column(
    tmp_path: Path,
) -> None:
    """A header with no identifying field raises and names the columns to rename."""
    path = tmp_path / "proteins.csv"
    path.write_text("name,sequence\nkinase,MKV\n")

    with pytest.raises(DeepOriginException, match="needs at least one of") as excinfo:
        protein_csv_mapper(path)
    message = str(excinfo.value)
    assert "'sequence' to 'fasta_sequence'" in message
    assert "'name' to 'protein_name'" in message


def test_build_protein_csv_import_inputs_without_zip() -> None:
    """Inputs carry the CSV, mapper and dataset identity, and nothing served."""
    inputs = build_protein_csv_import_inputs(
        csv_path="imports/staging/a.csv",
        mapper=_PROTEIN_CSV_MAPPER,
    )

    assert inputs == {
        "csv_path": "imports/staging/a.csv",
        "mapper": _PROTEIN_CSV_MAPPER,
        "database_key": IMPORT_DATASET_PROTEINS_DATABASE_KEY,
        "database_version": IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
    }
    _assert_routes_to_workflow(inputs)


def test_build_protein_csv_import_inputs_with_zip() -> None:
    """A staged zip path is passed as ``protein_zip_path``."""
    inputs = build_protein_csv_import_inputs(
        csv_path="imports/staging/a.csv",
        mapper=_PROTEIN_CSV_MAPPER,
        protein_zip_path="imports/staging/b.zip",
    )

    assert inputs["protein_zip_path"] == "imports/staging/b.zip"
    _assert_routes_to_workflow(inputs)


def test_protein_csv_import_start_returns_handle_without_waiting(
    client: DeepOriginClient,
    tmp_path: Path,
) -> None:
    """Submit returns a handle; the run is a hidden workflow import."""
    csv_path = _write_protein_csv(
        tmp_path / "proteins.csv",
        [{"protein_name": f"p-{uuid.uuid4().hex[:8]}", "fasta_sequence": "MKV"}],
    )

    handle = ProteinCsvImport.start(csv_path, client=client)

    assert isinstance(handle, ProteinCsvImport)
    assert handle.project_id == client.project_id
    dto = client.executions.get(handle.execution_id)
    inputs = dto["userInputs"]
    assert inputs["mapper"] == _PROTEIN_CSV_MAPPER
    assert inputs["database_key"] == IMPORT_DATASET_PROTEINS_DATABASE_KEY
    assert inputs["database_version"] == IMPORT_DATASET_PROTEINS_DATABASE_VERSION
    assert inputs["csv_path"].endswith(".csv")
    assert "protein_zip_path" not in inputs
    _assert_routes_to_workflow(inputs)


def test_protein_csv_import_start_stages_structures_zip(
    client: DeepOriginClient,
    tmp_path: Path,
) -> None:
    """The structures zip is uploaded and passed as ``protein_zip_path``."""
    zip_path = tmp_path / "structures.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(BRD_DATA_DIR / "brd.pdb", arcname="brd.pdb")
    csv_path = _write_protein_csv(
        tmp_path / "proteins.csv",
        [{"protein_name": f"p-{uuid.uuid4().hex[:8]}", "file_path": "brd.pdb"}],
    )

    handle = ProteinCsvImport.start(csv_path, protein_zip_path=zip_path, client=client)

    inputs = client.executions.get(handle.execution_id)["userInputs"]
    assert inputs["protein_zip_path"].endswith(".zip")
    assert inputs["protein_zip_path"] != inputs["csv_path"]


def test_protein_csv_import_wait_returns_project_proteins(
    client: DeepOriginClient,
    tmp_path: Path,
) -> None:
    """``wait()`` resolves on the SSE wake and returns the imported proteins."""
    suffix = uuid.uuid4().hex[:8]
    rows = [
        {"protein_name": f"kinase-{suffix}", "fasta_sequence": f"MKVL{suffix.upper()}"},
        {
            "protein_name": f"protease-{suffix}",
            "fasta_sequence": f"MSTA{suffix.upper()}",
        },
    ]
    csv_path = _write_protein_csv(tmp_path / "proteins.csv", rows)

    proteins = ProteinCsvImport.start(csv_path, client=client).wait(
        timeout=_WAIT_TIMEOUT_SECONDS
    )

    by_name = {p.name: p for p in proteins}
    for row in rows:
        assert row["protein_name"] in by_name
        assert by_name[row["protein_name"]].id
        assert by_name[row["protein_name"]].project_id == client.project_id
        assert by_name[row["protein_name"]].structure is None

    again = ProteinCsvImport.start(csv_path, client=client).wait(
        timeout=_WAIT_TIMEOUT_SECONDS
    )
    names = [p.name for p in again]
    for row in rows:
        assert names.count(row["protein_name"]) == 1


def test_protein_csv_import_wait_raises_on_failed_import(
    client: DeepOriginClient,
    tmp_path: Path,
) -> None:
    """A failed import raises with its status and reason."""
    csv_path = _write_protein_csv(tmp_path / "empty.csv", [])

    handle = ProteinCsvImport.start(csv_path, client=client)

    with pytest.raises(DeepOriginException, match="Failed") as excinfo:
        handle.wait(timeout=_WAIT_TIMEOUT_SECONDS)
    assert "No importable protein rows" in str(excinfo.value)


def test_protein_csv_import_wait_follows_search_cursor(
    client: DeepOriginClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With one protein per page, ``wait()`` reads every page exactly once."""
    monkeypatch.setattr(
        "deeporigin.drug_discovery.protein_csv_import.PROTEIN_SEARCH_PAGE_SIZE", 1
    )
    search = client.entities.search_proteins
    cursors: list[str | None] = []

    def recording_search(**kwargs: Any) -> dict[str, Any]:
        cursors.append(kwargs.get("cursor"))
        return search(**kwargs)

    monkeypatch.setattr(client.entities, "search_proteins", recording_search)
    suffix = uuid.uuid4().hex[:8]
    rows = [
        {"protein_name": f"page-{i}-{suffix}", "fasta_sequence": f"MK{i}{suffix}"}
        for i in range(3)
    ]
    csv_path = _write_protein_csv(tmp_path / "proteins.csv", rows)

    proteins = ProteinCsvImport.start(csv_path, client=client).wait(
        timeout=_WAIT_TIMEOUT_SECONDS
    )

    ids = [p.id for p in proteins]
    assert len(ids) == len(set(ids))
    assert len(cursors) == len(proteins) >= len(rows)
    assert cursors[0] is None
    assert len(set(cursors)) == len(cursors)
    names = {p.name for p in proteins}
    for row in rows:
        assert row["protein_name"] in names


def test_protein_csv_import_accepts_pdb_id_only_rows_with_padded_header(
    client: DeepOriginClient,
    tmp_path: Path,
) -> None:
    """A row identified only by ``pdb_id`` is imported; header padding is trimmed."""
    name = f"pdb-only-{uuid.uuid4().hex[:8]}"
    csv_path = tmp_path / "proteins.csv"
    csv_path.write_text(f"protein_name, pdb_id\n{name},1EBY\n")

    proteins = ProteinCsvImport.start(csv_path, client=client).wait(
        timeout=_WAIT_TIMEOUT_SECONDS
    )

    assert name in {p.name for p in proteins}
