"""Regression coverage for loading saved Protein Prep pocket settings."""

from unittest.mock import MagicMock

import pytest

from deeporigin.drug_discovery.protein_prep import ProteinPrep
from deeporigin.platform.client import DeepOriginClient


@pytest.mark.parametrize("loader", ["from_dto", "from_id"])
@pytest.mark.parametrize("inputs_key", ["userInputs", "inputs"])
@pytest.mark.parametrize(
    ("pocket_inputs", "expected_mode"),
    [
        pytest.param(
            {"find_pockets": "from-crystal-ligand"},
            "from-crystal-ligand",
            id="selection-crystal",
        ),
        pytest.param(
            {"pocket": {"mode": "from-crystal-ligand"}},
            "from-crystal-ligand",
            id="legacy-selection-crystal",
        ),
        pytest.param(
            {
                "find_pockets": "from-crystal-ligand",
                "crystal_ligand": {"component_id": "ligand:A:LIG:1:"},
            },
            "from-crystal-ligand",
            id="explicit-crystal-anchor",
        ),
        pytest.param(
            {"find_pockets": "novel", "pocket_count": 2, "pocket_min_size": 500},
            "novel",
            id="novel",
        ),
        pytest.param({"find_pockets": "no"}, "no", id="explicit-no"),
        pytest.param({}, "no", id="unrequested"),
    ],
)
def test_prepare_reload_preserves_pocket_mode(
    monkeypatch: pytest.MonkeyPatch,
    loader: str,
    inputs_key: str,
    pocket_inputs: dict,
    expected_mode: str,
) -> None:
    """Saved crystal runs keep their mode and wait for unpublished pockets."""
    selection = {
        "source_sha256": "a" * 64,
        "analyzer_version": "1.0.0",
        "decisions": {"chain:A": "keep", "ligand:A:LIG:1:": "extract"},
    }
    dto = {
        "executionId": "saved-preparation",
        "tool": {"key": "deeporigin.protein-prep", "version": "10"},
        "status": "Succeeded",
        inputs_key: {
            "action": "prepare",
            "protein": {},
            "selection": selection,
            "model_missing_loops": False,
            **pocket_inputs,
        },
    }
    client = MagicMock(spec=DeepOriginClient)
    client.project_id = None
    client.executions = MagicMock()
    client.executions.get.return_value = dto

    if loader == "from_id":
        prep = ProteinPrep.from_id(dto["executionId"], client=client)
        client.executions.get.assert_called_once_with(dto["executionId"])
    else:
        prep = ProteinPrep.from_dto(dto, client=client)
        client.executions.get.assert_not_called()

    assert prep.find_pockets == expected_mode
    assert prep.selection == selection
    if expected_mode == "novel":
        assert prep.pocket_count == 2
        assert prep.pocket_min_size == 500

    # Completed executions may publish their output rows shortly afterwards.
    monkeypatch.setattr(prep, "_result_rows", lambda result_type: [])
    monkeypatch.setattr(prep, "_execution_outputs", lambda dto: {})
    if expected_mode == "no":
        with pytest.raises(ValueError, match="did not request pockets"):
            prep.get_pockets()
    else:
        assert prep.get_pockets() is None
