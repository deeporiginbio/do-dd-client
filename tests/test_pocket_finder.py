"""Tests for :class:`deeporigin.drug_discovery.pocket_finder.PocketFinder`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from conftest import check_tool_exists
from deeporigin.drug_discovery import BRD_DATA_DIR
from deeporigin.drug_discovery.pocket_finder import PocketFinder
from deeporigin.drug_discovery.structures.pocket import Pocket
from deeporigin.drug_discovery.structures.protein import Protein
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def _minimal_pocket_finder_dto(*, execution_id: str = "exec-pf-1") -> dict:
    """Build a minimal tools execution DTO for pocket finder."""
    pf = TOOL_KEYS_AND_VERSIONS["pocket_finder"]
    return {
        "executionId": execution_id,
        "tool": {"key": pf["tool_key"], "version": pf["tool_version"]},
        "status": "Succeeded",
        "name": "pf-test",
        "userInputs": {
            "protein": {"id": "prot-xyz", "file_path": "entities/proteins/p.pdb"},
            "pocket_count": 2,
            "pocket_min_size": 35,
        },
        "quotationResult": {"successfulQuotations": [{"priceTotal": 2.5}]},
    }


def test_pocket_finder_from_dto_tool_key_mismatch() -> None:
    """Wrong tool key raises ``ValueError``."""
    dto = _minimal_pocket_finder_dto()
    dto["tool"] = {"key": "wrong.tool", "version": dto["tool"]["version"]}
    with pytest.raises(ValueError, match="tool key mismatch"):
        PocketFinder.from_dto(dto, client=MagicMock(spec=DeepOriginClient))


def test_pocket_finder_from_dto_missing_protein_id() -> None:
    """Missing ``protein.id`` raises ``ValueError``."""
    dto = _minimal_pocket_finder_dto()
    dto["userInputs"] = {"protein": {"file_path": "x"}, "pocket_count": 1}
    with pytest.raises(ValueError, match="protein.id"):
        PocketFinder.from_dto(dto, client=MagicMock(spec=DeepOriginClient))


@patch("deeporigin.drug_discovery.pocket_finder.Protein.from_id", autospec=True)
def test_pocket_finder_from_dto_hydrates(
    mock_protein_from_id: MagicMock,
) -> None:
    """``from_dto`` sets id, inputs, pricing, and calls ``Protein.from_id``."""
    fake_protein = MagicMock()
    mock_protein_from_id.return_value = fake_protein
    client = MagicMock(spec=DeepOriginClient)
    dto = _minimal_pocket_finder_dto()

    pf = PocketFinder.from_dto(dto, client=client)

    assert pf.id == "exec-pf-1"
    assert pf.protein is fake_protein
    assert pf.pocket_count == 2
    assert pf.pocket_min_size == 35
    assert pf.estimate == pytest.approx(2.5)
    assert pf.cost == pytest.approx(2.5)
    assert pf.status == "Succeeded"
    mock_protein_from_id.assert_called_once_with(
        "prot-xyz",
        client=client,
        download=False,
        remote_path_override="entities/proteins/p.pdb",
    )


@patch("deeporigin.drug_discovery.pocket_finder.Protein.from_id", autospec=True)
def test_pocket_finder_from_dto_falls_back_to_inputs_key(
    mock_protein_from_id: MagicMock,
) -> None:
    """Older DTOs may store the create payload under ``inputs``."""
    mock_protein_from_id.return_value = MagicMock()
    dto = _minimal_pocket_finder_dto()
    dto["inputs"] = dto.pop("userInputs")

    PocketFinder.from_dto(dto, client=MagicMock(spec=DeepOriginClient))

    mock_protein_from_id.assert_called_once()


@patch.object(Pocket, "from_json", autospec=True)
@patch.object(Pocket, "from_result", autospec=True)
def test_pocket_finder_get_results_falls_back_to_job_outputs(
    mock_from_result: MagicMock,
    mock_from_json: MagicMock,
) -> None:
    """When ``from_result`` fails, ``jobOutputs.pockets`` is parsed via ``from_json``."""
    fake_pocket = MagicMock(spec=Pocket)
    mock_from_result.side_effect = ValueError("no rows")
    mock_from_json.return_value = [fake_pocket]

    client = MagicMock(spec=DeepOriginClient)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    dto_exec = _minimal_pocket_finder_dto()
    dto_exec["jobOutputs"] = {"pockets": [{"id": "p1"}]}

    pf = PocketFinder(protein, client=client)
    pf.update_from_dto(dto_exec)

    out = pf.get_results(dto_exec)

    assert out == [fake_pocket]
    mock_from_result.assert_called_once_with(
        execution_id="exec-pf-1",
        client=client,
    )
    mock_from_json.assert_called_once_with(
        [{"id": "p1"}],
        client=client,
    )


def test_pocket_finder_get_results_requires_id() -> None:
    """``get_results`` raises when ``id`` has not been set."""
    client = MagicMock(spec=DeepOriginClient)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    pf = PocketFinder(protein, client=client)

    with pytest.raises(ValueError, match="id is None"):
        pf.get_results()


def test_pocket_finder_update_from_dto_updates_execution_fields() -> None:
    """``update_from_dto`` refreshes execution state without replacing ``protein``."""
    client = MagicMock(spec=DeepOriginClient)
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    dto = _minimal_pocket_finder_dto()

    pf = PocketFinder(protein, client=client)
    pf.update_from_dto(dto)

    assert pf.protein is protein
    assert pf.id == "exec-pf-1"
    assert pf.status == "Succeeded"
    assert pf.estimate == pytest.approx(2.5)
    assert pf.cost == pytest.approx(2.5)


def test_pocket_finder_from_id_delegates_lv1(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """Round-trip: ``run`` then ``PocketFinder.from_id`` restores inputs."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
    ), "Pocket finder tool not registered on platform."

    pf = PocketFinder(registered_protein, pocket_count=1, client=client)
    pf.run()
    assert pf.id is not None

    restored = PocketFinder.from_id(pf.id, client=client)
    assert restored.id == pf.id
    assert restored.pocket_count == 1
    assert restored.pocket_min_size == 30
    assert registered_protein.id is not None
    assert restored.protein.id == registered_protein.id
