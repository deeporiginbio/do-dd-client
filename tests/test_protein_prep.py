"""Tests for :mod:`deeporigin.drug_discovery.protein_prep`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeporigin.drug_discovery import Protein, ProteinPrep
from deeporigin.drug_discovery.protein_prep import selection_from_recommendation
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from deeporigin.utils.constants import (
    PROTEIN_PREP_PDB_ID_REQUIRED_MSG,
    PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG,
    PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG,
)
from tests.conftest import check_tool_exists

_SHA256 = "a" * 64
_SAMPLE_SELECTION = {
    "analyzer_version": "1.0.0",
    "decisions": {"chain:A": "keep", "ligand:LIG:A:100": "skip"},
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
    """In-memory protein with a remote path so payload tests skip upload."""
    protein = Protein(name="test", pdb_id=pdb_id)
    protein.remote_path = "testing/brd.pdb"
    return protein


def test_protein_prep_defaults_to_recommend() -> None:
    """Constructor without selection is a recommend run; pdb_id is optional."""
    protein = Protein(name="test")
    prep = ProteinPrep(protein)
    assert prep.action == "recommend"
    assert prep.pdb_id is None
    assert prep.selection is None
    assert prep.model_missing_loops is True


def test_protein_prep_infers_pdb_id_from_protein() -> None:
    """Constructor stores protein.pdb_id for later prepare."""
    protein = Protein(name="test", pdb_id="1EBY")
    prep = ProteinPrep(protein)
    assert prep.pdb_id == "1EBY"


def test_protein_prep_prepare_requires_pdb_id_when_loops_on() -> None:
    """Prepare with loop modelling raises when neither source has pdb_id."""
    protein = Protein(name="test")
    with pytest.raises(ValueError, match="pdb_id is required"):
        ProteinPrep(protein, selection=_SAMPLE_SELECTION)


def test_protein_prep_prepare_loops_off_allows_missing_pdb_id() -> None:
    """Prepare with model_missing_loops=False does not require pdb_id."""
    protein = Protein(name="test")
    prep = ProteinPrep(
        protein,
        selection=_SAMPLE_SELECTION,
        model_missing_loops=False,
    )
    assert prep.action == "prepare"
    assert prep.pdb_id is None
    assert prep.model_missing_loops is False


def test_protein_prep_rejects_invalid_pdb_id() -> None:
    """Constructor rejects PDB IDs that are not 4 alphanumeric characters."""
    protein = Protein(name="test")
    with pytest.raises(ValueError, match="4-character"):
        ProteinPrep(protein, pdb_id="1EB")
    with pytest.raises(ValueError, match="4-character"):
        ProteinPrep(protein, pdb_id="1EBYX")
    with pytest.raises(ValueError, match="4-character"):
        ProteinPrep(protein, pdb_id="1EB!")


def test_protein_prep_explicit_pdb_id_overrides_protein() -> None:
    """Constructor pdb_id= wins over protein.pdb_id."""
    protein = Protein(name="test", pdb_id="1ABC")
    prep = ProteinPrep(protein, pdb_id="2XYZ")
    assert prep.pdb_id == "2XYZ"


def test_protein_prep_recommend_rejects_loops_off() -> None:
    """model_missing_loops=False is invalid on a recommend run."""
    protein = Protein(name="test")
    with pytest.raises(ValueError, match="model_missing_loops=False"):
        ProteinPrep(protein, model_missing_loops=False)


def test_protein_prep_prepare_requires_selection() -> None:
    """Explicit action='prepare' without selection raises."""
    protein = Protein(name="test", pdb_id="1EBY")
    with pytest.raises(ValueError, match="requires a selection"):
        ProteinPrep(protein, action="prepare")


def test_protein_prep_recommend_rejects_selection() -> None:
    """Explicit action='recommend' with selection raises."""
    protein = Protein(name="test")
    with pytest.raises(ValueError, match="does not accept a selection"):
        ProteinPrep(protein, action="recommend", selection=_SAMPLE_SELECTION)


def test_protein_prep_selection_copy_is_independent() -> None:
    """Constructor copies selection so later mutations do not leak."""
    protein = Protein(name="test", pdb_id="1EBY")
    selection = {
        "analyzer_version": "1.0.0",
        "decisions": {"chain:A": "keep"},
        "source_sha256": _SHA256,
    }
    prep = ProteinPrep(protein, selection=selection)
    selection["decisions"]["chain:A"] = "skip"
    assert prep.selection is not None
    assert prep.selection["decisions"]["chain:A"] == "keep"


def test_selection_from_recommendation_resolves_review_to_skip() -> None:
    """Reviews become skip by default; keep/skip pass through."""
    selection = selection_from_recommendation(_SAMPLE_RECOMMENDATION)
    assert selection["source_sha256"] == _SHA256
    assert selection["analyzer_version"] == "1.0.0"
    assert selection["decisions"] == {
        "chain:A": "keep",
        "ligand:LIG:A:100": "skip",
    }


def test_selection_from_recommendation_can_keep_reviews() -> None:
    """resolve_review_as='keep' maps review components to keep."""
    selection = selection_from_recommendation(
        _SAMPLE_RECOMMENDATION,
        resolve_review_as="keep",
    )
    assert selection["decisions"]["ligand:LIG:A:100"] == "keep"


def test_protein_prep_from_recommendation_builds_prepare() -> None:
    """from_recommendation produces a prepare instance with a selection."""
    protein = Protein(name="test", pdb_id="1EBY")
    prep = ProteinPrep.from_recommendation(protein, _SAMPLE_RECOMMENDATION)
    assert prep.action == "prepare"
    assert prep.pdb_id == "1EBY"
    assert prep.selection == _SAMPLE_SELECTION


def test_protein_prep_repr_lists_parameters() -> None:
    """repr/str show constructor parameters including action."""
    protein = Protein(name="brd", pdb_id="1EBY")
    prep = ProteinPrep(protein)
    text = repr(prep)

    assert text == str(prep)
    assert text.startswith("ProteinPrep")
    assert "action" in text
    assert "recommend" in text
    assert "pdb_id" in text
    assert "1EBY" in text
    assert "selection" in text
    assert "(none)" in text
    assert "model_missing_loops" in text
    assert "tool_version" in text
    assert "brd" in text
    names = [name for name, _ in prep._parameter_rows()]
    assert "id" not in names
    assert "status" not in names


def test_protein_prep_repr_shows_selection_and_execution_fields() -> None:
    """repr shows selection counts and id/status when set."""
    protein = Protein(name="brd", id="prot-1", pdb_id="1EBY")
    prep = ProteinPrep(protein, selection=_SAMPLE_SELECTION)
    text = repr(prep)
    assert "prepare" in text
    assert "1 keep, 1 skip" in text
    assert "id='prot-1'" in text

    prep._id = "exec-abc"
    prep.status = "Succeeded"
    prep._name = "my-prep"
    later = repr(prep)
    assert "exec-abc" in later
    assert "Succeeded" in later
    assert "my-prep" in later


def test_protein_prep_repr_html_escapes_and_lists_parameters() -> None:
    """_repr_html_ is an HTML table of parameters with escaped values."""
    protein = Protein(name="<script>", pdb_id="1EBY")
    prep = ProteinPrep(protein, selection=_SAMPLE_SELECTION)
    html = prep._repr_html_()

    assert "<table" in html
    assert "selection" in html
    assert "pdb_id" in html
    assert "1 keep, 1 skip" in html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_protein_prep_recommend_payload_omits_v1_fields() -> None:
    """Recommend POST body is action + protein only."""
    protein = _protein_with_remote()
    protein.id = "prot-1"
    prep = ProteinPrep(protein, pdb_id="1EBY")
    payload = prep._make_payload(approve_amount=None, sync=False)
    assert payload["inputs"] == {
        "action": "recommend",
        "protein": {"file_path": "testing/brd.pdb", "id": "prot-1"},
    }
    assert payload["sync"] is False
    assert "approveAmount" not in payload


def test_protein_prep_prepare_payload_includes_selection() -> None:
    """Prepare POST body includes action, protein, pdb_id, and selection."""
    protein = _protein_with_remote()
    prep = ProteinPrep(protein, selection=_SAMPLE_SELECTION, pdb_id="1EBY")
    payload = prep._make_payload(approve_amount=None, sync=False)
    inputs = payload["inputs"]
    assert payload["sync"] is False
    assert inputs["action"] == "prepare"
    assert inputs["pdb_id"] == "1EBY"
    assert inputs["selection"] == _SAMPLE_SELECTION
    assert inputs["protein"]["file_path"] == "testing/brd.pdb"
    assert "model_missing_loops" not in inputs
    assert "keep_chain_ids" not in inputs


def test_protein_prep_prepare_loops_off_payload() -> None:
    """Loops-off prepare sends model_missing_loops=false and omits pdb_id."""
    protein = _protein_with_remote(pdb_id=None)
    prep = ProteinPrep(
        protein,
        selection=_SAMPLE_SELECTION,
        model_missing_loops=False,
    )
    payload = prep._make_payload(approve_amount=None, sync=True)
    inputs = payload["inputs"]
    assert payload["sync"] is True
    assert inputs["action"] == "prepare"
    assert inputs["model_missing_loops"] is False
    assert "pdb_id" not in inputs
    assert "sync" not in inputs


def test_protein_prep_start_rejects_non_none_status(
    registered_protein: Protein,
) -> None:
    """start() refuses to resubmit when an execution already exists."""
    prep = ProteinPrep(registered_protein, pdb_id="1EBY")
    prep._id = "exec-existing"
    prep.status = "Running"

    with pytest.raises(ValueError, match="already in 'Running' state"):
        prep.start()


def test_protein_prep_get_results_requires_id() -> None:
    """get_results() raises when no execution has been started."""
    protein = Protein(name="test", pdb_id="1EBY")
    prep = ProteinPrep(protein)
    with pytest.raises(ValueError, match="no execution"):
        prep.get_results()


def test_protein_prep_from_dto_maps_prepare_fields(client: DeepOriginClient) -> None:
    """from_dto rehydrates protein, action, pdb_id, and selection."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/protein-prep-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    prep = ProteinPrep.from_dto(dto, client=client)

    assert prep.id == dto["executionId"]
    assert prep.status == dto["status"]
    assert prep.action == "prepare"
    assert prep.pdb_id == "1EBY"
    assert prep.selection == _SAMPLE_SELECTION
    assert prep.protein.remote_path == "testing/brd.pdb"


def test_protein_prep_from_dto_maps_recommend_fields(client: DeepOriginClient) -> None:
    """from_dto rehydrates a recommend execution without a selection."""
    fixture_path = (
        Path(__file__).parent
        / "fixtures/executions/protein-prep-recommend-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    prep = ProteinPrep.from_dto(dto, client=client)

    assert prep.action == "recommend"
    assert prep.selection is None
    rec = prep.get_recommendation(dto)
    assert rec["source_sha256"] == _SHA256
    assert rec["components"][0]["id"] == "chain:A"


def test_protein_prep_from_dto_v1_keep_lists_still_get_results(
    client: DeepOriginClient,
) -> None:
    """v1 userInputs (no action) rehydrate as prepare so get_results still works."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/protein-prep-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    dto["userInputs"] = {
        "keep_chain_ids": ["A"],
        "keep_cofactor_ids": ["MG"],
        "keep_water_residue_names": ["HOH"],
        "pdb_id": "1EBY",
        "protein": {"file_path": "testing/brd.pdb", "id": "brd"},
        "remove_ligand_ids": ["LIG"],
    }
    prep = ProteinPrep.from_dto(dto, client=client)
    assert prep.action == "prepare"
    assert prep.selection is None
    prepared = prep.get_results(dto)
    assert isinstance(prepared, Protein)
    assert prepared.remote_path == "testing/brd.pdb"


def test_protein_prep_from_dto_initializes_notebook_watch_state(
    client: DeepOriginClient,
) -> None:
    """from_dto skips __init__; notebook watch attrs must exist for stop_watching."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/protein-prep-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    prep = ProteinPrep.from_dto(dto, client=client)
    assert prep._watch_task is None
    assert prep._display_id is None
    assert prep._last_html is None
    prep.stop_watching()


def test_protein_prep_from_dto_rejects_tool_key_mismatch(
    client: DeepOriginClient,
) -> None:
    """from_dto raises when the DTO tool key is not protein-prep."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/protein-prep-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    dto["tool"] = {"key": "deeporigin.pocket-finder", "version": "1.0.0"}

    with pytest.raises(ValueError, match="tool key mismatch"):
        ProteinPrep.from_dto(dto, client=client)


def test_protein_prep_start_submits_recommend_payload(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """start() without selection submits action=recommend and stores id/status."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
    ), "Protein prep tool not registered on platform (expected key/version)."

    prep = ProteinPrep(registered_protein, pdb_id="1EBY", client=client)
    prep.start()

    assert prep.id is not None
    assert prep.status is not None
    dto = prep._dto or {}
    assert (
        dto.get("tool", {}).get("key")
        == TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"]
    )
    user_inputs = dto.get("userInputs") or {}
    assert user_inputs.get("action") == "recommend"
    assert "pdb_id" not in user_inputs
    assert "keep_chain_ids" not in user_inputs
    assert "selection" not in user_inputs
    protein_input = user_inputs.get("protein") or {}
    assert protein_input.get("id") == registered_protein.id
    assert protein_input.get("file_path") == registered_protein.remote_path


def test_protein_prep_start_recommend_get_recommendation(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """start() then get_recommendation() returns the component inventory."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
    ), "Protein prep tool not registered on platform (expected key/version)."

    prep = ProteinPrep(registered_protein, client=client)
    prep.start()
    recommendation = prep.get_recommendation()
    assert recommendation.get("source_sha256")
    assert recommendation.get("analyzer_version")
    assert recommendation.get("components")

    with pytest.raises(DeepOriginException, match="as_prepare"):
        prep.get_results()


def test_protein_prep_start_as_prepare_get_results(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """Recommend then as_prepare() then get_results() returns an in-memory Protein."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
    ), "Protein prep tool not registered on platform (expected key/version)."

    original_id = registered_protein.id
    rec = ProteinPrep(registered_protein, pdb_id="1EBY", client=client)
    rec.start()
    if client.env == "local":
        assert is_success_status(rec.status)

    prep = rec.as_prepare()
    assert prep.action == "prepare"
    assert prep.pdb_id == "1EBY"
    assert prep.selection is not None
    assert prep.selection["decisions"]["chain:A"] == "keep"
    assert prep.selection["decisions"]["ligand:LIG:A:100"] == "skip"
    prep.start()

    if client.env == "local":
        assert is_success_status(prep.status)
    prepared = prep.get_results()

    assert isinstance(prepared, Protein)
    assert prepared.id is None
    assert prepared.remote_path == "testing/brd.pdb"
    assert prepared.pdb_id == "1EBY"
    assert rec.protein.id == original_id
    assert rec.protein is registered_protein


def test_protein_prep_start_prepare_payload(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """start() with a selection submits action=prepare."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
    ), "Protein prep tool not registered on platform (expected key/version)."

    prep = ProteinPrep(
        registered_protein,
        selection=_SAMPLE_SELECTION,
        pdb_id="1EBY",
        client=client,
    )
    prep.start()
    user_inputs = (prep._dto or {}).get("userInputs") or {}
    assert user_inputs.get("action") == "prepare"
    assert user_inputs.get("pdb_id") == "1EBY"
    assert user_inputs.get("selection") == _SAMPLE_SELECTION


def test_protein_prep_get_results_from_job_outputs_fallback(
    client: DeepOriginClient,
) -> None:
    """get_results parses jobOutputs.protein when explorer rows are absent."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/protein-prep-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    prep = ProteinPrep.from_dto(dto, client=client)
    prepared = prep.get_results(dto)

    assert isinstance(prepared, Protein)
    assert prepared.id is None
    assert prepared.remote_path == "testing/brd.pdb"


def test_protein_from_prepared_data_requires_pdb_path() -> None:
    """Prepared-protein payloads without a PDB path are rejected."""
    from deeporigin.drug_discovery.protein_prep import _protein_from_prepared_data
    from deeporigin.utils.constants import PROTEIN_PREP_NO_OUTPUT_PATHS_MSG

    with pytest.raises(ValueError, match="prepared PDB"):
        _protein_from_prepared_data(
            {},
            fallback_pdb_id="1EBY",
            fallback_name="brd",
        )
    with pytest.raises(ValueError, match=PROTEIN_PREP_NO_OUTPUT_PATHS_MSG):
        _protein_from_prepared_data(
            {"protein_pdb_file_path": "  "},
            fallback_pdb_id="1EBY",
            fallback_name="brd",
        )


def test_protein_prep_pdb_id_required_message() -> None:
    """Loops-on prepare without pdb_id uses the shared constant."""
    assert "model_missing_loops=False" in PROTEIN_PREP_PDB_ID_REQUIRED_MSG
    assert "as_prepare" in PROTEIN_PREP_RECOMMEND_NOT_PREPARE_MSG


def test_protein_prep_run_raises_on_recommend() -> None:
    """run() is illegal on a recommend instance."""
    protein = Protein(name="test")
    prep = ProteinPrep(protein)
    with pytest.raises(ValueError, match="model_missing_loops=False"):
        prep.run()


def test_protein_prep_run_raises_on_loops_on_prepare() -> None:
    """run() is illegal when loop modelling is on."""
    protein = Protein(name="test", pdb_id="1EBY")
    prep = ProteinPrep(protein, selection=_SAMPLE_SELECTION)
    assert prep.model_missing_loops is True
    with pytest.raises(ValueError, match="model_missing_loops=False"):
        prep.run()


def test_protein_prep_run_requires_loops_off_message() -> None:
    """Illegal run() uses the shared constant."""
    assert "as_prepare(model_missing_loops=False)" in (
        PROTEIN_PREP_RUN_REQUIRES_LOOPS_OFF_MSG
    )


def test_protein_prep_run_loops_off_returns_protein(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """run() on loops-off prepare returns an in-memory Protein."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
    ), "Protein prep tool not registered on platform (expected key/version)."

    rec = ProteinPrep(registered_protein, client=client)
    rec.start()
    if client.env == "local":
        assert is_success_status(rec.status)

    prep = rec.as_prepare(model_missing_loops=False)
    prepared = prep.run()

    assert isinstance(prepared, Protein)
    assert prepared.id is None
    assert prepared.remote_path == "testing/brd.pdb"
    if client.env == "local":
        assert is_success_status(prep.status)
        user_inputs = (prep._dto or {}).get("userInputs") or {}
        assert user_inputs.get("model_missing_loops") is False
