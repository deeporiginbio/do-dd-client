"""Local mock-server tests for :class:`~deeporigin.drug_discovery.metabolism.Metabolism`."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from deeporigin.drug_discovery import Ligand, LigandSet, Metabolism
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import METABOLISM_ENZYMES, METABOLISM_LIGAND_CAP
from tests.conftest import check_tool_exists
from tests.mock_server.routers.tools import _synthesize_metabolism_outputs

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_N_SITES_PER_LIGAND = len(METABOLISM_ENZYMES) * 3


def _assert_tool_available(client: DeepOriginClient) -> None:
    """Require the mock metabolism definition."""
    cfg = TOOL_KEYS_AND_VERSIONS["metabolism"]
    assert check_tool_exists(client, cfg["tool_key"], cfg["tool_version"])


def test_metabolism_construct_copies_nine_enzymes(
    client: DeepOriginClient,
) -> None:
    """``Metabolism(...)`` fills ``enzymes`` with the nine DOSOM CYP names."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)

    assert job.enzymes == list(METABOLISM_ENZYMES)
    assert isinstance(job.enzymes, list)
    assert job.tool_version == "latest"
    assert job.tool_key == "deeporigin.metabolism"


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


def test_metabolism_enzymes_assign_and_inplace_trim(
    client: DeepOriginClient,
) -> None:
    """Draft ``enzymes`` can be replaced or trimmed in place."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)

    job.enzymes = ["CYP3A4", "CYP2D6"]
    assert job.enzymes == ["CYP3A4", "CYP2D6"]

    job.enzymes.remove("CYP2D6")
    assert job.enzymes == ["CYP3A4"]

    with pytest.raises(ValueError, match="Unknown"):
        job.enzymes = ["CYP3A5"]
    with pytest.raises(ValueError, match="non-empty"):
        job.enzymes = []
    with pytest.raises(ValueError, match="duplicates"):
        job.enzymes = ["CYP3A4", "CYP3A4"]


def test_metabolism_run_returns_sites_dataframe(
    client: DeepOriginClient,
) -> None:
    """Normal ``run()`` returns site rows for all nine enzymes."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Metabolism(ligands=ligand, client=client)

    df = job.run()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == _N_SITES_PER_LIGAND
    for col in ("ligand_id", "smiles", "atom_index", "enzyme", "confidence"):
        assert col in df.columns
    assert set(df["enzyme"]) == set(METABOLISM_ENZYMES)
    assert job.status == "Completed"
    assert job.id is not None
    assert isinstance(job.enzymes, tuple)
    assert list(job.enzymes) == list(METABOLISM_ENZYMES)
    with pytest.raises(AttributeError, match="execution id"):
        job.enzymes = ["CYP3A4"]

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


def test_metabolism_enzyme_trim_filters_sites_not_molecules(
    client: DeepOriginClient,
) -> None:
    """Trimmed ``enzymes`` filters site rows; ``get_molecules`` stays unfiltered."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.enzymes = ["CYP3A4", "CYP2D6"]

    df = job.run()
    mols = job.get_molecules()

    assert set(df["enzyme"]) == {"CYP3A4", "CYP2D6"}
    assert len(df) == 6
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


def test_metabolism_run_rejects_cleared_enzymes(
    client: DeepOriginClient,
) -> None:
    """In-place empty ``enzymes`` fails at ``run()``."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.enzymes.clear()
    with pytest.raises(ValueError, match="non-empty"):
        job.run()


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


def test_metabolism_from_dto_enzymes_is_none(
    client: DeepOriginClient,
) -> None:
    """``from_dto`` does not restore a trim; ``get_results`` returns all sites."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.enzymes = ["CYP3A4"]
    job.run()
    assert job.dto is not None

    restored = Metabolism.from_dto(job.dto, client=client)
    assert restored.id == job.id
    assert restored.enzymes is None
    assert restored.ligands[0].smiles == "CCO"
    with pytest.raises(AttributeError, match="execution id"):
        restored.enzymes = ["CYP3A4"]

    all_sites = restored.get_results()
    assert set(all_sites["enzyme"]) == set(METABOLISM_ENZYMES)


def test_metabolism_duplicate_makes_enzymes_writable(
    client: DeepOriginClient,
) -> None:
    """``duplicate()`` clears ``id`` and returns a mutable enzymes list."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.enzymes = ["CYP3A4"]
    job.run()

    copy = job.duplicate()
    assert copy.id is None
    assert isinstance(copy.enzymes, list)
    copy.enzymes = ["CYP2D6"]
    assert copy.enzymes == ["CYP2D6"]


def test_metabolism_from_dto_duplicate_fills_enzymes(
    client: DeepOriginClient,
) -> None:
    """``duplicate()`` of a rehydrated job fills the nine CYP names."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.run()
    assert job.dto is not None

    restored = Metabolism.from_dto(job.dto, client=client)
    assert restored.enzymes is None
    copy = restored.duplicate()
    assert copy.id is None
    assert copy.enzymes == list(METABOLISM_ENZYMES)
    copy.enzymes.remove("CYP1A2")
    assert "CYP1A2" not in copy.enzymes
