"""Local mock-server tests for :class:`~deeporigin.drug_discovery.secondary_pharma.SecondaryPharmacology`.

Both execution paths run against the local mock: the ligand-ml path is
served/sync (mirrors Admet); the docking path is a minimal async completion
(mirrors Metabolism's async path) that indexes real result-explorer rows via
``_inject_secondary_pharma_docking_tool_execution_results``, so
``get_results()``/``get_poses()``'s result-explorer branch gets real coverage
here, not just the ``jobOutputs``-fallback branch exercised by the hand-built
DTO tests below. The full Argo submit/poll/complete *timing* is still
integration-only (dev/staging) -- this mock completes near-instantly, it
doesn't simulate a real multi-minute workflow.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Ligand, SecondaryPharmacology
from deeporigin.drug_discovery.structures.pose import Pose, PoseSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import (
    TERMINAL_STATES,
    TOOL_KEYS_AND_VERSIONS,
    is_success_status,
)
from tests.conftest import check_tool_exists
from tests.mock_server.routers.tools import (
    MOCK_SECONDARY_PHARMA_PANEL,
    MOCK_SECONDARY_PHARMA_POSE_SDF_PATH,
    _synthesize_secondary_pharma_ligand_ml_row,
)

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_CFG = TOOL_KEYS_AND_VERSIONS["secondary_pharma"]
_PANEL_ACCESSIONS = [accession for accession, _, _ in MOCK_SECONDARY_PHARMA_PANEL]


def _assert_tool_available(client: DeepOriginClient) -> None:
    """Require the mock secondary-pharma definition."""
    assert check_tool_exists(client, _CFG["tool_key"], _CFG["tool_version"])


def _definition_enum(client: DeepOriginClient) -> list[str]:
    """UniProt panel enum from the mock tool definition (independent of the class)."""
    definition = client.tools.get(
        tool_key=_CFG["tool_key"],
        tool_version=_CFG["tool_version"],
    )
    return definition["inputs"]["properties"]["uniprots"]["items"]["enum"]


# --- construction & validation -----------------------------------------------


def test_secondary_pharma_construct_copies_definition_enum(
    client: DeepOriginClient,
) -> None:
    """Construction fetches the live tool definition; ``tool_version`` stays latest."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], client=client)

    assert _definition_enum(client) == _PANEL_ACCESSIONS
    assert job.tool_version == "latest"
    assert job.method == "docking"
    assert job.uniprots is None


def test_secondary_pharma_requires_ligands_unless_self_test(
    client: DeepOriginClient,
) -> None:
    """``ligands`` is required unless ``self_test=True``."""
    _assert_tool_available(client)
    with pytest.raises(ValueError, match="self_test"):
        SecondaryPharmacology(client=client)

    job = SecondaryPharmacology(self_test=True, client=client)
    assert job.ligands == []
    assert job.self_test is True


def test_secondary_pharma_self_test_rejects_ligands(client: DeepOriginClient) -> None:
    """``self_test=True`` with ``ligands`` given is rejected, not silently ignored.

    The platform tool discards ``ligands`` for a self_test run (baked
    gefitinib is scored instead) -- passing both would otherwise silently
    drop the caller's ligands with no signal.
    """
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="ignored when self_test"):
        SecondaryPharmacology(ligands=[ligand], self_test=True, client=client)


def test_secondary_pharma_uniprots_constructor_rejects_unknown(
    client: DeepOriginClient,
) -> None:
    """An accession outside the live panel enum is rejected at construction."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="Unknown"):
        SecondaryPharmacology(ligands=[ligand], uniprots=["Q99999"], client=client)


def test_secondary_pharma_uniprots_setter_validation(client: DeepOriginClient) -> None:
    """Draft ``uniprots`` can be replaced, cleared, or rejected."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], client=client)

    job.uniprots = [_PANEL_ACCESSIONS[0]]
    assert job.uniprots == [_PANEL_ACCESSIONS[0]]

    job.uniprots = None
    assert job.uniprots is None

    with pytest.raises(ValueError, match="Unknown"):
        job.uniprots = ["not-an-accession"]
    with pytest.raises(ValueError, match="non-empty"):
        job.uniprots = []
    with pytest.raises(ValueError, match="duplicates"):
        job.uniprots = [_PANEL_ACCESSIONS[0], _PANEL_ACCESSIONS[0]]


def test_secondary_pharma_default_name(client: DeepOriginClient) -> None:
    """An omitted ``name`` is generated from method/ligands/uniprots/self_test."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")

    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    assert job.name == "SecondaryPharma (docking): 1 ligand vs full panel"

    job2 = SecondaryPharmacology(self_test=True, method="ligand-ml", client=client)
    assert job2.name == "SecondaryPharma (ligand-ml): self-test vs full panel"

    job3 = SecondaryPharmacology(
        ligands=[ligand],
        uniprots=_PANEL_ACCESSIONS[:2],
        client=client,
    )
    assert "2 panel targets" in job3.name


# --- method gating -------------------------------------------------------------


def test_secondary_pharma_run_rejects_docking_method(client: DeepOriginClient) -> None:
    """``run()`` is ligand-ml only; docking must use ``start()``."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    with pytest.raises(ValueError, match="start\\("):
        job.run()


def test_secondary_pharma_start_rejects_ligand_ml_method(
    client: DeepOriginClient,
) -> None:
    """``start()`` is docking only; ligand-ml must use ``run()``."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    with pytest.raises(ValueError, match="run\\("):
        job.start()


def test_secondary_pharma_watch_rejects_ligand_ml_method(
    client: DeepOriginClient,
) -> None:
    """``watch()`` is docking only -- ligand-ml never has an in-flight async job."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)

    async def _run() -> None:
        with pytest.raises(ValueError, match="run\\("):
            await job.watch()

    asyncio.run(_run())


def test_secondary_pharma_get_poses_rejects_ligand_ml_method(
    client: DeepOriginClient,
) -> None:
    """``get_poses()`` is docking only."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    with pytest.raises(ValueError, match="get_results\\("):
        job.get_poses()


def test_secondary_pharma_get_poses_rejects_self_test(client: DeepOriginClient) -> None:
    """``get_poses()`` refuses a self_test docking run.

    The platform's baked test ligand has no ligand id, so no panel_poses
    rows are ever published for it -- get_poses() would otherwise either
    raise an opaque "no results" error or (if jobOutputs happened to carry
    the rows) fail inside Pose.from_json on the missing ligand_id.
    """
    _assert_tool_available(client)
    job = SecondaryPharmacology(self_test=True, method="docking", client=client)
    with pytest.raises(ValueError, match="self_test"):
        job.get_poses()


def test_secondary_pharma_run_revalidates_mutated_uniprots(
    client: DeepOriginClient,
) -> None:
    """An in-place ``uniprots`` mutation is caught at ``run()``, not just the setter."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(
        ligands=[ligand],
        method="ligand-ml",
        uniprots=[_PANEL_ACCESSIONS[0]],
        client=client,
    )
    job.uniprots.append("not-an-accession")  # bypasses the setter
    with pytest.raises(ValueError, match="Unknown"):
        job.run()


def test_secondary_pharma_run_validates_effort_even_on_ligand_ml(
    client: DeepOriginClient,
) -> None:
    """Out-of-range ``effort`` is rejected on ``run()`` too, not just ``start()``.

    The schema has no conditional relaxation of effort's 1-5 bound for the
    ligand-ml path, so an out-of-range value would otherwise reach the
    platform and fail there instead of locally.
    """
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(
        ligands=[ligand], method="ligand-ml", effort=9, client=client
    )
    with pytest.raises(DeepOriginException, match="effort"):
        job.run()


def test_secondary_pharma_start_validates_effort_before_any_sync(
    client: DeepOriginClient,
) -> None:
    """Out-of-range ``effort`` is rejected before ligand sync / submission."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(
        ligands=[ligand], method="docking", effort=9, client=client
    )
    with pytest.raises(DeepOriginException, match="effort"):
        job.start()
    assert ligand.id is None, "sync must not have run before the effort check"


def test_secondary_pharma_repr_names_correct_entry_point(
    client: DeepOriginClient,
) -> None:
    """``repr()`` points at ``run()`` or ``start()`` matching ``method``.

    Both methods are always present on the instance but only one works;
    the repr hint is the notebook-facing cue for which one to call.
    """
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")

    ml_job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    assert repr(ml_job).endswith("# call run() to execute synchronously")

    dock_job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    assert repr(dock_job).endswith("# call start() to execute asynchronously")


# --- payload building -----------------------------------------------------------


def test_secondary_pharma_make_inputs_omits_ligands_for_self_test(
    client: DeepOriginClient,
) -> None:
    """``self_test=True`` runs have no ligands, so the ``ligands`` key is omitted.

    (The omission itself is just "no ligands to send" -- ``_make_inputs``
    doesn't special-case ``self_test``; any empty ``self._ligands`` omits
    the key the same way. The constructor is what ties the two together by
    requiring ``self_test`` whenever ``ligands`` is empty.)
    """
    _assert_tool_available(client)
    job = SecondaryPharmacology(self_test=True, method="docking", client=client)
    inputs = job._make_inputs()
    assert "ligands" not in inputs
    assert inputs["self_test"] is True
    assert inputs["methods"] == ["docking"]


def test_secondary_pharma_make_inputs_ligand_ml_falls_back_to_index_id(
    client: DeepOriginClient,
) -> None:
    """Ligand-ml rows use the list index as ``id`` when a ligand has none (never synced)."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    assert ligand.id is None
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    inputs = job._make_inputs()
    assert inputs["ligands"] == [{"smiles": "CCO", "id": "0"}]
    assert ligand.id is None, "ligand-ml path must not sync/mutate ligands"


def test_secondary_pharma_make_inputs_docking_uses_ligand_id_directly(
    client: DeepOriginClient,
) -> None:
    """Docking rows use ``lig.id``/``lig.smiles`` as-is, assuming a prior sync."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    ligand.id = "manually-set-id"
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    inputs = job._make_inputs()
    assert inputs["ligands"] == [{"id": "manually-set-id", "smiles": "CCO"}]


def test_secondary_pharma_ensure_platform_inputs_syncs_ligands(
    client: DeepOriginClient,
) -> None:
    """``_ensure_platform_inputs`` (docking-only) syncs ligands to the platform."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    assert ligand.id is None
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    job._ensure_platform_inputs()
    assert ligand.id is not None


def test_secondary_pharma_make_inputs_includes_uniprots_only_when_set(
    client: DeepOriginClient,
) -> None:
    """``uniprots`` is included when restricted, omitted for the whole panel."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], client=client)
    assert "uniprots" not in job._make_inputs()

    job.uniprots = [_PANEL_ACCESSIONS[0]]
    assert job._make_inputs()["uniprots"] == [_PANEL_ACCESSIONS[0]]


# --- ligand-ml run() / get_results() -------------------------------------------


def test_secondary_pharma_run_ligand_ml_returns_dataframe(
    client: DeepOriginClient,
) -> None:
    """Normal ``run()`` on the ligand-ml path returns one row per ligand x panel member."""
    _assert_tool_available(client)
    lig1 = Ligand.from_smiles("CCO")
    lig2 = Ligand.from_smiles("CCN")
    job = SecondaryPharmacology(ligands=[lig1, lig2], method="ligand-ml", client=client)

    df = job.run()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2 * len(_PANEL_ACCESSIONS)
    assert job.status == "Completed"
    assert job.id is not None
    for col in (
        "ligand_id",
        "uniprot_id",
        "gene_name",
        "ligand_smiles",
        "p_active",
        "p_affinity",
    ):
        assert col in df.columns

    expected = _synthesize_secondary_pharma_ligand_ml_row(
        smiles="CCO",
        ligand_id="0",
        uniprot_id=_PANEL_ACCESSIONS[0],
        gene_name=MOCK_SECONDARY_PHARMA_PANEL[0][1],
    )
    row = df[
        (df["ligand_id"] == "0") & (df["uniprot_id"] == _PANEL_ACCESSIONS[0])
    ].iloc[0]
    # exactly one of p_active/p_affinity is set per row; the other is None,
    # which pandas stores as NaN once the column is a float64 dtype.
    for key in ("p_active", "p_affinity"):
        if expected[key] is None:
            assert pd.isna(row[key])
        else:
            assert row[key] == expected[key]


def test_secondary_pharma_run_ligand_ml_filters_uniprots(
    client: DeepOriginClient,
) -> None:
    """Restricting ``uniprots`` restricts the returned rows to that subset."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(
        ligands=[ligand],
        method="ligand-ml",
        uniprots=[_PANEL_ACCESSIONS[0]],
        client=client,
    )
    df = job.run()
    assert len(df) == 1
    assert df.iloc[0]["uniprot_id"] == _PANEL_ACCESSIONS[0]


def test_secondary_pharma_run_ligand_ml_self_test_uses_full_panel(
    client: DeepOriginClient,
) -> None:
    """``self_test=True`` scores the baked ligand against the whole panel."""
    _assert_tool_available(client)
    job = SecondaryPharmacology(self_test=True, method="ligand-ml", client=client)
    df = job.run()
    assert len(df) == len(_PANEL_ACCESSIONS)
    assert set(df["uniprot_id"]) == set(_PANEL_ACCESSIONS)


def test_secondary_pharma_run_quote_true(client: DeepOriginClient) -> None:
    """``run(quote=True)`` returns the job with an estimate; ligands are unchanged."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    assert ligand.id is None
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    result = job.run(quote=True)

    assert result is job
    assert ligand.id is None
    assert job.estimate is not None
    assert job.status == "Quoted"


def test_secondary_pharma_get_results_ligand_ml_missing_rows_raises(
    client: DeepOriginClient,
) -> None:
    """A DTO with no ``ligand_ml_predictions`` rows raises, not returns empty."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    empty_dto = {
        "executionId": "fake-id",
        "tool": {"key": _CFG["tool_key"], "version": "1"},
        "jobOutputs": {"ligand_ml_predictions": []},
    }
    with pytest.raises(DeepOriginException, match="ligand_ml_predictions"):
        job.get_results(empty_dto)


# --- from_dto / duplicate --------------------------------------------------------


def test_secondary_pharma_from_dto_round_trip_ligand_ml(
    client: DeepOriginClient,
) -> None:
    """``from_dto`` restores ligands/method/effort/self_test/uniprots that ran."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(
        ligands=[ligand],
        method="ligand-ml",
        uniprots=[_PANEL_ACCESSIONS[0]],
        client=client,
    )
    job.run()
    assert job.dto is not None

    restored = SecondaryPharmacology.from_dto(job.dto, client=client)
    assert restored.id == job.id
    assert restored.method == "ligand-ml"
    assert restored.self_test is False
    assert restored.ligands[0].smiles == "CCO"
    assert restored.uniprots == (_PANEL_ACCESSIONS[0],)
    assert isinstance(restored.uniprots, tuple)
    with pytest.raises(AttributeError, match="execution id"):
        restored.uniprots = [_PANEL_ACCESSIONS[1]]


def _hand_built_docking_dto(*, self_test: bool = False) -> dict:
    """A docking-path execution DTO, since local mock never completes one for real."""
    inputs: dict = {
        "methods": ["docking"],
        "effort": 3,
        "self_test": self_test,
        "uniprots": list(_PANEL_ACCESSIONS[:2]),
    }
    if not self_test:
        inputs["ligands"] = [{"id": "lig-1", "smiles": "CCO"}]
    return {
        "executionId": "docking-hand-built",
        "status": "Completed",
        "tool": {"key": _CFG["tool_key"], "version": "2.0.2"},
        "userInputs": inputs,
    }


def test_secondary_pharma_from_dto_docking(client: DeepOriginClient) -> None:
    """``from_dto`` on a docking-path DTO restores method/effort/uniprots correctly."""
    restored = SecondaryPharmacology.from_dto(_hand_built_docking_dto(), client=client)
    assert restored.method == "docking"
    assert restored.effort == 3
    assert restored.self_test is False
    assert restored.uniprots == tuple(_PANEL_ACCESSIONS[:2])
    assert restored.ligands[0].smiles == "CCO"


def test_secondary_pharma_from_dto_self_test_has_no_ligands(
    client: DeepOriginClient,
) -> None:
    """A self_test DTO (no ``ligands`` in userInputs) rehydrates to an empty list."""
    restored = SecondaryPharmacology.from_dto(
        _hand_built_docking_dto(self_test=True), client=client
    )
    assert restored.ligands == []
    assert restored.self_test is True


def test_secondary_pharma_duplicate_after_from_dto_makes_uniprots_writable(
    client: DeepOriginClient,
) -> None:
    """``duplicate()`` fetches the definition so a rehydrated draft can set ``uniprots``."""
    _assert_tool_available(client)
    restored = SecondaryPharmacology.from_dto(_hand_built_docking_dto(), client=client)
    # restored already has an execution id, so the id-already-set guard fires
    # first (same precedence as Admet.properties) -- not the "no definition"
    # branch, which only matters for an id-less draft.
    with pytest.raises(AttributeError, match="execution id"):
        restored.uniprots = [_PANEL_ACCESSIONS[0]]

    copy = restored.duplicate()
    assert copy.id is None
    copy.uniprots = [_PANEL_ACCESSIONS[0]]
    assert copy.uniprots == [_PANEL_ACCESSIONS[0]]


# --- docking path: real local mock completion -----------------------------------


def test_secondary_pharma_docking_start_sync_get_results_and_poses(
    client: DeepOriginClient,
) -> None:
    """Full docking round trip against the local mock's minimal async completion.

    Exercises ``_load_panel_pose_rows``'s primary (result-explorer) branch for
    real -- via ``result_type="panelpose"`` -- not just the ``jobOutputs``
    fallback exercised by the hand-built DTO tests above. The mock completes
    near-instantly (0.1s); it stands in for "the workflow finished", not for
    real Argo submit/poll timing, which stays integration-only.
    """
    _assert_tool_available(client)
    client.files.upload(
        local_path=BRD_DATA_DIR / "brd-2.sdf",
        remote_path=MOCK_SECONDARY_PHARMA_POSE_SDF_PATH,
    )

    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    job.start()
    assert job.id is not None
    assert ligand.id is not None, "start() syncs the ligand before submitting"
    synced_ligand_id = ligand.id

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

    # Production-like: async DTO has empty jobOutputs; rows live in result-explorer.
    dto = job.dto or {}
    assert (dto.get("jobOutputs") or {}).get("panel_poses") == []

    df = job.get_results()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(_PANEL_ACCESSIONS)
    assert set(df["uniprot_id"]) == set(_PANEL_ACCESSIONS)
    assert set(df["ligand_id"]) == {synced_ligand_id}
    for col in ("pose_score", "binding_energy", "file_path", "gene_name", "pdb_id"):
        assert col in df.columns

    poses = job.get_poses()
    assert isinstance(poses, PoseSet)
    assert len(poses) == len(_PANEL_ACCESSIONS)
    for pose in poses:
        assert isinstance(pose, Pose)
        assert pose.ligand_id == synced_ligand_id
        assert pose.local_path is not None, "get_poses() downloads the SDF"
        assert pose.smiles is not None
