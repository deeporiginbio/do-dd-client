"""tests deeporigin.projects

Note that this doesn't test deeporigin.platform.projects -- this contains tests of the high-level API."""

import pytest

from deeporigin import projects
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from tests.mock_server.routers.data_platform import (
    MOCK_CANONICAL_PROTEIN_ID,
    MOCK_DEFAULT_PROJECT_ID,
    MOCK_DEFAULT_PROJECT_NAME,
)

PROJECT_NAME = MOCK_DEFAULT_PROJECT_NAME


def test_current_lv1() -> None:
    """projects.current() returns the active project id and display name."""

    projects.load(PROJECT_NAME)
    current = projects.current()
    assert current is not None
    project_id, name = current
    assert name == PROJECT_NAME, f"Expected project name {PROJECT_NAME}, got {name}"
    assert project_id
    # Local mock uses a stable seeded id; dev resolves a real platform id.
    if DeepOriginClient().env == "local":
        assert project_id == MOCK_DEFAULT_PROJECT_ID


def test_load_lv1() -> None:
    """projects.load() selects a project by display name and by id."""

    projects.load(PROJECT_NAME)
    client = DeepOriginClient()
    pid = client.project_id
    assert pid is not None
    cur = projects.current()
    assert cur is not None
    assert cur[1] == PROJECT_NAME, f"Expected project name {PROJECT_NAME}, got {cur[1]}"
    assert cur[0] == str(pid)

    projects.load(str(pid))
    assert client.project_id == str(pid)
    cur = projects.current()
    assert cur is not None
    assert cur[0] == str(pid)
    assert cur[1] == PROJECT_NAME

    if client.env == "local":
        projects.load("python-client-test-project")
        assert client.project_id == MOCK_DEFAULT_PROJECT_ID


def test_create_lv1() -> None:
    """tests that upsert works"""

    project_id = projects.create(PROJECT_NAME)
    assert project_id is not None

    assert projects.create(PROJECT_NAME) == project_id, (
        "create should return the same project id if the project already exists"
    )


def test_list_lv1():
    """tests that list works"""

    projects.create(PROJECT_NAME)

    df = projects.list()
    assert df is not None, "list should return a DataFrame"
    assert len(df) > 0, "list should return at least one project"


def test_get_ligands_lv1(monkeypatch: pytest.MonkeyPatch) -> None:
    """projects.get_ligands() collects ids from search and passes them to LigandSet.from_ids."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    captured: list[list[str]] = []

    def fake_from_ids(ids: list[str], *, client: object | None = None) -> LigandSet:
        captured.append([str(i) for i in ids])
        return LigandSet(ligands=[])

    projects.load(PROJECT_NAME)
    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    ligands.sync()

    monkeypatch.setattr(
        "deeporigin.drug_discovery.structures.ligand.LigandSet.from_ids",
        fake_from_ids,
    )
    projects.get_ligands()
    df = projects.ligands()
    assert captured, "from_ids should be called with platform ligand ids"
    assert set(captured[0]) == set(df["id"].astype(str))


def test_project_proteins_lv1() -> None:
    """projects.proteins() includes a protein id after sync()."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, Protein

    projects.load(PROJECT_NAME)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.sync()
    assert protein.id is not None

    df = projects.proteins()
    ids = df["id"].astype(str).tolist()
    assert str(protein.id) in ids

    if DeepOriginClient().env == "local":
        assert str(protein.id) == MOCK_CANONICAL_PROTEIN_ID


def test_project_ligands_lv1() -> None:
    """projects.ligands() includes ids for ligands synced from BRD_DATA_DIR."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    projects.load(PROJECT_NAME)
    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    assert len(ligands.ligands) > 0
    ligands.sync()

    for lig in ligands.ligands:
        assert lig.id is not None

    df = projects.ligands()
    ids = df["id"].astype(str).tolist()
    for lig in ligands.ligands:
        assert str(lig.id) in ids


def test_current_no_project_lv1() -> None:
    """projects.current() is None when no project is selected."""

    DeepOriginClient.close_all()
    assert projects.current() is None


def test_ligands_requires_project_lv1() -> None:
    """projects.ligands() raises when no project is active."""

    DeepOriginClient.close_all()
    with pytest.raises(DeepOriginException) as excinfo:
        projects.ligands()
    assert excinfo.value.title == "No current project"


def test_load_not_found_lv1() -> None:
    """projects.load() raises when no project matches the identifier."""

    with pytest.raises(DeepOriginException) as excinfo:
        projects.load("zzzz-nonexistent-project-99999")
    assert excinfo.value.title == "Project not found"


def test_create_load_false_lv1() -> None:
    """projects.create(..., load=False) returns an id without selecting the project."""

    DeepOriginClient.close_all()
    pid = projects.create(PROJECT_NAME, load=False)
    assert pid
    assert DeepOriginClient().project_id is None


def test_list_limit_none_lv1() -> None:
    """projects.list(limit=None) returns a DataFrame without error."""

    projects.create(PROJECT_NAME)
    df = projects.list(limit=None)
    assert df is not None
    assert {"id", "name", "description"}.issubset(set(df.columns))


def test_executions_lv1() -> None:
    """projects.executions() returns a DataFrame with execution metadata columns."""

    projects.load(PROJECT_NAME)
    df = projects.executions()
    required = {
        "id",
        "tool_key",
        "tool_version",
        "status",
        "started_at",
        "completed_at",
    }
    assert required.issubset(set(df.columns))
    assert "execution_id" in df.columns
    if DeepOriginClient().env == "local":
        assert len(df) >= 1


def test_get_proteins_lv1() -> None:
    """projects.get_proteins() returns Protein objects for the current project."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, Protein

    projects.load(PROJECT_NAME)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.sync()
    assert protein.id is not None

    out = projects.get_proteins()
    assert len(out) >= 1
    got_ids = {str(p.id) for p in out if p.id is not None}
    assert str(protein.id) in got_ids


def test_set_ligands_lv1() -> None:
    """projects.set_ligands() syncs a LigandSet to the current project."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    projects.load(PROJECT_NAME)
    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    assert len(ligands.ligands) > 0
    projects.set_ligands(ligands)

    for lig in ligands.ligands:
        assert lig.id is not None
    df = projects.ligands()
    ids = df["id"].astype(str).tolist()
    for lig in ligands.ligands:
        assert str(lig.id) in ids


def test_set_proteins_lv1() -> None:
    """projects.set_proteins() syncs proteins to the current project."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, Protein

    projects.load(PROJECT_NAME)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    projects.set_proteins([protein])
    assert protein.id is not None

    df = projects.proteins()
    assert str(protein.id) in df["id"].astype(str).tolist()
    if DeepOriginClient().env == "local":
        assert str(protein.id) == MOCK_CANONICAL_PROTEIN_ID
