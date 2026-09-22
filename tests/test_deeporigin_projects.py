"""tests deeporigin.projects

Note that this doesn't test deeporigin.platform.projects -- this contains tests of the high-level API."""

import pytest

from deeporigin import projects
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient
from tests.integration_project import (
    integration_project_id_for_env,
    integration_project_name,
)
from tests.mock_server.routers.data_platform import MOCK_CANONICAL_PROTEIN_ID


def test_current_lv1(client: DeepOriginClient) -> None:
    """projects.current() returns the active project id and display name."""

    project_name = integration_project_name(client.env)
    projects.load(project_name)
    current = projects.current()
    assert current is not None
    project_id, name = current
    assert name == project_name, f"Expected project name {project_name}, got {name}"
    assert project_id
    expected_id = integration_project_id_for_env(client.env)
    if expected_id is not None:
        assert project_id == expected_id


def test_load_lv1(client: DeepOriginClient) -> None:
    """projects.load() selects a project by display name and by id."""

    project_name = integration_project_name(client.env)
    projects.load(project_name)
    pid = client.project_id
    assert pid is not None
    cur = projects.current()
    assert cur is not None
    assert cur[1] == project_name, (
        f"Expected project name {project_name}, got {cur[1]}"
    )
    assert cur[0] == str(pid)

    projects.load(str(pid))
    assert client.project_id == str(pid)
    cur = projects.current()
    assert cur is not None
    assert cur[0] == str(pid)
    assert cur[1] == project_name

    if client.env == "local":
        projects.load("python-client-test-project")
        expected_id = integration_project_id_for_env("local")
        assert client.project_id == expected_id


def test_create_lv1(client: DeepOriginClient) -> None:
    """tests that upsert works"""

    project_name = integration_project_name(client.env)
    project_id = projects.create(project_name)
    assert project_id is not None

    assert projects.create(project_name) == project_id, (
        "create should return the same project id if the project already exists"
    )


def test_list_lv1(client: DeepOriginClient):
    """tests that list works"""

    projects.create(integration_project_name(client.env))

    df = projects.list()
    assert df is not None, "list should return a DataFrame"
    assert len(df) > 0, "list should return at least one project"


def test_get_ligands_lv1(
    monkeypatch: pytest.MonkeyPatch, client: DeepOriginClient
) -> None:
    """projects.get_ligands() collects ids from search and passes them to LigandSet.from_ids."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    captured: list[list[str]] = []

    def fake_from_ids(ids: list[str], *, client: object | None = None) -> LigandSet:
        captured.append([str(i) for i in ids])
        return LigandSet(ligands=[])

    projects.load(integration_project_name(client.env))
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


def test_project_proteins_lv1(client: DeepOriginClient) -> None:
    """projects.proteins() includes a protein id after sync()."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, Protein

    projects.load(integration_project_name(client.env))
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.sync()
    assert protein.id is not None

    df = projects.proteins()
    ids = df["id"].astype(str).tolist()
    assert str(protein.id) in ids

    if client.env == "local":
        assert str(protein.id) == MOCK_CANONICAL_PROTEIN_ID


def test_project_ligands_lv1(client: DeepOriginClient) -> None:
    """projects.ligands() includes ids for ligands synced from BRD_DATA_DIR."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    projects.load(integration_project_name(client.env))
    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    assert len(ligands.ligands) > 0
    ligands.sync()

    for lig in ligands.ligands:
        assert lig.id is not None

    df = projects.ligands()
    ids = df["id"].astype(str).tolist()
    for lig in ligands.ligands:
        assert str(lig.id) in ids


def test_current_no_project_lv1(client: DeepOriginClient) -> None:
    """projects.current() is None when no project is selected."""

    DeepOriginClient.close_all()
    assert projects.current() is None


def test_ligands_requires_project_lv1(client: DeepOriginClient) -> None:
    """projects.ligands() raises when no project is active."""

    DeepOriginClient.close_all()
    with pytest.raises(DeepOriginException) as excinfo:
        projects.ligands()
    assert excinfo.value.title == "No current project"


def test_load_not_found_lv1(client: DeepOriginClient) -> None:
    """projects.load() raises when no project matches the identifier."""

    with pytest.raises(DeepOriginException) as excinfo:
        projects.load("zzzz-nonexistent-project-99999")
    assert excinfo.value.title == "Project not found"


def test_create_load_false_lv1(client: DeepOriginClient) -> None:
    """projects.create(..., load=False) returns an id without selecting the project."""

    client.project_id = None
    pid = projects.create(integration_project_name(client.env), load=False, client=client)
    assert pid
    assert client.project_id is None
    assert projects.current() is None


def test_list_limit_none_lv1(client: DeepOriginClient) -> None:
    """projects.list(limit=None) returns a DataFrame without error."""

    projects.create(integration_project_name(client.env))
    df = projects.list(limit=None)
    assert df is not None
    assert {"id", "name", "description"}.issubset(set(df.columns))


def test_executions_lv1(client: DeepOriginClient) -> None:
    """projects.executions() returns a DataFrame with execution metadata columns."""

    projects.load(integration_project_name(client.env))
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
    if client.env == "local":
        assert len(df) >= 1


def test_get_proteins_lv1(client: DeepOriginClient) -> None:
    """projects.get_proteins() returns Protein objects for the current project."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, Protein

    projects.load(integration_project_name(client.env))
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.sync()
    assert protein.id is not None

    out = projects.get_proteins()
    assert len(out) >= 1
    got_ids = {str(p.id) for p in out if p.id is not None}
    assert str(protein.id) in got_ids


def test_set_ligands_lv1(client: DeepOriginClient) -> None:
    """projects.set_ligands() syncs a LigandSet to the current project."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    projects.load(integration_project_name(client.env))
    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    assert len(ligands.ligands) > 0
    projects.set_ligands(ligands)

    for lig in ligands.ligands:
        assert lig.id is not None
    df = projects.ligands()
    ids = df["id"].astype(str).tolist()
    for lig in ligands.ligands:
        assert str(lig.id) in ids


def test_set_proteins_lv1(client: DeepOriginClient) -> None:
    """projects.set_proteins() syncs proteins to the current project."""

    from deeporigin.drug_discovery import BRD_DATA_DIR, Protein

    projects.load(integration_project_name(client.env))
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    projects.set_proteins([protein])
    assert protein.id is not None

    df = projects.proteins()
    assert str(protein.id) in df["id"].astype(str).tolist()
    if client.env == "local":
        assert str(protein.id) == MOCK_CANONICAL_PROTEIN_ID
