"""Tests for the jobs-centric base classes, mixins, PocketFinder, and SystemPrep."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    QuoteMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.pocket_finder import PocketFinder
from deeporigin.drug_discovery.structures.ligand import Ligand
from deeporigin.drug_discovery.structures.prepared_system import PreparedSystem
from deeporigin.drug_discovery.system_prep import SystemPrep
from deeporigin.functions.result import FunctionResult

_BRD_PDB = Path(os.path.join(BRD_DATA_DIR, "brd.pdb"))


# ---------------------------------------------------------------------------
# Helpers -- minimal subclasses for testing the base machinery
# ---------------------------------------------------------------------------


class SyncOnlyJob(Execution, QuoteMixin, SyncExecutableMixin):
    """Minimal sync-only execution for testing."""

    tool_key = "test.sync"
    tool_version = "0.0.1"

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    @property
    def name(self) -> str:
        """Immutable job name."""
        return self._name


class AsyncJob(Execution, QuoteMixin, AsyncExecutableMixin):
    """Minimal async execution for testing."""

    tool_key = "test.async"
    tool_version = "0.0.1"

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    @property
    def name(self) -> str:
        """Immutable job name."""
        return self._name


# ===========================================================================
# Fixtures
# ===========================================================================


# IDs used by SystemPrep tests (constructor requires protein and ligand(s) to have id set).
_PROTEIN_ID = "08490C8DF2ACD"
_LIGAND_ID = "08886EA147352"
_LIGAND2_ID = "08BT9WM0NYVFY"


@pytest.fixture
def protein():
    """Create a real Protein from the bundled BRD data with id set for SystemPrep."""
    p = Protein.from_file(str(_BRD_PDB))
    p.id = _PROTEIN_ID
    return p


@pytest.fixture
def ligand():
    """Create a minimal Ligand from SMILES with id set for SystemPrep."""
    lig = Ligand.from_smiles("CCO", name="ethanol")
    lig.id = _LIGAND_ID
    return lig


# ===========================================================================
# Execution tests
# ===========================================================================


class TestExecutionReadOnly:
    """Read-only field enforcement on Execution."""

    def test_id_blocked(self):
        """Assigning id directly raises AttributeError."""
        job = SyncOnlyJob("x")
        with pytest.raises(AttributeError, match="id"):
            job.id = "should-fail"

    def test_estimate_blocked(self):
        """Assigning estimate directly raises AttributeError."""
        job = SyncOnlyJob("x")
        with pytest.raises(AttributeError, match="estimate"):
            job.estimate = 1.23

    def test_cost_blocked(self):
        """Assigning cost directly raises AttributeError."""
        job = SyncOnlyJob("x")
        with pytest.raises(AttributeError, match="cost"):
            job.cost = 4.56

    def test_private_attrs_allow_internal_writes(self):
        """Internal code can write to the private backing attributes."""
        job = SyncOnlyJob("x")
        job._id = "abc"
        job._estimate = 1.0
        job._cost = 2.0
        assert job.id == "abc"
        assert job.estimate == 1.0
        assert job.cost == 2.0

    def test_initial_values_are_none(self):
        """id, estimate, cost default to None."""
        job = SyncOnlyJob("x")
        assert job.id is None
        assert job.estimate is None
        assert job.cost is None


class TestExecutionImmutableFields:
    """Immutable input field enforcement."""

    def test_immutable_field_blocked(self):
        """Assigning to an immutable field raises AttributeError."""
        job = SyncOnlyJob("original")
        with pytest.raises(AttributeError, match="name"):
            job.name = "changed"

    def test_immutable_field_readable(self):
        """Immutable fields are readable after construction."""
        job = SyncOnlyJob("hello")
        assert job.name == "hello"


class TestExecutionStatusTransitions:
    """Lifecycle state transition validation."""

    def test_valid_transition_from_none_to_created(self):
        """None -> Created is allowed."""
        job = AsyncJob("x")
        job._set_status("Created")
        assert job.status == "Created"

    def test_valid_transition_chain(self):
        """None -> Created -> Queued -> Running -> Succeeded."""
        job = AsyncJob("x")
        for s in ["Created", "Queued", "Running", "Succeeded"]:
            job._set_status(s)
        assert job.status == "Succeeded"

    def test_invalid_transition_raises(self):
        """Transitioning from None directly to Succeeded raises ValueError."""
        job = AsyncJob("x")
        with pytest.raises(ValueError, match="Invalid status transition"):
            job._set_status("Succeeded")

    def test_terminal_state_blocks_further_transitions(self):
        """None -> Created -> Running -> Succeeded blocks further transitions."""
        job = AsyncJob("x")
        job._set_status("Created")
        job._set_status("Running")
        job._set_status("Succeeded")
        with pytest.raises(ValueError, match="Invalid status transition"):
            job._set_status("Running")


class TestExecutionRepr:
    """__repr__ produces a human-readable summary."""

    def test_repr_minimal(self):
        """Repr of a fresh job shows the class name."""
        job = SyncOnlyJob("x")
        r = repr(job)
        assert "SyncOnlyJob" in r

    def test_repr_with_fields(self):
        """Repr includes id, estimate, cost when set."""
        job = SyncOnlyJob("x")
        job._id = "abc"
        job._estimate = 1.5
        job._cost = 2.5
        r = repr(job)
        assert "abc" in r
        assert "$1.50" in r
        assert "$2.50" in r


# ===========================================================================
# Mixin tests
# ===========================================================================


class TestQuoteMixin:
    """QuoteMixin.quote() guards and delegates to _quote_impl."""

    def test_default_quote_impl_raises(self):
        """Unoverridden _quote_impl() raises NotImplementedError."""
        mixin = QuoteMixin()
        with pytest.raises(NotImplementedError):
            mixin.quote()

    def test_quote_blocked_when_already_quoted(self):
        """quote() raises ValueError when status is already 'Quoted'."""
        job = AsyncJob("x")
        job.status = "Quoted"
        job._id = "exec-123"
        with pytest.raises(ValueError, match="quotation already exists"):
            job.quote()

    def test_quote_blocked_when_id_is_set(self):
        """quote() raises ValueError when an execution ID is already assigned."""
        job = AsyncJob("x")
        job._id = "exec-456"
        job._set_status("Created")
        with pytest.raises(ValueError, match="already has id"):
            job.quote()

    def test_quote_allowed_when_fresh(self):
        """quote() passes the guard when status is None and id is None."""
        job = AsyncJob("x")
        with pytest.raises(NotImplementedError):
            job.quote()


class TestSyncExecutableMixin:
    """SyncExecutableMixin.run() default raises NotImplementedError."""

    def test_default_run_raises(self):
        """Unoverridden run() raises NotImplementedError."""
        mixin = SyncExecutableMixin()
        with pytest.raises(NotImplementedError):
            mixin.run()


class TestAsyncExecutableMixin:
    """AsyncExecutableMixin lifecycle methods."""

    def test_cancel_no_id_raises(self):
        """cancel() with no execution ID raises ValueError."""
        job = AsyncJob("x")
        with pytest.raises(ValueError, match="id is None"):
            job.cancel()

    def test_sync_no_id_raises(self):
        """sync() with no execution ID raises ValueError."""
        job = AsyncJob("x")
        with pytest.raises(ValueError, match="id is None"):
            job.sync()

    def test_cancel_wrong_state_raises(self):
        """cancel() from a non-cancellable state raises ValueError."""
        job = AsyncJob("x")
        job._id = "some-id"
        job._set_status("Created")
        job._set_status("Running")
        job._set_status("Succeeded")
        with pytest.raises(ValueError, match="Cannot cancel"):
            job.cancel()

    @pytest.mark.parametrize(
        "blocked_status",
        ["Created", "Queued", "Running", "Succeeded", "Failed", "Cancelled"],
    )
    def test_start_blocked_when_already_active(self, blocked_status):
        """start() raises ValueError when status is not None or 'Quoted'."""
        job = AsyncJob("x")
        job.status = blocked_status
        with pytest.raises(ValueError, match="Cannot start"):
            job.start()

    def test_start_allowed_when_status_is_none(self):
        """start() with status None calls _start_impl."""
        job = AsyncJob("x")
        assert job.status is None
        with pytest.raises(NotImplementedError):
            job.start()

    def test_start_quoted_calls_confirm_and_sync(self):
        """start() with status 'Quoted' confirms the existing execution and syncs."""
        from unittest.mock import MagicMock, patch

        job = AsyncJob("x")
        job.status = "Quoted"
        job._id = "exec-123"

        mock_client = MagicMock()
        job.client = mock_client

        with patch.object(job, "sync") as mock_sync:
            job.start()

        mock_client.executions.confirm.assert_called_once_with(execution_id="exec-123")
        mock_sync.assert_called_once()


# ===========================================================================
# PocketFinder tests
# ===========================================================================


class TestPocketFinderConstruction:
    """PocketFinder construction and attribute access."""

    def test_defaults(self, protein):
        """Fresh PocketFinder has None for id, estimate, cost."""
        pf = PocketFinder(protein)
        assert pf.protein is protein
        assert pf.pocket_count == 1
        assert pf.pocket_min_size == 30
        assert pf.id is None
        assert pf.estimate is None
        assert pf.cost is None

    def test_custom_params(self, protein):
        """Constructor accepts pocket_count and pocket_min_size."""
        pf = PocketFinder(protein, pocket_count=5, pocket_min_size=50)
        assert pf.pocket_count == 5
        assert pf.pocket_min_size == 50

    def test_protein_immutable(self, protein):
        """Protein cannot be reassigned after construction."""
        pf = PocketFinder(protein)
        with pytest.raises(AttributeError, match="protein"):
            pf.protein = protein

    def test_pocket_count_immutable(self, protein):
        """pocket_count cannot be reassigned after construction."""
        pf = PocketFinder(protein)
        with pytest.raises(AttributeError, match="pocket_count"):
            pf.pocket_count = 10

    def test_tool_key(self, protein):
        """tool_key matches the platform constant."""
        pf = PocketFinder(protein)
        assert pf.tool_key == "deeporigin.pocketfinder"


class TestPocketFinderNoAsyncMethods:
    """PocketFinder (sync-only) should not expose async lifecycle methods."""

    def test_no_status_attribute(self, protein):
        """PocketFinder instances have no status attribute."""
        pf = PocketFinder(protein)
        assert not hasattr(pf, "status")

    def test_no_from_id(self):
        """PocketFinder class has no from_id classmethod."""
        assert not hasattr(PocketFinder, "from_id")

    def test_no_start(self, protein):
        """PocketFinder instances have no start method."""
        pf = PocketFinder(protein)
        assert not hasattr(pf, "start")


# ===========================================================================
# SystemPrep tests
# ===========================================================================


class TestSystemPrepConstruction:
    """SystemPrep construction and attribute access."""

    def test_defaults(self, protein, ligand):
        """Fresh SystemPrep has None for output paths and estimate/cost."""
        sp = SystemPrep(protein=protein, ligand=ligand)
        assert sp.protein is protein
        assert sp.ligand is ligand
        assert sp.binding_xml_path is None
        assert sp.solvation_xml_path is None
        assert sp.system_pdb_path is None
        assert sp.id is None
        assert sp.estimate is None
        assert sp.cost is None

    def test_custom_params(self, protein, ligand):
        """Constructor accepts padding, retain_waters, box_size."""
        sp = SystemPrep(
            protein=protein,
            ligand=ligand,
            padding=2.0,
            retain_waters=True,
            box_size=[3.0, 3.0, 3.0],
        )
        assert sp._padding == 2.0
        assert sp._retain_waters is True
        assert sp._box_size == [3.0, 3.0, 3.0]

    def test_protein_immutable(self, protein, ligand):
        """Protein cannot be reassigned after construction."""
        sp = SystemPrep(protein=protein, ligand=ligand)
        with pytest.raises(AttributeError, match="protein"):
            sp.protein = protein

    def test_tool_key(self, protein, ligand):
        """tool_key matches the platform constant."""
        sp = SystemPrep(protein=protein, ligand=ligand)
        assert sp.tool_key == "deeporigin.system-prep"

    def test_rbfe_mode_ligand1_ligand2(self, protein, ligand):
        """Constructor with ligand1 and ligand2 exposes both ligands (RBFE mode)."""
        lig2 = Ligand.from_smiles("CC(=O)O", name="acetate")
        lig2.id = _LIGAND2_ID
        sp = SystemPrep(protein=protein, ligand1=ligand, ligand2=lig2)
        assert sp.ligand is None
        assert sp.ligand1 is ligand
        assert sp.ligand2 is lig2

    def test_constructor_requires_ligand_or_ligand_pair(self, protein, ligand):
        """ValueError when neither ligand nor (ligand1 and ligand2) is provided."""
        with pytest.raises(ValueError, match="Provide either ligand"):
            SystemPrep(protein=protein)

    def test_constructor_rejects_only_ligand1(self, protein, ligand):
        """ValueError when only ligand1 is provided."""
        with pytest.raises(ValueError, match="Provide either ligand"):
            SystemPrep(protein=protein, ligand1=ligand)

    def test_constructor_rejects_only_ligand2(self, protein, ligand):
        """ValueError when only ligand2 is provided."""
        with pytest.raises(ValueError, match="Provide either ligand"):
            SystemPrep(protein=protein, ligand2=ligand)

    def test_constructor_rejects_both_abfe_and_rbfe(self, protein, ligand):
        """ValueError when both ligand and ligand1/ligand2 are provided."""
        lig2 = Ligand.from_smiles("CC(=O)O", name="acetate")
        lig2.id = _LIGAND2_ID
        with pytest.raises(ValueError, match="Provide either ligand"):
            SystemPrep(protein=protein, ligand=ligand, ligand1=ligand, ligand2=lig2)

    def test_constructor_requires_protein_id(self, ligand):
        """ValueError when protein has no id."""
        p = Protein.from_file(str(_BRD_PDB))
        assert p.id is None
        with pytest.raises(ValueError, match="protein must have an id"):
            SystemPrep(protein=p, ligand=ligand)

    def test_constructor_requires_ligand_id(self, protein):
        """ValueError when ligand has no id (ABFE mode)."""
        lig = Ligand.from_smiles("CCO", name="ethanol")
        assert lig.id is None
        with pytest.raises(ValueError, match="ligand must have an id"):
            SystemPrep(protein=protein, ligand=lig)

    def test_constructor_requires_ligand1_ligand2_ids_in_rbfe(self, protein, ligand):
        """ValueError when ligand1 or ligand2 has no id in RBFE mode."""
        lig2 = Ligand.from_smiles("CC(=O)O", name="acetate")
        # lig2.id not set
        with pytest.raises(ValueError, match="ligand1 and ligand2 must have an id"):
            SystemPrep(protein=protein, ligand1=ligand, ligand2=lig2)


class TestSystemPrepNoAsyncMethods:
    """SystemPrep (sync-only) should not expose async lifecycle methods."""

    def test_no_status_attribute(self, protein, ligand):
        """SystemPrep instances have no status attribute."""
        sp = SystemPrep(protein=protein, ligand=ligand)
        assert not hasattr(sp, "status")

    def test_no_from_id(self):
        """SystemPrep class has no from_id classmethod."""
        assert not hasattr(SystemPrep, "from_id")

    def test_no_start(self, protein, ligand):
        """SystemPrep instances have no start method."""
        sp = SystemPrep(protein=protein, ligand=ligand)
        assert not hasattr(sp, "start")


class TestSystemPrepRunParsesOutputs:
    """run() parses function outputs, sets paths on SystemPrep, and returns PreparedSystem."""

    def test_run_sets_paths_and_returns_prepared_system(self, protein, ligand):
        """When for_abfe() returns completed result with system dict, run() sets paths and returns PreparedSystem."""
        mock_outputs = {
            "system": {
                "binding_xml_file_path": "some/dir/bsm_system.xml",
                "solvation_xml_ligand1_file_path": "some/dir/solvation_ligand1.xml",
                "system_pdb_file_path": "some/dir/system.pdb",
            },
        }
        mock_result = FunctionResult(
            [
                {
                    "id": "test-exec-id",
                    "status": "Completed",
                    "functionOutputs": mock_outputs,
                    "quotationResult": {"successfulQuotations": [{"priceTotal": 1.5}]},
                }
            ]
        )

        with (
            patch("deeporigin.functions.sysprep.for_abfe", return_value=mock_result),
            patch(
                "deeporigin.platform.results.Results.get_prepared_systems",
                return_value={"data": []},
            ),
        ):
            sp = SystemPrep(protein=protein, ligand=ligand)
            out = sp.run()

        assert isinstance(out, PreparedSystem)
        assert out.binding_xml_path == "some/dir/bsm_system.xml"
        assert out.solvation_xml_path == "some/dir/solvation_ligand1.xml"
        assert out.system_pdb_path == "some/dir/system.pdb"
        assert sp.binding_xml_path == "some/dir/bsm_system.xml"
        assert sp.solvation_xml_path == "some/dir/solvation_ligand1.xml"
        assert sp.system_pdb_path == "some/dir/system.pdb"
        assert sp.cost == 1.5

    def test_run_rbfe_calls_rbfe_and_sets_paths(self, protein, ligand):
        """When in RBFE mode, run() calls for_rbfe() and returns PreparedSystem with paths."""
        lig2 = Ligand.from_smiles("CC(=O)O", name="acetate")
        lig2.id = _LIGAND2_ID
        mock_outputs = {
            "system": {
                "binding_xml_file_path": "rbfe/dir/bsm_system.xml",
                "solvation_xml_ligand1_file_path": "rbfe/dir/solvation_ligand1.xml",
                "system_pdb_file_path": "rbfe/dir/system.pdb",
            },
        }
        mock_result = FunctionResult(
            [
                {
                    "id": "test-exec-id-rbfe",
                    "status": "Completed",
                    "functionOutputs": mock_outputs,
                    "quotationResult": {"successfulQuotations": [{"priceTotal": 2.0}]},
                }
            ]
        )
        with (
            patch("deeporigin.functions.sysprep.for_rbfe", return_value=mock_result),
            patch(
                "deeporigin.platform.results.Results.get_prepared_systems",
                return_value={"data": []},
            ),
        ):
            sp = SystemPrep(protein=protein, ligand1=ligand, ligand2=lig2)
            out = sp.run()
        assert isinstance(out, PreparedSystem)
        assert out.binding_xml_path == "rbfe/dir/bsm_system.xml"
        assert sp.binding_xml_path == "rbfe/dir/bsm_system.xml"
        assert sp.solvation_xml_path == "rbfe/dir/solvation_ligand1.xml"
        assert sp.system_pdb_path == "rbfe/dir/system.pdb"
        assert sp.cost == 2.0

    def test_run_calls_function_and_returns_prepared_system(self, protein, ligand):
        """run() calls the platform sysprep function and returns PreparedSystem."""
        mock_outputs = {
            "system": {
                "binding_xml_file_path": "fresh/bsm_system.xml",
                "solvation_xml_ligand1_file_path": "fresh/solvation_ligand1.xml",
                "system_pdb_file_path": "fresh/system.pdb",
            },
        }
        mock_result = FunctionResult(
            [
                {
                    "id": "test-exec-id-fresh",
                    "status": "Completed",
                    "functionOutputs": mock_outputs,
                    "quotationResult": {"successfulQuotations": [{"priceTotal": 0.5}]},
                }
            ]
        )
        with (
            patch("deeporigin.functions.sysprep.for_abfe", return_value=mock_result),
            patch(
                "deeporigin.platform.results.Results.get_prepared_systems",
                return_value={"data": []},
            ),
        ):
            sp = SystemPrep(protein=protein, ligand=ligand)
            out = sp.run()
        assert isinstance(out, PreparedSystem)
        assert out.binding_xml_path == "fresh/bsm_system.xml"
        assert sp.binding_xml_path == "fresh/bsm_system.xml"
        assert sp.solvation_xml_path == "fresh/solvation_ligand1.xml"
        assert sp.system_pdb_path == "fresh/system.pdb"

    def test_get_results_returns_prepared_systems_from_platform(self, protein, ligand):
        """get_results() calls PreparedSystem.from_result with instance params."""
        mock_systems = [
            PreparedSystem(
                binding_xml_path="p/bsm.xml",
                solvation_xml_path="p/solv.xml",
                system_pdb_path="p/system.pdb",
            )
        ]
        with patch(
            "deeporigin.drug_discovery.structures.prepared_system.PreparedSystem.from_result",
            return_value=mock_systems,
        ) as from_result:
            sp = SystemPrep(protein=protein, ligand=ligand)
            results = sp.get_results()
        from_result.assert_called_once()
        call_kw = from_result.call_args[1]
        assert call_kw["protein_id"] == protein.id
        assert call_kw["ligand1_id"] == ligand.id
        assert call_kw["ligand2_id"] is None
        assert results == mock_systems
