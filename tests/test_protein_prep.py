"""Tests for :mod:`deeporigin.drug_discovery.protein_prep`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeporigin.drug_discovery import Protein, ProteinPrep
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS, is_success_status
from tests.conftest import check_tool_exists


def test_protein_prep_infers_pdb_id_from_protein() -> None:
    """Constructor uses protein.pdb_id when pdb_id= is omitted."""
    protein = Protein(name="test", pdb_id="1EBY")
    prep = ProteinPrep(protein)
    assert prep.pdb_id == "1EBY"


def test_protein_prep_requires_pdb_id_when_protein_has_none() -> None:
    """Constructor raises when neither kwarg nor protein.pdb_id is set."""
    protein = Protein(name="test")
    with pytest.raises(ValueError, match="pdb_id is required"):
        ProteinPrep(protein)


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


def test_protein_prep_keep_remove_defaults_are_empty() -> None:
    """Keep/remove lists default to empty copies, not shared mutables."""
    protein = Protein(name="test", pdb_id="1EBY")
    prep = ProteinPrep(protein)
    assert prep.keep_chain_ids == []
    assert prep.keep_cofactor_ids == []
    assert prep.keep_water_residue_names == []
    assert prep.remove_ligand_ids == []
    prep.keep_chain_ids.append("A")
    other = ProteinPrep(protein)
    assert other.keep_chain_ids == []


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


def test_protein_prep_from_dto_maps_fields(client: DeepOriginClient) -> None:
    """from_dto rehydrates protein, pdb_id, and keep/remove lists."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/protein-prep-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    prep = ProteinPrep.from_dto(dto, client=client)

    assert prep.id == dto["executionId"]
    assert prep.status == dto["status"]
    assert prep.pdb_id == "1EBY"
    assert prep.keep_chain_ids == ["A"]
    assert prep.keep_cofactor_ids == ["MG"]
    assert prep.keep_water_residue_names == ["HOH"]
    assert prep.remove_ligand_ids == ["LIG"]
    assert prep.protein.remote_path == "testing/brd.pdb"


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


def test_protein_prep_start_submits_payload(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """start() submits inputs without approveAmount and stores id/status."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
    ), "Protein prep tool not registered on platform (expected key/version)."

    prep = ProteinPrep(
        registered_protein,
        pdb_id="1EBY",
        keep_chain_ids=["A"],
        keep_cofactor_ids=["ZN"],
        keep_water_residue_names=["HOH"],
        remove_ligand_ids=["LIG"],
        client=client,
    )
    prep.start()

    assert prep.id is not None
    assert prep.status is not None
    dto = prep._dto or {}
    assert (
        dto.get("tool", {}).get("key")
        == TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"]
    )
    user_inputs = dto.get("userInputs") or {}
    assert user_inputs.get("pdb_id") == "1EBY"
    assert user_inputs.get("keep_chain_ids") == ["A"]
    assert user_inputs.get("keep_cofactor_ids") == ["ZN"]
    assert user_inputs.get("keep_water_residue_names") == ["HOH"]
    assert user_inputs.get("remove_ligand_ids") == ["LIG"]
    protein_input = user_inputs.get("protein") or {}
    assert protein_input.get("id") == registered_protein.id
    assert protein_input.get("file_path") == registered_protein.remote_path
    assert "approveAmount" not in (prep._make_payload(approve_amount=None, sync=False))


def test_protein_prep_start_get_results_returns_in_memory_protein(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """start() then get_results() returns Protein with id None and prepared path."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["protein_prep"]["tool_version"],
    ), "Protein prep tool not registered on platform (expected key/version)."

    original_id = registered_protein.id
    prep = ProteinPrep(registered_protein, pdb_id="1EBY", client=client)
    prep.start()

    if client.env == "local":
        assert is_success_status(prep.status)
    prepared = prep.get_results()

    assert isinstance(prepared, Protein)
    assert prepared.id is None
    assert prepared.remote_path == "testing/brd.pdb"
    assert prepared.pdb_id == "1EBY"
    assert prep.protein.id == original_id
    assert prep.protein is registered_protein


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
