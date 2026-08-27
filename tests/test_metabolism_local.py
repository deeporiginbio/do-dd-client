"""Local mock-server tests for :class:`~deeporigin.drug_discovery.metabolism.Metabolism`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from deeporigin.drug_discovery import Ligand, LigandSet, Metabolism
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import METABOLISM_LIGAND_CAP
from tests.conftest import check_tool_exists
from tests.mock_server.routers.tools import _synthesize_metabolism_outputs

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_SAMPLE_SITES, _ = _synthesize_metabolism_outputs(smiles="CCO", ligand_id=None)
_N_SITES_PER_LIGAND = len(_SAMPLE_SITES)
_MOCK_ENZYMES = {row["enzyme"] for row in _SAMPLE_SITES}


def _assert_tool_available(client: DeepOriginClient) -> None:
    """Require the mock metabolism definition."""
    cfg = TOOL_KEYS_AND_VERSIONS["metabolism"]
    assert check_tool_exists(client, cfg["tool_key"], cfg["tool_version"])


def test_metabolism_construct_sets_tool_identity(
    client: DeepOriginClient,
) -> None:
    """``Metabolism(...)`` pins the metabolism tool key and latest version."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)

    assert job.tool_version == "latest"
    assert job.tool_key == "deeporigin.metabolism"
    assert not hasattr(job, "enzymes")


def test_metabolism_constructor_rejects_enzymes_kwarg(
    client: DeepOriginClient,
) -> None:
    """The constructor does not take ``enzymes=``."""
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(TypeError):
        Metabolism(  # ty:ignore[unexpected-keyword]
            ligands=ligand,
            enzymes=["CYP3A4"],
            client=client,
        )


def test_metabolism_constructor_rejects_quote_on_run(
    client: DeepOriginClient,
) -> None:
    """``run()`` has no quote path."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    with pytest.raises(TypeError):
        job.run(quote=True)  # ty:ignore[unexpected-keyword]


def test_metabolism_run_returns_sites_dataframe(
    client: DeepOriginClient,
) -> None:
    """Normal ``run()`` returns site rows for every enzyme the tool scored."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Metabolism(ligands=ligand, client=client)

    df = job.run()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == _N_SITES_PER_LIGAND
    for col in ("ligand_id", "smiles", "atom_index", "enzyme", "confidence"):
        assert col in df.columns
    assert set(df["enzyme"]) == _MOCK_ENZYMES
    assert job.status == "Completed"
    assert job.id is not None

    expected_sites, _ = _synthesize_metabolism_outputs(
        smiles="CCO",
        ligand_id=None,
    )
    assert df["smiles"].iloc[0] == "CCO"
    assert pd.isna(df["ligand_id"].iloc[0]) or df["ligand_id"].iloc[0] is None
    cyp3a4 = df[df["enzyme"] == "CYP3A4"].sort_values("atom_index")
    expected_3a4 = [r for r in expected_sites if r["enzyme"] == "CYP3A4"]
    assert list(cyp3a4["confidence"]) == [r["confidence"] for r in expected_3a4]


def test_metabolism_run_omits_id_when_ligand_has_none(
    client: DeepOriginClient,
) -> None:
    """Payload sends SMILES only when ``Ligand.id`` is unset."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    assert ligand.id is None
    job = Metabolism(ligands=ligand, client=client)
    inputs = job._make_inputs()
    assert inputs["ligands"] == [{"smiles": "CCO"}]
    assert "id" not in inputs["ligands"][0]


def test_metabolism_run_sends_id_when_present(
    client: DeepOriginClient,
) -> None:
    """A platform ligand id is forwarded and echoed on result rows."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    ligand.id = "lig-1"
    job = Metabolism(ligands=ligand, client=client)
    assert job._make_inputs()["ligands"] == [{"smiles": "CCO", "id": "lig-1"}]

    df = job.run()
    assert set(df["ligand_id"]) == {"lig-1"}
    mols = job.get_molecules()
    assert set(mols["ligand_id"]) == {"lig-1"}
    assert set(mols["confidence_tier"]).issubset({"high", "medium", "low"})


def test_metabolism_get_molecules_one_row_per_ligand(
    client: DeepOriginClient,
) -> None:
    """``get_molecules`` returns one confidence-tier row per scored SMILES."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.run()
    mols = job.get_molecules()

    assert len(mols) == 1
    assert list(mols.columns)[:3] == ["ligand_id", "smiles", "confidence_tier"]


def test_metabolism_accepts_ligandset(
    client: DeepOriginClient,
) -> None:
    """A LigandSet is a valid constructor value."""
    _assert_tool_available(client)
    ligands = LigandSet(ligands=[Ligand.from_smiles("CCO"), Ligand.from_smiles("CCN")])
    job = Metabolism(ligands=ligands, client=client)
    df = job.run()
    assert len(df) == _N_SITES_PER_LIGAND * 2
    assert set(df["smiles"]) == {"CCO", "CCN"}
    assert len(job.get_molecules()) == 2


def test_metabolism_rejects_over_cap(client: DeepOriginClient) -> None:
    """More than 250 ligands fails before create."""
    ligand = Ligand.from_smiles("CCO")
    ligands = [ligand] * (METABOLISM_LIGAND_CAP + 1)
    with pytest.raises(ValueError, match="at most 250"):
        Metabolism(ligands=ligands, client=client)


def test_metabolism_get_results_missing_sites_raises(
    client: DeepOriginClient,
) -> None:
    """Empty ``sites`` in jobOutputs is a loud failure."""
    dto = {
        "executionId": "metabolism-empty-sites",
        "status": "Completed",
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["metabolism"]["tool_key"],
            "version": "4.0.0",
        },
        "userInputs": {"ligands": [{"smiles": "CCO"}]},
        "jobOutputs": {"sites": [], "molecules": []},
    }
    job = Metabolism.from_dto(dto, client=client)
    with pytest.raises(DeepOriginException, match="no sites"):
        job.get_results(dto)
    with pytest.raises(DeepOriginException, match="no molecules"):
        job.get_molecules(dto)


def test_metabolism_from_dto_restores_ligands_and_all_sites(
    client: DeepOriginClient,
) -> None:
    """``from_dto`` restores ligands; ``get_results`` returns every site row."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.run()
    assert job.dto is not None

    restored = Metabolism.from_dto(job.dto, client=client)
    assert restored.id == job.id
    assert restored.ligands[0].smiles == "CCO"
    assert not hasattr(restored, "enzymes")

    all_sites = restored.get_results()
    assert set(all_sites["enzyme"]) == _MOCK_ENZYMES


def test_metabolism_duplicate_clears_id(
    client: DeepOriginClient,
) -> None:
    """``duplicate()`` clears ``id`` so the same ligands can be re-run."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.run()

    copy = job.duplicate()
    assert copy.id is None
    assert [lig.smiles for lig in copy.ligands] == ["CCO"]
    assert not hasattr(copy, "enzymes")
