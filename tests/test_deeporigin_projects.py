"""tests deeporigin.projects

Note that this doesn't test deeporigin.platform.projects -- this contains tests of the high-level API."""

from deeporigin import projects
from tests.mock_server.routers.data_platform import MOCK_DEFAULT_PROJECT_NAME

PROJECT_NAME = MOCK_DEFAULT_PROJECT_NAME


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


def test_project_ligands_lv1():
    """test that we can set and get ligands in a project"""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    ligands.sync()
