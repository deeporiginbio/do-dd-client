"""Tests for the Docking execution class."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.drug_discovery.docking import Docking
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.platform.client import DeepOriginClient

_BRD_PDB = Path(os.path.join(BRD_DATA_DIR, "brd.pdb"))
_POCKET_PDB = Path(
    "tests/fixtures/files/tool-runs/86ea3aea-accd-474d-9e0b-89a3f47ab61b/pocket_1.pdb"
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def protein():
    """Create a real Protein from the bundled BRD data."""
    return Protein.from_file(str(_BRD_PDB))


@pytest.fixture
def pocket():
    """Create a real Pocket from fixture data."""
    return Pocket.from_pdb_file(str(_POCKET_PDB))


@pytest.fixture
def ligand_set():
    """Create a small LigandSet from SMILES."""
    return LigandSet.from_smiles(["CCO", "CCCO"])


@pytest.fixture
def client():
    """Create a mock DeepOriginClient that passes beartype checks."""
    return MagicMock(spec=DeepOriginClient)


@pytest.fixture
def docking_with_ligands(protein, pocket, ligand_set, client):
    """Create a Docking instance using a LigandSet."""
    return Docking(
        protein=protein,
        pocket=pocket,
        ligands=ligand_set,
        client=client,
    )


@pytest.fixture
def docking_with_smiles(protein, pocket, client):
    """Create a Docking instance using raw SMILES."""
    return Docking(
        protein=protein,
        pocket=pocket,
        smiles_list=["CCO", "CCCO"],
        client=client,
    )


# ===========================================================================
# Construction tests
# ===========================================================================


class TestDockingConstruction:
    """Docking construction and attribute access."""

    def test_with_ligand_set(self, docking_with_ligands, protein, pocket, ligand_set):
        """Docking can be constructed with a LigandSet."""
        d = docking_with_ligands
        assert d.protein is protein
        assert d.pocket is pocket
        assert d.ligands is ligand_set
        assert d.smiles_list is None
        assert d.id is None
        assert d.estimate is None
        assert d.cost is None
        assert d.status is None

    def test_with_smiles_list(self, docking_with_smiles, protein, pocket):
        """Docking can be constructed with a SMILES list."""
        d = docking_with_smiles
        assert d.protein is protein
        assert d.pocket is pocket
        assert d.ligands is None
        assert d.smiles_list == ["CCO", "CCCO"]

    def test_neither_ligands_nor_smiles_raises(self, protein, pocket, client):
        """Omitting both ligands and smiles_list raises ValueError."""
        with pytest.raises(ValueError, match="Either ligands or smiles_list"):
            Docking(protein=protein, pocket=pocket, client=client)

    def test_tool_key(self, docking_with_ligands):
        """tool_key matches the platform constant."""
        assert "docking" in docking_with_ligands.tool_key.lower()


# ===========================================================================
# Immutable fields
# ===========================================================================


class TestDockingImmutableFields:
    """Immutable field enforcement after construction."""

    def test_protein_immutable(self, docking_with_ligands, protein):
        """protein cannot be reassigned."""
        with pytest.raises(AttributeError, match="protein"):
            docking_with_ligands.protein = protein

    def test_pocket_immutable(self, docking_with_ligands, pocket):
        """pocket cannot be reassigned."""
        with pytest.raises(AttributeError, match="pocket"):
            docking_with_ligands.pocket = pocket

    def test_ligands_immutable(self, docking_with_ligands, ligand_set):
        """ligands cannot be reassigned."""
        with pytest.raises(AttributeError, match="ligands"):
            docking_with_ligands.ligands = ligand_set

    def test_smiles_list_immutable(self, docking_with_smiles):
        """smiles_list cannot be reassigned."""
        with pytest.raises(AttributeError, match="smiles_list"):
            docking_with_smiles.smiles_list = ["CC"]


# ===========================================================================
# Async lifecycle
# ===========================================================================


class TestDockingAsyncLifecycle:
    """Docking exposes async lifecycle methods from AsyncExecutableMixin."""

    def test_has_status(self, docking_with_ligands):
        """Docking instances have a status attribute."""
        assert hasattr(docking_with_ligands, "status")
        assert docking_with_ligands.status is None

    def test_has_start(self, docking_with_ligands):
        """Docking instances have a start method."""
        assert hasattr(docking_with_ligands, "start")

    def test_has_cancel(self, docking_with_ligands):
        """Docking instances have a cancel method."""
        assert hasattr(docking_with_ligands, "cancel")

    def test_has_refresh(self, docking_with_ligands):
        """Docking instances have a refresh method."""
        assert hasattr(docking_with_ligands, "refresh")

    def test_cancel_no_id_raises(self, docking_with_ligands):
        """cancel() with no execution ID raises ValueError."""
        with pytest.raises(ValueError, match="id is None"):
            docking_with_ligands.cancel()

    def test_refresh_no_id_raises(self, docking_with_ligands):
        """refresh() via base mixin with no execution ID raises ValueError."""
        with pytest.raises(ValueError, match="id is None"):
            docking_with_ligands.refresh()


# ===========================================================================
# Quote
# ===========================================================================


class TestDockingQuote:
    """Docking.quote() populates estimate."""

    def test_quote_sets_estimate(self, docking_with_ligands):
        """quote() calls the functions API and sets self.estimate."""
        mock_result = MagicMock()
        mock_result.estimate = 0.10

        with patch(
            "deeporigin.functions.docking.dock",
            return_value=mock_result,
        ) as mock_fn:
            docking_with_ligands.quote()
            mock_fn.assert_called_once()
            call_kwargs = mock_fn.call_args[1]
            assert call_kwargs["quote"] is True

        assert docking_with_ligands.estimate == pytest.approx(0.20)


# ===========================================================================
# Run (sync)
# ===========================================================================


class TestDockingRun:
    """Docking.run() returns poses and sets cost."""

    def test_run_returns_ligand_set_and_sets_cost(self, docking_with_ligands):
        """run() delegates to functions API and sets cost."""
        mock_dock_result = MagicMock()
        mock_dock_result.response = {"status": "Succeeded"}

        mock_poses = MagicMock(spec=LigandSet)
        mock_func_result = MagicMock()
        mock_func_result.cost = 1.50

        with (
            patch(
                "deeporigin.functions.parallel.run_func_in_parallel",
                return_value={"results": [mock_dock_result, mock_dock_result]},
            ),
            patch(
                "deeporigin.functions.result.FunctionResult",
                return_value=mock_func_result,
            ),
            patch(
                "deeporigin.drug_discovery.structures.protein._make_poses_from_dock_results",
                return_value=mock_poses,
            ),
        ):
            result = docking_with_ligands.run()

        assert result is mock_poses
        assert docking_with_ligands.cost == 1.50


# ===========================================================================
# Resolve ligands
# ===========================================================================


class TestDockingResolveLigands:
    """_resolve_ligands works with both ligands and smiles_list."""

    def test_resolve_from_ligand_set(self, docking_with_ligands):
        """_resolve_ligands returns ligands from the LigandSet."""
        result = docking_with_ligands._resolve_ligands()
        assert len(result) == 2
        assert all(isinstance(lig, Ligand) for lig in result)

    def test_resolve_from_smiles(self, docking_with_smiles):
        """_resolve_ligands creates Ligands from SMILES strings."""
        result = docking_with_smiles._resolve_ligands()
        assert len(result) == 2
        assert all(isinstance(lig, Ligand) for lig in result)


# ===========================================================================
# Repr
# ===========================================================================


class TestDockingRepr:
    """__repr__ produces a readable summary."""

    def test_repr_contains_docking(self, docking_with_ligands):
        """Repr starts with Docking."""
        r = repr(docking_with_ligands)
        assert "Docking" in r

    def test_repr_shows_ligand_count(self, docking_with_ligands):
        """Repr includes number of ligands."""
        r = repr(docking_with_ligands)
        assert "ligands=2" in r

    def test_repr_smiles_single(self, protein, pocket, client):
        """Repr of single-SMILES docking shows the SMILES string."""
        d = Docking(
            protein=protein,
            pocket=pocket,
            smiles_list=["CCO"],
            client=client,
        )
        r = repr(d)
        assert "CCO" in r
