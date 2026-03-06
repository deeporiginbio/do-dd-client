"""Tests for the jobs-centric base classes, mixins, and PocketFinder."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.drug_discovery.execution import Execution
from deeporigin.drug_discovery.execution_mixins import (
    AsyncExecutableMixin,
    QuoteMixin,
    SyncExecutableMixin,
)
from deeporigin.drug_discovery.pocket_finder import PocketFinder
from deeporigin.platform.client import DeepOriginClient

_BRD_PDB = Path(os.path.join(BRD_DATA_DIR, "brd.pdb"))


# ---------------------------------------------------------------------------
# Helpers -- minimal subclasses for testing the base machinery
# ---------------------------------------------------------------------------


class SyncOnlyJob(Execution, QuoteMixin, SyncExecutableMixin):
    """Minimal sync-only execution for testing."""

    tool_key = "test.sync"
    tool_version = "0.0.1"
    _immutable_fields = frozenset({"name"})

    def __init__(self, name: str) -> None:
        super().__init__()
        with self._system_update():
            self.name = name


class AsyncJob(Execution, QuoteMixin, AsyncExecutableMixin):
    """Minimal async execution for testing."""

    tool_key = "test.async"
    tool_version = "0.0.1"
    _immutable_fields = frozenset({"name"})

    def __init__(self, name: str) -> None:
        super().__init__()
        self._init_async()
        with self._system_update():
            self.name = name


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def protein():
    """Create a real Protein from the bundled BRD data."""
    return Protein.from_file(str(_BRD_PDB))


# ===========================================================================
# Execution tests
# ===========================================================================


class TestExecutionReadOnly:
    """Read-only field enforcement on Execution."""

    def test_id_blocked_outside_system_update(self):
        """Assigning id directly raises AttributeError."""
        job = SyncOnlyJob("x")
        with pytest.raises(AttributeError, match="id"):
            job.id = "should-fail"

    def test_estimate_blocked_outside_system_update(self):
        """Assigning estimate directly raises AttributeError."""
        job = SyncOnlyJob("x")
        with pytest.raises(AttributeError, match="estimate"):
            job.estimate = 1.23

    def test_cost_blocked_outside_system_update(self):
        """Assigning cost directly raises AttributeError."""
        job = SyncOnlyJob("x")
        with pytest.raises(AttributeError, match="cost"):
            job.cost = 4.56

    def test_system_update_allows_writes(self):
        """Within _system_update, writes to protected fields succeed."""
        job = SyncOnlyJob("x")
        with job._system_update():
            job.id = "abc"
            job.estimate = 1.0
            job.cost = 2.0
        assert job.id == "abc"
        assert job.estimate == 1.0
        assert job.cost == 2.0

    def test_system_update_re_locks(self):
        """After exiting _system_update, writes are blocked again."""
        job = SyncOnlyJob("x")
        with job._system_update():
            job.id = "abc"
        with pytest.raises(AttributeError, match="id"):
            job.id = "def"

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
        """Once in Succeeded, no further transitions are allowed."""
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
        with job._system_update():
            job.id = "abc"
            job.estimate = 1.5
            job.cost = 2.5
        r = repr(job)
        assert "abc" in r
        assert "$1.50" in r
        assert "$2.50" in r


# ===========================================================================
# Mixin tests
# ===========================================================================


class TestQuoteMixin:
    """QuoteMixin.quote() default raises NotImplementedError."""

    def test_default_quote_raises(self):
        """Unoverridden quote() raises NotImplementedError."""
        mixin = QuoteMixin()
        with pytest.raises(NotImplementedError):
            mixin.quote()


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

    def test_refresh_no_id_raises(self):
        """refresh() with no execution ID raises ValueError."""
        job = AsyncJob("x")
        with pytest.raises(ValueError, match="id is None"):
            job.refresh()

    def test_cancel_wrong_state_raises(self):
        """cancel() from a non-cancellable state raises ValueError."""
        job = AsyncJob("x")
        with job._system_update():
            job.id = "some-id"
            job.status = "Succeeded"
        with pytest.raises(ValueError, match="Cannot cancel"):
            job.cancel()

    def test_list_delegates_to_platform(self):
        """list() calls through to platform JobList.list()."""
        mock_client = MagicMock()
        mock_job_list = MagicMock()

        with (
            patch(
                "deeporigin.platform.client.DeepOriginClient.get",
                return_value=mock_client,
            ),
            patch(
                "deeporigin.platform.job.JobList.list",
                return_value=mock_job_list,
            ),
        ):
            result = AsyncJob.list()
            assert result is mock_job_list


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


class TestPocketFinderQuote:
    """PocketFinder.quote() populates estimate."""

    def test_quote_sets_estimate(self, protein):
        """quote() calls the functions API and sets self.estimate."""
        pf = PocketFinder(protein, client=MagicMock(spec=DeepOriginClient))

        mock_result = MagicMock()
        mock_result.estimate = 0.42

        with patch(
            "deeporigin.functions.pocket_finder.find_pockets",
            return_value=mock_result,
        ) as mock_fn:
            pf.quote()
            mock_fn.assert_called_once()
            call_kwargs = mock_fn.call_args[1]
            assert call_kwargs["quote"] is True

        assert pf.estimate == 0.42


class TestPocketFinderRun:
    """PocketFinder.run() returns pockets and sets cost."""

    def test_run_returns_pockets_and_sets_cost(self, protein):
        """run() delegates to the functions API and sets cost."""
        pf = PocketFinder(protein, client=MagicMock(spec=DeepOriginClient))

        mock_result = MagicMock()
        mock_result.cost = 0.99
        mock_pockets = [MagicMock(), MagicMock()]

        with (
            patch(
                "deeporigin.functions.pocket_finder.find_pockets",
                return_value=mock_result,
            ),
            patch(
                "deeporigin.drug_discovery.structures.protein._make_pockets_from_result",
                return_value=mock_pockets,
            ),
        ):
            result = pf.run()

        assert result == mock_pockets
        assert pf.cost == 0.99


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
