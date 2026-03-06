"""Tests for the ABFE execution class."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.drug_discovery.abfe import ABFE
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.platform.client import DeepOriginClient

_BRD_PDB = Path(os.path.join(BRD_DATA_DIR, "brd.pdb"))


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def protein():
    """Create a real Protein from the bundled BRD data."""
    return Protein.from_file(str(_BRD_PDB))


@pytest.fixture
def ligand():
    """Create a real Ligand from a simple SMILES."""
    return Ligand.from_smiles("CCO", name="ethanol")


@pytest.fixture
def client():
    """Create a mock DeepOriginClient that passes beartype checks."""
    return MagicMock(spec=DeepOriginClient)


@pytest.fixture
def abfe(protein, ligand, client):
    """Create an ABFE instance."""
    return ABFE(protein=protein, ligand=ligand, client=client)


# ===========================================================================
# Construction
# ===========================================================================


class TestABFEConstruction:
    """ABFE construction and attribute access."""

    def test_defaults(self, abfe, protein, ligand):
        """Fresh ABFE has None for id, estimate, cost, status."""
        assert abfe.protein is protein
        assert abfe.ligand is ligand
        assert abfe.id is None
        assert abfe.estimate is None
        assert abfe.cost is None
        assert abfe.status is None
        assert abfe.binding_xml_path is None
        assert abfe.solvation_xml_path is None

    def test_tool_key(self, abfe):
        """tool_key matches the expected ABFE tool key."""
        assert abfe.tool_key == "deeporigin.abfe-end-to-end"


# ===========================================================================
# Immutable fields
# ===========================================================================


class TestABFEImmutableFields:
    """Immutable field enforcement after construction."""

    def test_protein_immutable(self, abfe, protein):
        """protein cannot be reassigned."""
        with pytest.raises(AttributeError, match="protein"):
            abfe.protein = protein

    def test_ligand_immutable(self, abfe, ligand):
        """ligand cannot be reassigned."""
        with pytest.raises(AttributeError, match="ligand"):
            abfe.ligand = ligand


# ===========================================================================
# Async lifecycle
# ===========================================================================


class TestABFEAsyncLifecycle:
    """ABFE exposes async lifecycle methods."""

    def test_has_status(self, abfe):
        """ABFE instances have a status attribute."""
        assert hasattr(abfe, "status")
        assert abfe.status is None

    def test_has_start(self, abfe):
        """ABFE instances have a start method."""
        assert hasattr(abfe, "start")

    def test_has_cancel(self, abfe):
        """ABFE instances have a cancel method."""
        assert hasattr(abfe, "cancel")

    def test_has_sync(self, abfe):
        """ABFE instances have a sync method."""
        assert hasattr(abfe, "sync")

    def test_no_run_method(self, abfe):
        """ABFE (async-only) should NOT have run()."""
        assert not hasattr(abfe, "run")

    def test_cancel_no_id_raises(self, abfe):
        """cancel() with no execution ID raises ValueError."""
        with pytest.raises(ValueError, match="id is None"):
            abfe.cancel()

    def test_sync_no_id_raises(self, abfe):
        """sync() with no execution ID raises ValueError."""
        with pytest.raises(ValueError, match="id is None"):
            abfe.sync()


# ===========================================================================
# Prepare
# ===========================================================================


class TestABFEPrepare:
    """ABFE.prepare() runs system preparation."""

    def test_prepare_sets_xml_paths(self, protein, ligand, client):
        """prepare() populates binding_xml_path and solvation_xml_path."""
        mock_client = MagicMock()
        mock_client.files.download_file.return_value = str(_BRD_PDB)

        abfe = ABFE(protein=protein, ligand=ligand, client=client)
        abfe.client = mock_client

        mock_result = MagicMock()
        mock_result.function_outputs = [
            {
                "output_files": [
                    "/remote/path/bsm_system.xml",
                    "/remote/path/solvation.xml",
                ],
                "system": {"system_pdb_file_path": "/remote/system.pdb"},
            }
        ]

        with (
            patch.object(abfe.protein, "find_missing_residues", return_value=[]),
            patch.object(abfe.ligand, "is_charged", return_value=False),
            patch(
                "deeporigin.functions.sysprep.abfe",
                return_value=mock_result,
            ),
        ):
            abfe.prepare()

        assert abfe.binding_xml_path == "/remote/path/bsm_system.xml"
        assert abfe.solvation_xml_path == "/remote/path/solvation.xml"

    def test_prepare_charged_ligand_raises(self, abfe):
        """prepare() raises when ligand is charged."""
        with patch.object(abfe.ligand, "is_charged", return_value=True):
            with pytest.raises(Exception, match="charged"):
                abfe.prepare()


# ===========================================================================
# Quote
# ===========================================================================


class TestABFEQuote:
    """ABFE.quote() requires preparation."""

    def test_quote_without_prepare_raises(self, abfe):
        """quote() raises ValueError if prepare() hasn't been called."""
        with pytest.raises(ValueError, match="not been prepared"):
            abfe.quote()

    def test_quote_sets_estimate(self, abfe):
        """quote() populates estimate after prepare()."""
        abfe.binding_xml_path = "/remote/binding.xml"
        abfe.solvation_xml_path = "/remote/solvation.xml"

        mock_dto = {
            "quotationResult": {
                "successfulQuotations": [{"priceTotal": 12.50}],
            },
            "executionId": "exec-123",
            "status": "Quoted",
        }

        with patch(
            "deeporigin.drug_discovery.utils._start_tool_run",
            return_value=mock_dto,
        ):
            abfe.quote()

        assert abfe.estimate == 12.50
        assert abfe.id == "exec-123"


# ===========================================================================
# Start
# ===========================================================================


class TestABFEStart:
    """ABFE.start() submits the execution."""

    def test_start_without_prepare_raises(self, abfe):
        """start() raises ValueError if prepare() hasn't been called."""
        with pytest.raises(ValueError, match="not been prepared"):
            abfe.start()

    def test_start_sets_id_and_status(self, abfe):
        """start() assigns execution ID and status from the platform."""
        abfe.binding_xml_path = "/remote/binding.xml"
        abfe.solvation_xml_path = "/remote/solvation.xml"

        mock_dto = {
            "executionId": "exec-456",
            "status": "Created",
        }
        mock_job = MagicMock()
        mock_job.id = "exec-456"
        mock_job.status = "Created"

        abfe.client = MagicMock()

        with (
            patch(
                "deeporigin.drug_discovery.utils._start_tool_run",
                return_value=mock_dto,
            ),
            patch(
                "deeporigin.platform.job.Job.from_dto",
                return_value=mock_job,
            ),
            patch.object(abfe.protein, "sync"),
        ):
            abfe.start()

        assert abfe.id == "exec-456"
        assert abfe.status == "Created"


# ===========================================================================
# Get results
# ===========================================================================


class TestABFEGetResults:
    """ABFE.get_results() retrieves results from the platform."""

    def test_get_results_no_id_raises(self, abfe):
        """get_results() raises ValueError if no execution started."""
        with pytest.raises(ValueError, match="No execution"):
            abfe.get_results()

    def test_get_results_not_succeeded_returns_none(self, abfe, client):
        """get_results() returns None if status is not Succeeded."""
        abfe.client = client

        abfe._id = "exec-789"
        abfe.status = "Created"

        client.executions = MagicMock()
        client.executions.get_execution.return_value = {"status": "Running"}
        result = abfe.get_results()

        assert result is None


# ===========================================================================
# Build helpers
# ===========================================================================


class TestABFEBuildHelpers:
    """Internal helper methods for params, metadata, output dir."""

    def test_build_metadata(self, abfe):
        """_build_metadata returns expected keys."""
        meta = abfe._build_metadata()
        assert "protein_hash" in meta
        assert "ligand_hash" in meta
        assert "ligand_smiles" in meta
        assert "protein_name" in meta
        assert "ligand_name" in meta

    def test_build_outputs(self, abfe):
        """_build_outputs includes expected output keys."""
        outputs = abfe._build_outputs()
        assert "output_file" in outputs
        assert "abfe_results_summary" in outputs
        assert "results.csv" in outputs["abfe_results_summary"]["key"]
