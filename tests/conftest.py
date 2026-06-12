"""Shared fixtures and helpers for tests."""

import math
from pathlib import Path
from typing import Optional

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Ligand, Pocket, Protein
from deeporigin.platform import DeepOriginClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_deeporigin_client_cache() -> None:
    """Drop cached clients so each test gets a fresh client.

    :class:`~deeporigin.platform.client.DeepOriginClient` is a singleton; the
    cache key omits ``project_id`` because it is mutable (see
    :func:`deeporigin.projects.load`). Without a reset, a test could see another
    test's ``project_id`` or other client state until
    :meth:`~deeporigin.platform.client.DeepOriginClient.close_all` runs.
    """
    DeepOriginClient.close_all()


PROTEIN_REMOTE_PATH = "testing/brd.pdb"
LIGAND_REMOTE_PATH = "testing/brd-2.sdf"
LIGAND_3_REMOTE_PATH = "testing/brd-3.sdf"
POCKET_PDB_PATH = FIXTURES_DIR / "files" / "pocketfinder" / "pocket_1.pdb"
# PDB-derived test pockets may report tiny extents; docking tests use a minimum box.
_MIN_TEST_POCKET_BOX_EXTENT = 10.0
_DEFAULT_TEST_POCKET_BOX_SIZE = 30.0


def _normalize_pocket_box_sizes_for_tests(pocket: Pocket) -> None:
    """Raise any axis below 10 Å to the default test box size.

    Compares each ``box_size_*`` to the volume-derived default docking uses when an
    axis is omitted; if either resolved value is below ``_MIN_TEST_POCKET_BOX_EXTENT``,
    that axis is set to ``_DEFAULT_TEST_POCKET_BOX_SIZE``.

    Args:
        pocket: Pocket loaded from a test fixture (mutated in place).
    """
    pocket.get_center()
    vol = pocket.volume or 0.0
    docking_default = float(2 * math.cbrt(vol)) if vol > 0 else 0.0
    for attr in ("box_size_x", "box_size_y", "box_size_z"):
        val = getattr(pocket, attr)
        effective = float(val) if val is not None else docking_default
        if effective < _MIN_TEST_POCKET_BOX_EXTENT:
            setattr(pocket, attr, _DEFAULT_TEST_POCKET_BOX_SIZE)


def check_tool_exists(
    client: DeepOriginClient,
    key: str,
    version: Optional[str] = None,
) -> bool:
    """Check if a tool exists on the platform.

    Args:
        client: DeepOrigin client instance.
        key: Tool key to look for.
        version: Optional version pin (exact semver, major-only, or ``latest``).
            If None, any registered enabled version satisfies the check.

    Returns:
        True if the tool exists (or env is local), False otherwise.
    """
    if client.env == "local":
        return True

    if version is not None:
        return client.tools.exists(tool_key=key, tool_version=version)

    response = client.tools.get_by_key(tool_key=key)
    if isinstance(response, dict) and "data" in response:
        definitions = response["data"]
    elif isinstance(response, list):
        definitions = response
    else:
        definitions = []
    return any(d.get("enabled") is not False for d in definitions)


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
def brd_ligand_brd3(client: DeepOriginClient) -> Ligand:
    """Load BRD-3 ligand from SDF and upload to a stable remote path."""
    ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
    ligand.upload(client=client, remote_path=LIGAND_3_REMOTE_PATH)
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
def registered_ligand_brd3(client: DeepOriginClient) -> Ligand:
    """Load BRD-3 ligand from SDF and sync with the data platform."""
    ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
    ligand.sync(client=client, remote_path=LIGAND_3_REMOTE_PATH)
    return ligand


def _pocket_from_test_fixture_pdb() -> Pocket:
    """Build a normalized test pocket from the shared PDB fixture."""
    pocket = Pocket.from_pdb_file(POCKET_PDB_PATH)
    _normalize_pocket_box_sizes_for_tests(pocket)
    return pocket


@pytest.fixture()
def unregistered_pocket() -> Pocket:
    """Pocket from disk for docking tests (no platform id; geometry-only tool input)."""
    return _pocket_from_test_fixture_pdb()
