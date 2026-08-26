"""Tests for :mod:`deeporigin.drug_discovery.protein_prep`."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from deeporigin.drug_discovery import Protein, ProteinPrep
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from tests.conftest import check_tool_exists

_SHA256 = "a" * 64
_SAMPLE_SELECTION = {
    "analyzer_version": "1.0.0",
    "decisions": {"chain:A": "keep", "ligand:LIG:A:100": "skip"},
    "source_sha256": _SHA256,
}
_DRAFT_SELECTION = {
    "analyzer_version": "1.0.0",
    "decisions": {"chain:A": "keep", "ligand:LIG:A:100": "review"},
    "source_sha256": _SHA256,
}
_SAMPLE_RECOMMENDATION = {
    "analyzer_version": "1.0.0",
    "chain_id_mapping": {},
    "components": [
        {
            "author": {"chain_id": "A"},
            "id": "chain:A",
            "kind": "chain",
            "label": "Chain A",
            "reason": "Ordinary protein chain",
            "reason_code": "ordinary_protein_chain",
            "recommendation": "keep",
            "subtype": "protein",
        },
        {
            "author": {"chain_id": "A", "resname": "LIG", "resseq": 100},
            "id": "ligand:LIG:A:100",
            "kind": "ligand",
            "label": "LIG",
            "reason": "Ambiguous ligand",
            "reason_code": "ambiguous_ligand",
            "recommendation": "review",
            "subtype": "small_molecule",
        },
    ],
    "source_sha256": _SHA256,
}


def _protein_with_remote(*, pdb_id: str | None = "1EBY") -> Protein:
    """Return a protein whose remote path avoids upload in payload tests."""
    protein = Protein(name="test", pdb_id=pdb_id)
    protein.remote_path = "testing/brd.pdb"
    return protein


def _execution_fixture(name: str) -> dict:
    """Load a Protein Prep execution fixture."""
    path = Path(__file__).parent / "fixtures/executions" / name
    return json.loads(path.read_text())


def test_protein_prep_constructor_has_configuration_defaults() -> None:
    """Construction creates unbound configuration with loops enabled."""
    protein = Protein(name="test", pdb_id="1EBY")
    prep = ProteinPrep(protein=protein)

    assert prep.protein is protein
    assert prep.pdb_id == "1EBY"
    assert prep.selection is None
    assert prep.recommendation is None
    assert prep.model_missing_loops is True
    assert prep.id is None
    assert not hasattr(prep, "action")


def test_protein_is_constructor_only() -> None:
    """The input protein cannot be replaced after construction."""
    prep = ProteinPrep(protein=Protein(name="test"))

    with pytest.raises(AttributeError):
        prep.protein = Protein(name="other")  # type: ignore[misc]


def test_pdb_id_is_mutable_before_prepare() -> None:
    """PDB ID can be corrected or cleared before durable submission."""
    prep = ProteinPrep(protein=Protein(name="test"))

    prep.pdb_id = "2ABC"
    assert prep.pdb_id == "2ABC"
    prep.pdb_id = None
    assert prep.pdb_id is None


@pytest.mark.parametrize("pdb_id", ["1EB", "1EBYX", "1EB!"])
def test_protein_prep_rejects_invalid_pdb_id(pdb_id: str) -> None:
    """PDB IDs must contain exactly four alphanumeric characters."""
    protein = Protein(name="test")

    with pytest.raises(ValueError, match="4-character"):
        ProteinPrep(protein=protein, pdb_id=pdb_id)


def test_selection_assignment_accepts_review_and_copies() -> None:
    """Draft Selection assignment accepts review without retaining aliases."""
    selection = {
        "analyzer_version": "1.0.0",
        "decisions": {
            "chain:A": "keep",
            "ligand:LIG:A:100": "review",
        },
        "source_sha256": _SHA256,
    }
    prep = ProteinPrep(protein=Protein(name="test"), selection=selection)

    selection["decisions"]["ligand:LIG:A:100"] = "skip"
    assert prep.selection == _DRAFT_SELECTION


def test_selection_getter_returns_defensive_copy() -> None:
    """Nested mutation of a Selection read does not change the object."""
    prep = ProteinPrep(
        protein=Protein(name="test"),
        selection=_DRAFT_SELECTION,
    )

    selection = prep.selection
    assert selection is not None
    selection["decisions"]["ligand:LIG:A:100"] = "skip"
    assert prep.selection == _DRAFT_SELECTION


def test_recommendation_getter_returns_defensive_copy() -> None:
    """Nested mutation of recommendation evidence does not change the object."""
    prep = ProteinPrep(protein=Protein(name="test"))
    prep._recommendation = _SAMPLE_RECOMMENDATION

    recommendation = prep.recommendation
    assert recommendation is not None
    recommendation["components"][0]["label"] = "changed"
    assert prep.recommendation is not None
    assert prep.recommendation["components"][0]["label"] == "Chain A"


def test_keep_and_skip_change_only_named_components() -> None:
    """Domain editing methods preserve decisions not named by the caller."""
    prep = ProteinPrep(
        protein=Protein(name="test"),
        selection=_DRAFT_SELECTION,
    )

    prep.skip(["ligand:LIG:A:100"])
    prep.keep(["chain:A"])

    assert prep.selection == _SAMPLE_SELECTION


@pytest.mark.parametrize("method_name", ["keep", "skip"])
def test_keep_and_skip_reject_bare_string(method_name: str) -> None:
    """Decision methods require an iterable container, not a bare string."""
    prep = ProteinPrep(
        protein=Protein(name="test"),
        selection=_DRAFT_SELECTION,
    )
    method = getattr(prep, method_name)

    with pytest.raises(TypeError, match="iterable"):
        method("chain:A")


def test_keep_reports_all_unknown_component_ids() -> None:
    """Decision editing rejects unknown IDs without partially mutating."""
    prep = ProteinPrep(
        protein=Protein(name="test"),
        selection=_DRAFT_SELECTION,
    )

    with pytest.raises(ValueError, match="missing:A, missing:B"):
        prep.keep(["missing:B", "missing:A"])
    assert prep.selection == _DRAFT_SELECTION


def test_keep_requires_selection() -> None:
    """Decision editing guides callers to obtain a Selection first."""
    prep = ProteinPrep(protein=Protein(name="test"))

    with pytest.raises(ValueError, match=r"recommend\(\)"):
        prep.keep(["chain:A"])


def test_prepare_requires_selection_before_upload() -> None:
    """Prepare cannot begin until recommendation or assignment provides Selection."""
    prep = ProteinPrep(
        protein=Protein(name="test"),
        model_missing_loops=False,
    )

    with pytest.raises(ValueError, match="no selection"):
        prep.run()


def test_prepare_lists_unresolved_reviews() -> None:
    """Prepare reports every unresolved review component."""
    selection = {
        **_DRAFT_SELECTION,
        "decisions": {
            "chain:A": "review",
            "ligand:LIG:A:100": "review",
        },
    }
    prep = ProteinPrep(
        protein=Protein(name="test"),
        selection=selection,
        model_missing_loops=False,
    )

    with pytest.raises(ValueError, match=r"chain:A.*ligand:LIG:A:100"):
        prep.run()


def test_run_requires_loops_off() -> None:
    """Blocking prepare directs loops-on callers to start."""
    prep = ProteinPrep(
        protein=Protein(name="test", pdb_id="1EBY"),
        selection=_SAMPLE_SELECTION,
    )

    with pytest.raises(ValueError, match=r"Use start\(\)"):
        prep.run()


def test_start_requires_pdb_id_when_loops_enabled() -> None:
    """Asynchronous loops-on prepare requires a PDB ID."""
    prep = ProteinPrep(
        protein=Protein(name="test"),
        selection=_SAMPLE_SELECTION,
    )

    with pytest.raises(ValueError, match="pdb_id is required"):
        prep.start()


def test_configuration_freezes_permanently_after_id() -> None:
    """All supported configuration mutation fails once an ID is present."""
    prep = ProteinPrep(
        protein=Protein(name="test", pdb_id="1EBY"),
        selection=_SAMPLE_SELECTION,
    )
    prep._id = "exec-locked"

    with pytest.raises(AttributeError, match="execution id is already set"):
        prep.model_missing_loops = False
    with pytest.raises(AttributeError, match="execution id is already set"):
        prep.pdb_id = "2ABC"
    with pytest.raises(AttributeError, match="execution id is already set"):
        prep.selection = _SAMPLE_SELECTION
    with pytest.raises(AttributeError, match="execution id is already set"):
        prep.keep(["chain:A"])
    with pytest.raises(AttributeError, match="execution id is already set"):
        prep.recommend()


def test_removed_api_is_absent() -> None:
    """The old two-object and quote-oriented surface is removed."""
    prep = ProteinPrep(protein=Protein(name="test"))

    assert not hasattr(prep, "as_prepare")
    assert not hasattr(prep, "from_recommendation")
    assert not hasattr(prep, "get_recommendation")
    assert not hasattr(prep, "selection_from_recommendation")
    assert list(inspect.signature(prep.run).parameters) == []
    assert list(inspect.signature(prep.start).parameters) == []


def test_recommend_payload_is_blocking_and_minimal() -> None:
    """Internal recommend payload contains only action and protein input."""
    protein = _protein_with_remote()
    protein.id = "prot-1"
    prep = ProteinPrep(protein=protein)

    payload = prep._make_protein_prep_payload(action="recommend", sync=True)

    assert payload == {
        "inputs": {
            "action": "recommend",
            "protein": {"file_path": "testing/brd.pdb", "id": "prot-1"},
        },
        "metadata": {},
        "outputs": {},
        "sync": True,
    }


def test_prepare_payload_contains_resolved_selection() -> None:
    """Prepare payload contains current configuration and no billing fields."""
    prep = ProteinPrep(
        protein=_protein_with_remote(),
        pdb_id="1EBY",
        selection=_SAMPLE_SELECTION,
    )

    payload = prep._make_protein_prep_payload(action="prepare", sync=False)

    assert payload["sync"] is False
    assert payload["inputs"]["action"] == "prepare"
    assert payload["inputs"]["selection"] == _SAMPLE_SELECTION
    assert payload["inputs"]["pdb_id"] == "1EBY"
    assert "model_missing_loops" not in payload["inputs"]
    assert "approveAmount" not in payload


def test_loops_off_payload_omits_pdb_id() -> None:
    """Loops-off prepare sends the opt-out without requiring a PDB ID."""
    prep = ProteinPrep(
        protein=_protein_with_remote(pdb_id=None),
        selection=_SAMPLE_SELECTION,
        model_missing_loops=False,
    )

    payload = prep._make_protein_prep_payload(action="prepare", sync=True)

    assert payload["inputs"]["model_missing_loops"] is False
    assert "pdb_id" not in payload["inputs"]


def test_repr_uses_user_concepts_not_action() -> None:
    """Text display summarizes configuration without exposing action."""
    prep = ProteinPrep(
        protein=Protein(name="brd", pdb_id="1EBY"),
        selection=_DRAFT_SELECTION,
    )
    prep._recommendation = _SAMPLE_RECOMMENDATION

    text = repr(prep)

    assert "action" not in text
    assert "1 keep, 1 review, 0 skip" in text
    assert "recommendation" in text
    assert "available" in text


def test_repr_adds_durable_execution_state() -> None:
    """Text display adds ID, status, and progress for a bound object."""
    prep = ProteinPrep(
        protein=Protein(name="brd", pdb_id="1EBY"),
        selection=_SAMPLE_SELECTION,
    )
    prep._id = "exec-abc"
    prep.status = "Running"
    prep.progress = {"percent": 25}

    text = repr(prep)

    assert "exec-abc" in text
    assert "Running" in text
    assert "25" in text


def test_from_dto_rehydrates_prepare_without_public_action(
    client: DeepOriginClient,
) -> None:
    """Historical prepare DTOs retain inputs and private operation kind."""
    dto = _execution_fixture("protein-prep-test-execution.json")

    prep = ProteinPrep.from_dto(dto, client=client)

    assert prep.id == dto["executionId"]
    assert prep._operation_kind == "prepare"
    assert prep.selection == _SAMPLE_SELECTION
    assert prep.recommendation is None
    assert not hasattr(prep, "action")


def test_from_dto_rehydrates_recommendation(
    client: DeepOriginClient,
) -> None:
    """Historical recommend DTOs expose evidence and draft Selection."""
    dto = _execution_fixture("protein-prep-recommend-execution.json")

    prep = ProteinPrep.from_dto(dto, client=client)

    assert prep._operation_kind == "recommend"
    assert prep.recommendation is not None
    assert prep.selection == _DRAFT_SELECTION
    with pytest.raises(DeepOriginException, match="did not produce"):
        prep.get_results(dto)


def test_from_dto_v1_prepare_still_gets_results(
    client: DeepOriginClient,
) -> None:
    """Legacy inputs without action continue to rehydrate as prepare."""
    dto = _execution_fixture("protein-prep-test-execution.json")
    dto["userInputs"] = {
        "keep_chain_ids": ["A"],
        "pdb_id": "1EBY",
        "protein": {"file_path": "testing/brd.pdb", "id": "brd"},
    }

    prep = ProteinPrep.from_dto(dto, client=client)
    prepared = prep.get_results(dto)

    assert prep._operation_kind == "prepare"
    assert isinstance(prepared, Protein)
    assert prepared.remote_path == "testing/brd.pdb"


def test_get_results_requires_durable_id() -> None:
    """Result retrieval is unavailable before prepare submission."""
    prep = ProteinPrep(protein=Protein(name="test"))

    with pytest.raises(ValueError, match="no execution"):
        prep.get_results()


def test_recommend_updates_same_object_without_id(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """Blocking recommendation mutates configuration but does not bind ID."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
    )
    prep = ProteinPrep(protein=registered_protein, client=client)

    result = prep.recommend()

    assert result is None
    assert prep.id is None
    assert prep.status is None
    assert prep.recommendation is not None
    assert prep.selection is not None
    assert prep.selection["decisions"]["chain:A"] == "keep"
    assert prep.selection["decisions"]["ligand:LIG:A:100"] == "review"


def test_recommend_then_run_loops_off_returns_protein(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """One object recommends, resolves review, and prepares synchronously."""
    prep = ProteinPrep(
        protein=registered_protein,
        model_missing_loops=False,
        client=client,
    )
    prep.recommend()
    prep.skip(["ligand:LIG:A:100"])

    prepared = prep.run()

    assert isinstance(prepared, Protein)
    assert prepared.id is None
    assert prepared.remote_path == "testing/brd.pdb"
    assert prep.id is not None
    if client.env == "local":
        assert is_success_status(prep.status)
        inputs = (prep._dto or {}).get("userInputs") or {}
        assert inputs["action"] == "prepare"
        assert inputs["model_missing_loops"] is False


def test_start_accepts_resolved_loops_off_prepare(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """Loops-off preparation can use the asynchronous interface."""
    prep = ProteinPrep(
        protein=registered_protein,
        selection=_SAMPLE_SELECTION,
        model_missing_loops=False,
        client=client,
    )

    result = prep.start()

    assert result is None
    assert prep.id is not None
    if client.env == "local":
        assert is_success_status(prep.status)
