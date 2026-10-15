"""Protein folder import against import-dataset: a zip of structures plus a CSV."""

import csv
import hashlib
from pathlib import Path
import uuid
import zipfile

import pytest

from deeporigin import projects
from deeporigin.drug_discovery import BRD_DATA_DIR, import_dataset_sync
from deeporigin.drug_discovery.import_dataset_sync import (
    run_import_dataset_workflow,
    stage_local_file,
)
from deeporigin.drug_discovery.structures.protein_files import (
    build_protein_bundle,
    find_structure_files,
)
from deeporigin.exceptions import DeepOriginException
from deeporigin.utils.constants import (
    IMPORT_DATASET_PROTEINS_DATABASE_KEY,
    IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
    PROTEIN_FOLDER_CSV_MAPPER,
    PROTEIN_FOLDER_IMPORT_TOOL_VERSION,
)
from tests.mock_server.constants import MOCK_SSE_DISABLED_PROJECT_ID

PROTEIN_DIRS = Path(__file__).parent / "fixtures" / "protein_dirs"
_BRD_LINES = (BRD_DATA_DIR / "brd.pdb").read_text().splitlines(keepends=True)


def _structure(path: Path) -> Path:
    """Write a structure with unique content, so it is new to the project."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"REMARK   1 {uuid.uuid4().hex}\n" + "".join(_BRD_LINES[:40]))
    return path


def _canonical_path(path: Path) -> str:
    """Return where import-dataset stores a structure: by content hash."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"entities/proteins/{digest}{path.suffix.lower()}"


def _import(client, zip_path: Path, csv_path: Path) -> dict:
    """Stage the bundle, start the workflow and wait for ingestion."""
    inputs = {
        "csv_path": stage_local_file(client, csv_path),
        "protein_zip_path": stage_local_file(client, zip_path),
        "mapper": PROTEIN_FOLDER_CSV_MAPPER,
        "database_key": IMPORT_DATASET_PROTEINS_DATABASE_KEY,
        "database_version": IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
    }
    dto = run_import_dataset_workflow(
        inputs=inputs, project_id=client.project_id, client=client
    )
    return client.executions.wait_for_ingestion(dto["executionId"], timeout=30)


def _proteins_at(client, path: Path) -> list[dict]:
    """Return the project's proteins whose file is ``path``'s stored copy."""
    response = client.entities.search_proteins(
        project_id=client.project_id, file_path=_canonical_path(path)
    )
    return response.get("data") or []


def _write_bundle(out_dir: Path, entries: dict[str, bytes], rows: list[dict]):
    """Write a hand-made zip and CSV, bypassing build_protein_bundle."""
    zip_path = out_dir / "manual.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    csv_path = out_dir / "manual.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["protein_name", "file_path"])
        writer.writeheader()
        writer.writerows(rows)
    return zip_path, csv_path


def test_files_sharing_a_name_become_separate_proteins(client, tmp_path):
    """apo/model.pdb and holo/model.pdb become two proteins named model."""
    src = tmp_path / "src"
    apo = _structure(src / "apo" / "model.pdb")
    holo = _structure(src / "holo" / "model.pdb")
    files = find_structure_files(src, recursive=True)

    row = _import(client, *build_protein_bundle(files, tmp_path))

    assert row["status"] == "Completed"
    for path in (apo, holo):
        (protein,) = _proteins_at(client, path)
        assert protein["protein_name"] == "model"
        assert client.files.download(
            protein["file_path"], local_path=tmp_path / "check.pdb"
        )
        assert (tmp_path / "check.pdb").read_bytes() == path.read_bytes()


def test_rows_naming_one_zip_file_share_one_protein(client, tmp_path):
    """import-dataset caches by zip file name: why the bundle renames entries."""
    data = _structure(tmp_path / "model.pdb").read_bytes()
    zip_path, csv_path = _write_bundle(
        tmp_path,
        {"apo/model.pdb": data, "holo/model.pdb": data + b"REMARK 2\n"},
        [
            {"protein_name": "apo", "file_path": "model.pdb"},
            {"protein_name": "holo", "file_path": "model.pdb"},
        ],
    )

    _import(client, zip_path, csv_path)

    proteins = _proteins_at(client, tmp_path / "model.pdb")
    assert [p["protein_name"] for p in proteins] == ["apo"]


def test_reimport_reuses_the_protein_and_keeps_its_name(client, tmp_path):
    """The same structure imported again under another name is not duplicated."""
    first = _structure(tmp_path / "a" / "first.pdb")
    again = tmp_path / "b" / "again.pdb"
    again.parent.mkdir()
    again.write_bytes(first.read_bytes())

    for path in (first, again):
        out = tmp_path / f"out-{path.stem}"
        out.mkdir()
        _import(client, *build_protein_bundle([path], out))

    assert [p["protein_name"] for p in _proteins_at(client, first)] == ["first"]


def test_file_without_atoms_becomes_a_protein_with_only_a_name(client, tmp_path):
    """As on dev: the run succeeds and the row is imported without a file."""
    good = _structure(tmp_path / "good.pdb")
    bad_name = f"bad-{uuid.uuid4().hex[:8]}"
    zip_path, csv_path = _write_bundle(
        tmp_path,
        {"00001.pdb": good.read_bytes(), "00002.pdb": b"HEADER ONLY\nEND\n"},
        [
            {"protein_name": "good", "file_path": "00001.pdb"},
            {"protein_name": bad_name, "file_path": "00002.pdb"},
        ],
    )

    row = _import(client, zip_path, csv_path)

    assert row["status"] == "Completed"
    assert [p["protein_name"] for p in _proteins_at(client, good)] == ["good"]
    bad = [
        p
        for p in client.entities.search_proteins(
            project_id=client.project_id, limit=500
        ).get("data", [])
        if p.get("protein_name") == bad_name
    ]
    assert len(bad) == 1
    assert bad[0]["file_path"] is None


@pytest.mark.parametrize("folder", ["flat", "nested_unique"])
def test_fixture_folders_import(client, tmp_path, folder):
    """Every structure in the fixture folders imports with a stored file."""
    root = Path(__file__).parent / "fixtures" / "protein_dirs" / folder
    files = find_structure_files(root, recursive=True)

    row = _import(client, *build_protein_bundle(files, tmp_path))

    assert row["status"] == "Completed"
    for path in files:
        proteins = _proteins_at(client, path)
        assert len(proteins) == 1
        assert proteins[0]["file_path"] == _canonical_path(path)


def _import_dataset_execution_ids(client) -> set[str]:
    """Return the ids of the project's import-dataset executions."""
    response = client.executions.list(
        tool_key="deeporigin.import-dataset",
        project_id=client.project_id,
        fetch_all_pages=True,
    )
    return {str(e["executionId"]) for e in response.get("data") or []}


def test_sync_proteins_runs_a_workflow_import_on_version_4(client):
    """sync_proteins starts one import, routed to the workflow on version 4."""
    before = _import_dataset_execution_ids(client)

    projects.sync_proteins(PROTEIN_DIRS / "flat", timeout=30)

    (execution_id,) = _import_dataset_execution_ids(client) - before
    dto = client.executions.get(execution_id)
    inputs = dto["userInputs"]
    assert dto["tool"]["version"] == PROTEIN_FOLDER_IMPORT_TOOL_VERSION
    assert inputs["mapper"] == PROTEIN_FOLDER_CSV_MAPPER
    assert inputs["csv_path"] and inputs["protein_zip_path"]
    assert not inputs.get("sync") and not inputs.get("rows")
    assert not any(k.startswith(("process_", "register_")) for k in inputs)


def test_sync_proteins_imports_every_file_named_after_it(client, tmp_path):
    """Each file is a protein named after its file."""
    apo = _structure(tmp_path / "apo" / "model.pdb")
    holo = _structure(tmp_path / "holo" / "model.pdb")
    top = _structure(tmp_path / "top.pdb")

    projects.sync_proteins(tmp_path, recursive=True, timeout=30)

    for path, name in ((apo, "model"), (holo, "model"), (top, "top")):
        assert [p["protein_name"] for p in _proteins_at(client, path)] == [name]


def test_sync_proteins_accepts_a_list_of_files(client, tmp_path):
    """A list of files imports exactly those files."""
    chosen = _structure(tmp_path / "chosen.pdb")
    skipped = _structure(tmp_path / "skipped.pdb")

    projects.sync_proteins([chosen], timeout=30)

    assert len(_proteins_at(client, chosen)) == 1
    assert _proteins_at(client, skipped) == []


@pytest.mark.parametrize("folder", ["invalid", "empty"])
def test_sync_proteins_uploads_nothing_when_a_file_is_bad(client, folder):
    """Bad files are reported before anything is uploaded."""
    staged_before = client.files.list("imports/staging")

    with pytest.raises(DeepOriginException) as excinfo:
        projects.sync_proteins(PROTEIN_DIRS / folder)

    assert excinfo.value.title == "Protein files can't be imported"
    assert client.files.list("imports/staging") == staged_before


def test_sync_proteins_stages_the_bundle(client, tmp_path):
    """A good folder uploads its zip and CSV, so the check above can see uploads."""
    _structure(tmp_path / "staged.pdb")
    staged_before = set(client.files.list("imports/staging"))

    projects.sync_proteins(tmp_path, timeout=30)

    new = set(client.files.list("imports/staging")) - staged_before
    assert sorted(Path(key).suffix for key in new) == [".csv", ".zip"]


def test_sync_proteins_returns_the_imported_proteins(client, tmp_path):
    """Every imported file is among the returned metadata-only proteins."""
    files = [_structure(tmp_path / f"w{i}.pdb") for i in range(3)]

    proteins = projects.sync_proteins(tmp_path, timeout=30)

    by_path = {p.remote_path: p for p in proteins}
    for path in files:
        protein = by_path[_canonical_path(path)]
        assert protein.name == path.stem
        assert protein.id
        assert protein.project_id == client.project_id
        assert protein.structure is None
    assert len({p.id for p in proteins}) == len(proteins)


def test_sync_proteins_reads_every_page(client, tmp_path, monkeypatch):
    """With one protein per page, every page is read exactly once."""
    monkeypatch.setattr(projects, "PROTEIN_SEARCH_PAGE_SIZE", 1)
    search = client.entities.search_proteins
    cursors = []

    def recording_search(**kwargs):
        cursors.append(kwargs.get("cursor"))
        return search(**kwargs)

    monkeypatch.setattr(client.entities, "search_proteins", recording_search)
    for i in range(2):
        _structure(tmp_path / f"page{i}.pdb")

    proteins = projects.sync_proteins(tmp_path, timeout=30)

    assert len(cursors) == len(proteins) >= 2
    assert cursors[0] is None
    assert len(set(cursors)) == len(cursors)


def test_failed_import_raises_with_the_platform_reason(client, tmp_path):
    """A failed import raises with the platform's reason and the execution id.

    sync_proteins can't send an empty CSV (an empty folder is rejected before
    upload), so the run is started directly and its wait is tested.
    """
    zip_path, csv_path = _write_bundle(tmp_path, {}, [])
    inputs = {
        "csv_path": stage_local_file(client, csv_path),
        "protein_zip_path": stage_local_file(client, zip_path),
        "mapper": PROTEIN_FOLDER_CSV_MAPPER,
        "database_key": IMPORT_DATASET_PROTEINS_DATABASE_KEY,
        "database_version": IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
    }
    execution_id = run_import_dataset_workflow(
        inputs=inputs, project_id=client.project_id, client=client
    )["executionId"]

    with pytest.raises(DeepOriginException) as excinfo:
        projects._wait_for_import(client, execution_id, client.project_id, timeout=30)

    assert excinfo.value.title == "Protein import failed"
    assert "No importable protein rows" in excinfo.value.body
    assert execution_id in excinfo.value.body


@pytest.fixture
def no_sse(client, monkeypatch):
    """Work in the mock project whose SSE stream is refused, polling fast."""
    monkeypatch.setattr(client, "project_id", MOCK_SSE_DISABLED_PROJECT_ID)
    monkeypatch.setattr(
        import_dataset_sync, "DATA_PLATFORM_INGESTION_POLL_SECONDS", 0.01
    )
    return client


def test_sync_proteins_polls_when_sse_is_unavailable(no_sse, tmp_path):
    """A refused SSE stream falls back to polling, with a warning."""
    path = _structure(tmp_path / "polled.pdb")

    with pytest.warns(UserWarning, match="polling"):
        proteins = projects.sync_proteins(tmp_path, timeout=30)

    by_path = {p.remote_path: p for p in proteins}
    assert by_path[_canonical_path(path)].project_id == MOCK_SSE_DISABLED_PROJECT_ID


def test_polling_fallback_raises_when_the_import_fails(no_sse, tmp_path):
    """Without SSE, a failed import still raises with its reason and execution id."""
    zip_path, csv_path = _write_bundle(tmp_path, {}, [])
    inputs = {
        "csv_path": stage_local_file(no_sse, csv_path),
        "protein_zip_path": stage_local_file(no_sse, zip_path),
        "mapper": PROTEIN_FOLDER_CSV_MAPPER,
        "database_key": IMPORT_DATASET_PROTEINS_DATABASE_KEY,
        "database_version": IMPORT_DATASET_PROTEINS_DATABASE_VERSION,
    }
    execution_id = run_import_dataset_workflow(
        inputs=inputs, project_id=no_sse.project_id, client=no_sse
    )["executionId"]

    with (
        pytest.warns(UserWarning, match="polling"),
        pytest.raises(DeepOriginException) as excinfo,
    ):
        projects._wait_for_import(no_sse, execution_id, no_sse.project_id, timeout=30)

    assert excinfo.value.title == "Protein import failed"
    assert "No importable protein rows" in excinfo.value.body
    assert execution_id in excinfo.value.body
