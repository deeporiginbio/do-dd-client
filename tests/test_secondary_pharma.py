"""Local mock-server tests for :class:`~deeporigin.drug_discovery.secondary_pharma.SecondaryPharmacology`.

Both execution paths run against the local mock: the ligand-ml path is
served/sync (mirrors Admet); the docking path is a minimal async completion
(mirrors Metabolism's async path) that indexes real result-explorer rows via
``_inject_secondary_pharma_docking_tool_execution_results``, so
``get_results()``/``_get_poses()``'s result-explorer branch gets real coverage
here, not just the ``jobOutputs``-fallback branch exercised by the hand-built
DTO tests below. The full Argo submit/poll/complete *timing* is still
integration-only (dev/staging) -- this mock completes near-instantly, it
doesn't simulate a real multi-minute workflow.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch
import warnings

import pandas as pd
import pytest

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Ligand,
    SecondaryPharmacology,
)
from deeporigin.drug_discovery.structures.pose import Pose, PoseSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.constants import (
    TERMINAL_STATES,
    TOOL_KEYS_AND_VERSIONS,
    is_success_status,
)
from deeporigin.plots import WHITE_RED_HAZARD_PALETTE
from tests.conftest import check_tool_exists
from tests.mock_server.routers.tools import (
    MOCK_SECONDARY_PHARMA_PANEL,
    MOCK_SECONDARY_PHARMA_POSE_SDF_PATH,
    MOCK_SECONDARY_PHARMA_RECEPTOR_PDB_PATH,
    _synthesize_secondary_pharma_ligand_ml_row,
)

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_CFG = TOOL_KEYS_AND_VERSIONS["secondary_pharma"]
_PANEL_ACCESSIONS = [accession for accession, _, _ in MOCK_SECONDARY_PHARMA_PANEL]


def _assert_tool_available(client: DeepOriginClient) -> None:
    """Require the mock secondary-pharma definition."""
    assert check_tool_exists(client, _CFG["tool_key"], _CFG["tool_version"])


def _upload_mock_panel_receptor(client: DeepOriginClient) -> None:
    """Stage a panel receptor PDB under the mock ``protected`` org namespace."""
    fixture = Path(__file__).parent / "fixtures" / "1eby.pdb"
    content = fixture.read_bytes()
    files = {
        "file": (fixture.name, content, "application/octet-stream"),
    }
    client._put(f"/files/{MOCK_SECONDARY_PHARMA_RECEPTOR_PDB_PATH}", files=files)


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
    """Construction fetches the live tool definition; ``tool_version`` stays pinned."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)

    assert _definition_enum(client) == _PANEL_ACCESSIONS
    assert job.tool_version == "2"
    assert job.method == "docking"
    assert job.uniprots is None


def test_secondary_pharma_panel_lists_accessions_and_gene_names(
    client: DeepOriginClient,
) -> None:
    """``get_panel()`` needs no ligand or instance and returns accession/gene_name rows."""
    _assert_tool_available(client)
    df = SecondaryPharmacology.get_panel(client=client)
    assert list(df["uniprot_id"]) == _PANEL_ACCESSIONS
    assert list(df["gene_name"]) == [gene for _, gene, _ in MOCK_SECONDARY_PHARMA_PANEL]


def test_secondary_pharma_panel_default_truncates_full_does_not(
    client: DeepOriginClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A panel larger than the preview size is truncated by default, not with ``full=True``.

    Runs against the mock server's real (3-member) panel -- the only patch is
    the module's own preview-size constant, an internal tuning knob, not
    simulated platform behavior. `client.tools.get()` is never replaced.
    """
    _assert_tool_available(client)
    monkeypatch.setattr(
        "deeporigin.drug_discovery.secondary_pharma._PANEL_PREVIEW_ROWS", 2
    )

    preview = SecondaryPharmacology.get_panel(client=client)
    assert len(preview) == 2
    assert list(preview["uniprot_id"]) == _PANEL_ACCESSIONS[:2]
    assert "2 of 3" in capsys.readouterr().out

    full = SecondaryPharmacology.get_panel(full=True, client=client)
    assert len(full) == len(_PANEL_ACCESSIONS)
    assert list(full["uniprot_id"]) == _PANEL_ACCESSIONS


def test_secondary_pharma_requires_method(client: DeepOriginClient) -> None:
    """``method`` is required; omitting it names both valid values."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="docking.*ligand-ml"):
        SecondaryPharmacology(ligands=[ligand], client=client)


def test_secondary_pharma_requires_ligands_unless_self_test(
    client: DeepOriginClient,
) -> None:
    """``ligands`` is required unless ``self_test=True``."""
    _assert_tool_available(client)
    with pytest.raises(ValueError, match="self_test"):
        SecondaryPharmacology(method="docking", client=client)

    job = SecondaryPharmacology(self_test=True, method="ligand-ml", client=client)
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
        SecondaryPharmacology(
            ligands=[ligand], self_test=True, method="ligand-ml", client=client
        )


def test_secondary_pharma_self_test_rejects_docking(client: DeepOriginClient) -> None:
    """``self_test=True`` with ``method="docking"`` is rejected at construction.

    The platform always routes a self_test run through the served
    ligand-ml path regardless of ``method`` -- a docking-shaped result
    never materializes, so this combination would otherwise silently
    misbehave downstream in ``get_results()``/``watch()`` instead of
    failing clearly up front.
    """
    _assert_tool_available(client)
    with pytest.raises(ValueError, match="self_test=True is not supported"):
        SecondaryPharmacology(self_test=True, method="docking", client=client)


def test_secondary_pharma_uniprots_constructor_rejects_unknown(
    client: DeepOriginClient,
) -> None:
    """An accession outside the live panel enum is rejected at construction."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="Unknown"):
        SecondaryPharmacology(
            ligands=[ligand], uniprots=["Q99999"], method="docking", client=client
        )


def test_secondary_pharma_uniprots_setter_validation(client: DeepOriginClient) -> None:
    """Draft ``uniprots`` can be replaced, cleared, or rejected."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)

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
        method="docking",
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
    """``_get_poses()`` is docking only."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    with pytest.raises(ValueError, match="get_results\\("):
        job._get_poses()


def test_secondary_pharma_get_poses_rejects_self_test(client: DeepOriginClient) -> None:
    """``_get_poses()`` refuses a self_test docking run.

    The constructor rejects ``self_test=True`` with ``method="docking"``
    outright (see ``test_secondary_pharma_self_test_rejects_docking``), but
    a legacy execution created before that guard existed can still
    rehydrate via ``from_dto`` into this exact shape -- this test covers
    that path via a hand-built DTO, not the constructor. The platform's
    baked test ligand has no ligand id, so no panel_poses rows are ever
    published for it -- _get_poses() would otherwise either raise an opaque
    "no results" error or (if jobOutputs happened to carry the rows) fail
    inside Pose.from_json on the missing ligand_id.
    """
    job = SecondaryPharmacology.from_dto(
        _hand_built_docking_dto(self_test=True), client=client
    )
    with pytest.raises(ValueError, match="self_test"):
        job._get_poses()


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


def test_secondary_pharma_batch_size_rejects_non_positive(
    client: DeepOriginClient,
) -> None:
    """``batch_size`` must be a positive integer, checked at construction.

    Unlike ``effort``, ``batch_size`` has no setter (read-only after
    construction), so there's no separate "validated again before
    submission" path to test -- construction is the only place it can go
    wrong.
    """
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(ValueError, match="batch_size"):
        SecondaryPharmacology(
            ligands=[ligand], method="docking", batch_size=0, client=client
        )
    with pytest.raises(ValueError, match="batch_size"):
        SecondaryPharmacology(
            ligands=[ligand], method="docking", batch_size=-5, client=client
        )


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
    job = SecondaryPharmacology(self_test=True, method="ligand-ml", client=client)
    inputs = job._make_inputs()
    assert "ligands" not in inputs
    assert inputs["self_test"] is True
    assert inputs["methods"] == ["ligand-ml"]


def test_secondary_pharma_make_inputs_ligand_ml_omits_id_when_unsynced(
    client: DeepOriginClient,
) -> None:
    """Ligand-ml rows omit ``id`` for a ligand with none (never synced).

    Not sent as ``id=None`` -- ``id`` must be a string when present, but
    isn't required at all, so omitting it is the schema-valid option.
    """
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    assert ligand.id is None
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    inputs = job._make_inputs()
    assert inputs["ligands"] == [{"smiles": "CCO"}]
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
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    assert "uniprots" not in job._make_inputs()

    job.uniprots = [_PANEL_ACCESSIONS[0]]
    assert job._make_inputs()["uniprots"] == [_PANEL_ACCESSIONS[0]]


def test_secondary_pharma_make_payload_includes_batch_size(
    client: DeepOriginClient,
) -> None:
    """``batchSize`` is a top-level payload field (like ``Docking``), not
    nested under ``inputs`` -- defaults to 30, and a custom value round-trips.
    """
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    payload = job._make_payload(approve_amount=None, sync=False)
    assert payload["batchSize"] == 30
    assert "batchSize" not in payload["inputs"]

    job_custom = SecondaryPharmacology(
        ligands=[ligand], method="docking", batch_size=10, client=client
    )
    assert job_custom._make_payload(approve_amount=None, sync=False)["batchSize"] == 10


def test_secondary_pharma_make_payload_sends_batch_size_on_ligand_ml_too(
    client: DeepOriginClient,
) -> None:
    """``batchSize`` is always sent, even on ligand-ml (which never reaches
    the workflow that reads it) -- matches ``Docking``'s always-send
    behavior, kept for a predictable ``from_dto`` round trip."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    assert job._make_payload(approve_amount=None, sync=True)["batchSize"] == 30


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
    assert set(df["method"]) == {"ligand-ml"}

    # Ligands started unsynced, but get_results() backfills a real id once
    # they're synced post-hoc -- not a fabricated placeholder.
    assert lig1.id is not None
    assert lig2.id is not None
    assert set(df["ligand_id"]) == {lig1.id, lig2.id}
    expected = _synthesize_secondary_pharma_ligand_ml_row(
        smiles="CCO",
        ligand_id=None,
        uniprot_id=_PANEL_ACCESSIONS[0],
        gene_name=MOCK_SECONDARY_PHARMA_PANEL[0][1],
    )
    row = df[
        (df["ligand_smiles"] == "CCO") & (df["uniprot_id"] == _PANEL_ACCESSIONS[0])
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


def _hand_built_docking_dto(
    *,
    self_test: bool = False,
    batch_size: int | None = None,
    batch_size_in_metadata_only: bool = False,
) -> dict:
    """A docking-path execution DTO, since local mock never completes one for real."""
    inputs: dict = {
        "methods": ["docking"],
        "effort": 3,
        "self_test": self_test,
        "uniprots": list(_PANEL_ACCESSIONS[:2]),
    }
    if not self_test:
        inputs["ligands"] = [{"id": "lig-1", "smiles": "CCO"}]
    dto: dict = {
        "executionId": "docking-hand-built",
        "status": "Completed",
        "tool": {"key": _CFG["tool_key"], "version": "2.0.2"},
        "userInputs": inputs,
    }
    if batch_size is not None:
        if batch_size_in_metadata_only:
            dto["metadata"] = {"batchSize": batch_size}
        else:
            dto["batchSize"] = batch_size
    return dto


def test_secondary_pharma_from_dto_docking(client: DeepOriginClient) -> None:
    """``from_dto`` on a docking-path DTO restores method/effort/uniprots correctly."""
    restored = SecondaryPharmacology.from_dto(_hand_built_docking_dto(), client=client)
    assert restored.method == "docking"
    assert restored.effort == 3
    assert restored.self_test is False
    assert restored.uniprots == tuple(_PANEL_ACCESSIONS[:2])
    assert restored.ligands[0].smiles == "CCO"
    assert restored.batch_size == 30, "no batchSize anywhere in the DTO -- defaults"


def test_secondary_pharma_from_dto_restores_batch_size(
    client: DeepOriginClient,
) -> None:
    """``batch_size`` is restored from the top-level ``batchSize`` field, or
    ``metadata.batchSize`` as a fallback for an older execution record."""
    restored = SecondaryPharmacology.from_dto(
        _hand_built_docking_dto(batch_size=12), client=client
    )
    assert restored.batch_size == 12

    restored_from_meta = SecondaryPharmacology.from_dto(
        _hand_built_docking_dto(batch_size=7, batch_size_in_metadata_only=True),
        client=client,
    )
    assert restored_from_meta.batch_size == 7


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
    _upload_mock_panel_receptor(client)

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
    for col in (
        "pose_score",
        "binding_energy",
        "file_path",
        "gene_name",
        "pdb_id",
        "receptor_file_path",
        "structure_sha256",
        "panel_version",
    ):
        assert col in df.columns
    assert set(df["method"]) == {"docking"}

    poses = job._get_poses()
    assert isinstance(poses, PoseSet)
    assert len(poses) == len(_PANEL_ACCESSIONS)
    for pose in poses:
        assert isinstance(pose, Pose)
        assert pose.ligand_id == synced_ligand_id
        assert pose.local_path is not None, "_get_poses() downloads the SDF"
        assert pose.smiles is not None


def test_secondary_pharma__show_panel_pose_renders(
    client: DeepOriginClient,
) -> None:
    """``_show_panel_pose()`` downloads receptor + pose and builds Mol* HTML."""
    _assert_tool_available(client)
    client.files.upload(
        local_path=BRD_DATA_DIR / "brd-2.sdf",
        remote_path=MOCK_SECONDARY_PHARMA_POSE_SDF_PATH,
    )
    _upload_mock_panel_receptor(client)

    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    job.start()
    assert ligand.id is not None
    synced_ligand_id = ligand.id
    elapsed = 0.0
    while elapsed < 5.0:
        job.sync()
        if job.status in TERMINAL_STATES:
            break
        time.sleep(0.05)
        elapsed += 0.05
    assert is_success_status(job.status)

    target_uniprot = _PANEL_ACCESSIONS[0]
    mock_builder = MagicMock(return_value="<html>panel-pose</html>")
    with (
        patch(
            "deeporigin.viz.molstar_html.render_protein_with_poses_html",
            mock_builder,
        ),
        patch(
            "deeporigin.utils.notebook.render_html",
            side_effect=lambda html, **kwargs: html,
        ),
    ):
        html = job._show_panel_pose(
            ligand_id=synced_ligand_id,
            uniprot_id=target_uniprot,
        )

    assert html == "<html>panel-pose</html>"
    mock_builder.assert_called_once()
    call_kwargs = mock_builder.call_args.kwargs
    assert call_kwargs["ligand_payloads"]
    assert Path(call_kwargs["pdb_path"]).is_file()


def test_secondary_pharma__show_panel_pose_requires_receptor_file_path(
    client: DeepOriginClient,
) -> None:
    """``_show_panel_pose()`` fails clearly when receptor metadata is absent."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    row = {
        "ligand_id": "L1",
        "uniprot_id": _PANEL_ACCESSIONS[0],
        "file_path": MOCK_SECONDARY_PHARMA_POSE_SDF_PATH,
    }
    with (
        patch.object(
            job,
            "_panel_pose_row",
            return_value=row,
        ),
        pytest.raises(DeepOriginException, match="receptor_file_path"),
    ):
        job._show_panel_pose(ligand_id="L1", uniprot_id=_PANEL_ACCESSIONS[0])


# --- get_undocked_ligands() / get_missing_pairs() ---------------------------


def test_secondary_pharma_undocked_ligands_and_missing_pairs_after_reload(
    client: DeepOriginClient,
) -> None:
    """Both gap-checks find a ligand added after a real docking run completed.

    Regression: on a reloaded (``from_id``) unrestricted run, ``uniprots`` and
    ``_allowed_uniprots`` are both unset, so ``_expected_panel_pairs()`` used
    to collapse to an empty set and ``get_missing_pairs()`` silently reported
    nothing missing regardless of the actual gap.
    """
    _assert_tool_available(client)
    client.files.upload(
        local_path=BRD_DATA_DIR / "brd-2.sdf",
        remote_path=MOCK_SECONDARY_PHARMA_POSE_SDF_PATH,
    )

    docked_ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(
        ligands=[docked_ligand], method="docking", client=client
    )
    job.start()
    elapsed = 0.0
    while elapsed < 5.0:
        job.sync()
        if job.status in TERMINAL_STATES:
            break
        time.sleep(0.05)
        elapsed += 0.05
    assert is_success_status(job.status)

    # Nothing missing yet -- the one ligand is fully docked against the panel.
    assert job.get_undocked_ligands() is None
    assert job.get_missing_pairs() is None

    reloaded = SecondaryPharmacology.from_id(job.id, client=client)
    undocked_ligand = Ligand.from_smiles("c1ccccc1", name="benzene")
    undocked_ligand.id = "not-actually-docked"
    reloaded._ligands.append(undocked_ligand)

    undocked = reloaded.get_undocked_ligands()
    assert undocked is not None
    assert [lig.id for lig in undocked.ligands] == [undocked_ligand.id]

    missing = reloaded.get_missing_pairs()
    assert missing is not None
    assert {uniprot for _lig, uniprot in missing} == set(_PANEL_ACCESSIONS)
    assert {lig.id for lig, _uniprot in missing} == {undocked_ligand.id}


# --- list() -------------------------------------------------------------------


def _submit_job_with_dirty_smiles(client: DeepOriginClient) -> SecondaryPharmacology:
    """A completed ligand-ml run whose stored ligand smiles is multi-fragment.

    Ligand.from_smiles() self-normalizes at construction, so a ligand built
    the normal way never has a dirty smiles left to resubmit -- the payload
    is built normally, then patched with a raw multi-fragment smiles before
    submission, to reproduce a record actually stored that way (e.g. from
    an older client version, or a manual API call).
    """
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    payload = job._make_payload(approve_amount=None, sync=True)
    payload["inputs"]["ligands"][0]["smiles"] = "CCO.Cl"
    dto = client.executions.create(
        tool_key=job.tool_key, tool_version=job.tool_version, data=payload
    )
    job.update_from_dto(dto)
    assert is_success_status(job.status)
    return job


def _assert_no_user_warnings(caught: list) -> None:
    assert not any(issubclass(w.category, UserWarning) for w in caught), [
        str(w.message) for w in caught
    ]


def test_secondary_pharma_list_suppresses_ligand_hydration_warnings(
    client: DeepOriginClient,
) -> None:
    """list() doesn't leak from_dto()'s ligand-normalization warnings.

    Regression: Execution.list() rehydrates every returned execution via
    from_dto(), which reconstructs each stored ligand -- a stored record
    with a raw multi-fragment SMILES (e.g. a salt form) triggers
    Ligand.process_mol()'s UserWarning (naming the raw SMILES) as a side
    effect of just browsing past runs, not something the caller asked to
    see.
    """
    job = _submit_job_with_dirty_smiles(client)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        results = SecondaryPharmacology.list(status=["Completed"], client=client)

    assert any(r.id == job.id for r in results)
    _assert_no_user_warnings(caught)


def test_secondary_pharma_from_id_suppresses_ligand_hydration_warnings(
    client: DeepOriginClient,
) -> None:
    """from_id() doesn't leak the same warning either.

    Regression (review follow-up on the list() fix above): a list() ->
    pick id -> from_id() flow -- reloading one specific run after finding
    it by browsing -- rehydrates ligands the same way list() does, so it
    can leak the same SMILES-bearing warning even with list()'s own
    hydration silenced.
    """
    job = _submit_job_with_dirty_smiles(client)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reloaded = SecondaryPharmacology.from_id(job.id, client=client)

    assert reloaded.id == job.id
    _assert_no_user_warnings(caught)


def test_secondary_pharma_from_last_run_suppresses_ligand_hydration_warnings(
    client: DeepOriginClient,
) -> None:
    """from_last_run() doesn't leak the same warning either."""
    job = _submit_job_with_dirty_smiles(client)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reloaded = SecondaryPharmacology.from_last_run(client=client)

    assert reloaded.id == job.id
    _assert_no_user_warnings(caught)


# --- plot() -----------------------------------------------------------------


def test_secondary_pharma_plot_ligand_ml_labels_by_ligand_name(
    client: DeepOriginClient,
) -> None:
    """Heatmap rows are labeled by ligand name, not the raw SMILES, and dedupe."""
    _assert_tool_available(client)
    named = Ligand.from_smiles("CCO", name="ethanol")
    unnamed = Ligand.from_smiles("CCN")
    job = SecondaryPharmacology(
        ligands=[named, unnamed], method="ligand-ml", client=client
    )
    job.run()

    # run() backfills a real id for the unnamed ligand too -- plot() falls
    # back to a short id suffix for it, not a bare "ligand 1" placeholder.
    assert unnamed.id is not None

    with patch("deeporigin.plots.show") as mock_show:
        job.plot()
        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]
        row_labels = set(figure.y_range.factors)
        assert row_labels == {"ethanol", f"...{unnamed.id[-6:]}"}
        assert not any(label.startswith("CC") for label in row_labels), (
            "row labels must not be raw SMILES"
        )


def _rect_color_mapper(figure):
    """The LinearColorMapper driving a plot_grid_heatmap figure's cell fill."""
    renderer = next(r for r in figure.renderers if r.glyph.__class__.__name__ == "Rect")
    return renderer.glyph.fill_color["transform"]


def test_secondary_pharma_plot_docking_heatmap_metric_choice(
    client: DeepOriginClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Docking's plot() defaults to a binding_energy heatmap; metric= switches it.

    Both metrics use the same white-to-red hazard palette as ligand-ml's
    plot()
    """
    _assert_tool_available(client)
    client.files.upload(
        local_path=BRD_DATA_DIR / "brd-2.sdf",
        remote_path=MOCK_SECONDARY_PHARMA_POSE_SDF_PATH,
    )
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="docking", client=client)
    job.start()

    elapsed = 0.0
    while elapsed < 5.0:
        job.sync()
        if job.status in TERMINAL_STATES:
            break
        time.sleep(0.05)
        elapsed += 0.05
    assert is_success_status(job.status)

    with patch("deeporigin.plots.show") as mock_show:
        job.plot()
        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]
        assert "binding energy" in figure.title.text
        mapper = _rect_color_mapper(figure)
        assert mapper.palette == list(reversed(WHITE_RED_HAZARD_PALETTE))
        assert (mapper.low, mapper.high) != (0.0, 1.0), "auto-scaled, not fixed"

    with patch("deeporigin.plots.show") as mock_show:
        job.plot(metric="pose_score")
        mock_show.assert_called_once()
        figure = mock_show.call_args[0][0]
        mapper = _rect_color_mapper(figure)
        assert mapper.palette == WHITE_RED_HAZARD_PALETTE
        assert (mapper.low, mapper.high) != (0.0, 1.0), "auto-scaled, not fixed"
        assert "pose score" in figure.title.text

    # clim= overrides the auto-scaled range for whichever metric is active,
    # and out-of-range real values are visibly noted, not silently clipped.
    real_pose_score = job.get_results()["pose_score"].iloc[0]
    narrow_clim = (real_pose_score + 0.001, real_pose_score + 0.002)
    with patch("deeporigin.plots.show") as mock_show:
        job.plot(metric="pose_score", clim=narrow_clim)
        figure = mock_show.call_args[0][0]
        mapper = _rect_color_mapper(figure)
        assert (mapper.low, mapper.high) == narrow_clim
        out = capsys.readouterr().out
        # Every panel target's real pose_score falls outside this
        # deliberately narrow window -- at least the one it was built
        # around, guaranteed.
        assert "pose_score value(s)" in out
        assert f"({narrow_clim[0]}, {narrow_clim[1]})" in out
