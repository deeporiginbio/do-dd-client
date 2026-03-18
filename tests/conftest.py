"""Shared fixtures and helpers for tests."""

from pathlib import Path
from typing import Optional

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Ligand, Pocket, Protein
from deeporigin.platform import DeepOriginClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"

PROTEIN_REMOTE_PATH = "testing/brd.pdb"
LIGAND_REMOTE_PATH = "testing/brd-2.sdf"
POCKET_PDB_PATH = FIXTURES_DIR / "files" / "pocketfinder" / "pocket_1.pdb"


def check_function_exists(
    client: DeepOriginClient,
    key: str,
    version: Optional[str] = None,
) -> bool:
    """Check if a function exists on the platform.

    Args:
        client: DeepOrigin client instance.
        key: Function key to look for.
        version: Optional version to match. If None, matches any version.

    Returns:
        True if the function exists (or env is local), False otherwise.
    """

    if client.env == "local":
        return True

    functions = client.functions.list()
    for fcn in functions:
        manifest = fcn["manifestBody"]
        if manifest["key"] == key:
            if version is None or manifest["version"] == version:
                return True
    return False


def check_tool_exists(
    client: DeepOriginClient,
    key: str,
    version: Optional[str] = None,
) -> bool:
    """Check if a tool exists on the platform.

    Args:
        client: DeepOrigin client instance.
        key: Tool key to look for.
        version: Optional version to match. If None, matches any version.

    Returns:
        True if the tool exists (or env is local), False otherwise.
    """
    if client.env == "local":
        return True

    tools = client.tools.list()
    for tool in tools:
        if tool.get("key") == key:
            if version is None or tool.get("version") == version:
                return True
    return False


@pytest.fixture()
def client() -> DeepOriginClient:
    """Return a DeepOriginClient instance."""
    return DeepOriginClient()


@pytest.fixture()
def brd_protein(client: DeepOriginClient) -> Protein:
    """Load BRD protein, remove water, and upload to a stable remote path."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    protein.upload(client=client, remote_path=PROTEIN_REMOTE_PATH)
    return protein


@pytest.fixture()
def brd_ligand(client: DeepOriginClient) -> Ligand:
    """Load BRD ligand from SDF and upload to a stable remote path."""
    ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    ligand.upload(client=client, remote_path=LIGAND_REMOTE_PATH)
    return ligand


@pytest.fixture()
def registered_protein(client: DeepOriginClient) -> Protein:
    """Load BRD protein, remove water, sync with the data platform."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    protein.sync(client=client, remote_path=PROTEIN_REMOTE_PATH)
    return protein


@pytest.fixture()
def registered_ligand(client: DeepOriginClient) -> Ligand:
    """Load BRD ligand from SDF and sync with the data platform."""
    ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
    ligand.sync(client=client, remote_path=LIGAND_REMOTE_PATH)
    return ligand


@pytest.fixture()
def registered_pocket() -> Pocket:
    """Load pocket from PDB fixture file with a stable test ID."""
    pocket = Pocket.from_pdb_file(POCKET_PDB_PATH)
    pocket.id = "pocket-test-id"
    return pocket
