"""Local mock-server tests for :class:`~deeporigin.drug_discovery.metabolism.Metabolism`."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from deeporigin.drug_discovery import Ligand, LigandSet, Metabolism
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import (
    TERMINAL_STATES,
    TOOL_KEYS_AND_VERSIONS,
    is_success_status,
)
from deeporigin.utils.constants import (
    METABOLISM_INLINE_LIGAND_CAP,
    METABOLISM_WORKFLOW_LIGAND_THRESHOLD,
)
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


def test_metabolism_run_rejects_ge_threshold(
    client: DeepOriginClient,
) -> None:
    """``run()`` fails for workflow-scale batches; use ``start()`` instead."""
    _assert_tool_available(client)
    ligands = [Ligand.from_smiles("CCO")] * METABOLISM_WORKFLOW_LIGAND_THRESHOLD
    job = Metabolism(ligands=ligands, client=client)
    with pytest.raises(ValueError, match="start\\(\\) then wait\\(\\) or watch\\(\\)"):
        job.run()


def test_metabolism_start_async_payload(
    client: DeepOriginClient,
) -> None:
    """``start`` submits ``sync=False`` and stores id/status."""
    _assert_tool_available(client)
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job.start()

    assert job.id is not None
    assert job.status is not None
    dto = job._dto or {}
    assert dto.get("tool", {}).get("key") == "deeporigin.metabolism"
    assert (dto.get("userInputs") or {}).get("ligands") == [{"smiles": "CCO"}]


def test_metabolism_start_above_inline_cap_uses_ligands_file(
    client: DeepOriginClient,
) -> None:
    """Batches above the inline cap submit ``ligands_file`` after UFA upload."""
    _assert_tool_available(client)
    n = METABOLISM_INLINE_LIGAND_CAP + 1
    ligands = [Ligand.from_smiles("CCO")] * n
    job = Metabolism(ligands=ligands, client=client)
    inputs = job._make_inputs()
    assert "ligands" not in inputs
    remote = inputs["ligands_file"]
    assert remote.startswith("metabolism/ligand-lists/")
    assert job._remote_ligands_file == remote
    # Cached path: second call does not re-upload a new key.
    assert job._make_inputs()["ligands_file"] == remote

    job.start()

    dto = job._dto or {}
    assert (dto.get("userInputs") or {}).get("ligands_file") == remote
    assert "ligands" not in (dto.get("userInputs") or {})

    # Uploaded body is a bare ligand array.
    local = client.files.download(remote, direct=True)
    parsed = json.loads(Path(local).read_text(encoding="utf-8"))
    assert isinstance(parsed, list)
    assert len(parsed) == n
    assert parsed[0] == {"smiles": "CCO"}


def test_metabolism_from_dto_rehydrates_ligands_file(
    client: DeepOriginClient,
) -> None:
    """``from_dto`` downloads ``ligands_file`` and restores ligands."""
    _assert_tool_available(client)
    n = METABOLISM_INLINE_LIGAND_CAP + 1
    job = Metabolism(ligands=[Ligand.from_smiles("CCO")] * n, client=client)
    job.start()
    assert job.dto is not None

    restored = Metabolism.from_dto(job.dto, client=client)
    assert len(restored.ligands) == n
    assert restored.ligands[0].smiles == "CCO"
    assert restored._remote_ligands_file == (job.dto.get("userInputs") or {}).get(
        "ligands_file"
    )


def test_metabolism_start_rejects_non_initial_status(
    client: DeepOriginClient,
) -> None:
    """``start`` must refuse to resubmit when an execution already exists."""
    job = Metabolism(ligands=Ligand.from_smiles("CCO"), client=client)
    job._id = "exec-metabolism-existing"
    job.status = "Running"

    with pytest.raises(ValueError, match="already in 'Running' state"):
        job.start()


def test_metabolism_start_sync_get_results(
    client: DeepOriginClient,
) -> None:
    """Start asynchronously, poll until done, then load sites and molecules.

    Async mock completions index rows in result-explorer only (empty
    ``jobOutputs``), so this exercises the data-platform-first path.
    """
    _assert_tool_available(client)
    ligands = [Ligand.from_smiles("CCO")] * METABOLISM_WORKFLOW_LIGAND_THRESHOLD
    job = Metabolism(ligands=ligands, client=client)
    job.start()
    assert job.id is not None

    timeout_seconds = 5.0
    poll_interval = 0.05
    elapsed = 0.0
    while elapsed < timeout_seconds:
        job.sync()
        if job.status in TERMINAL_STATES:
            break
        time.sleep(poll_interval)
        elapsed += poll_interval

    assert job.status in TERMINAL_STATES
    assert is_success_status(job.status)

    # Production-like: async DTO has empty jobOutputs; rows live in results.
    dto = job.dto or {}
    jo = dto.get("jobOutputs") or {}
    assert jo.get("sites") == []
    assert jo.get("molecules") == []

    sites = job.get_results()
    assert len(sites) == _N_SITES_PER_LIGAND * METABOLISM_WORKFLOW_LIGAND_THRESHOLD
    mols = job.get_molecules()
    assert len(mols) == METABOLISM_WORKFLOW_LIGAND_THRESHOLD


def test_metabolism_get_results_missing_sites_raises(
    client: DeepOriginClient,
) -> None:
    """Empty sites/molecules from both sources is a loud failure."""
    dto = {
        # Mock sentinel: skip fixture rematch so result-explorer stays empty.
        "executionId": "__no_result_rows__",
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


def test_metabolism_fetch_results_and_molecules_by_ligand_id(
    client: DeepOriginClient,
) -> None:
    """``fetch_*`` loads indexed rows by ligand id without a new job."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    ligand.id = "lig-fetch-1"
    job = Metabolism(ligands=ligand, client=client)
    job.run()

    sites = Metabolism.fetch_results(ligands=ligand, client=client)
    mols = Metabolism.fetch_molecules(ligands=ligand, client=client)

    assert len(sites) == _N_SITES_PER_LIGAND
    assert set(sites["ligand_id"]) == {"lig-fetch-1"}
    assert set(sites["enzyme"]) == _MOCK_ENZYMES
    assert set(sites["smiles"]) == {"CCO"}
    assert len(mols) == 1
    assert set(mols["ligand_id"]) == {"lig-fetch-1"}
    assert set(mols["smiles"]) == {"CCO"}
    assert set(mols["confidence_tier"]).issubset({"high", "medium", "low"})


def test_metabolism_fetch_without_ids_returns_empty(
    client: DeepOriginClient,
) -> None:
    """Ligands without platform ids yield empty fetch tables with columns."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    assert ligand.id is None

    sites = Metabolism.fetch_results(ligands=ligand, client=client)
    mols = Metabolism.fetch_molecules(ligands=ligand, client=client)

    assert len(sites) == 0
    assert list(sites.columns)[:5] == [
        "ligand_id",
        "smiles",
        "atom_index",
        "enzyme",
        "confidence",
    ]
    assert len(mols) == 0
    assert list(mols.columns)[:3] == ["ligand_id", "smiles", "confidence_tier"]


def test_metabolism_run_refuses_when_all_already_scored(
    client: DeepOriginClient,
) -> None:
    """``run()`` raises before create when every id already has a molecule."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    ligand.id = "lig-already-1"
    Metabolism(ligands=ligand, client=client).run()

    again = Metabolism(ligands=ligand, client=client)
    with pytest.raises(DeepOriginException, match="already have MetabolismMolecule"):
        again.run()
    assert again.id is None
    assert again.status is None


def test_metabolism_start_refuses_when_all_already_scored(
    client: DeepOriginClient,
) -> None:
    """``start()`` raises before create when every id already has a molecule."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    ligand.id = "lig-already-start-1"
    Metabolism(ligands=ligand, client=client).run()

    again = Metabolism(ligands=ligand, client=client)
    with pytest.raises(DeepOriginException, match="already have MetabolismMolecule"):
        again.start()
    assert again.id is None
    assert again.status is None


def test_metabolism_run_warns_when_some_already_scored(
    client: DeepOriginClient,
    recwarn: pytest.WarningsRecorder,
) -> None:
    """Partial already-scored still runs and emits a UserWarning."""
    _assert_tool_available(client)
    scored = Ligand.from_smiles("CCO")
    scored.id = "lig-partial-scored"
    Metabolism(ligands=scored, client=client).run()

    fresh = Ligand.from_smiles("CCN")
    assert fresh.id is None
    job = Metabolism(ligands=[scored, fresh], client=client)
    recwarn.clear()
    df = job.run()

    assert job.id is not None
    assert len(df) >= _N_SITES_PER_LIGAND
    matching = [
        w
        for w in recwarn
        if issubclass(w.category, UserWarning)
        and "already have indexed MetabolismMolecule" in str(w.message)
    ]
    assert matching
    assert "sync path may recompute" in str(matching[0].message)
