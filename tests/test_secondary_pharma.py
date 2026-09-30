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
import base64
import hashlib
import json
from pathlib import Path
import time
from typing import TYPE_CHECKING
from unittest.mock import patch
import uuid

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
    MOCK_SECONDARY_PHARMA_PANEL_VERSION,
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
    """``get_poses()`` is docking only."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)
    with pytest.raises(ValueError, match="get_results\\("):
        job.get_poses()


def test_secondary_pharma_get_poses_rejects_self_test(client: DeepOriginClient) -> None:
    """``get_poses()`` refuses a self_test docking run.

    The constructor rejects ``self_test=True`` with ``method="docking"``
    outright (see ``test_secondary_pharma_self_test_rejects_docking``), but
    a legacy execution created before that guard existed can still
    rehydrate via ``from_dto`` into this exact shape -- this test covers
    that path via a hand-built DTO, not the constructor. The platform's
    baked test ligand has no ligand id, so no panel_poses rows are ever
    published for it -- get_poses() would otherwise either raise an opaque
    "no results" error or (if jobOutputs happened to carry the rows) fail
    inside Pose.from_json on the missing ligand_id.
    """
    job = SecondaryPharmacology.from_dto(
        _hand_built_docking_dto(self_test=True), client=client
    )
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
    ):
        assert col in df.columns
    assert "p_affinity" not in df.columns
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
    # p_affinity is hidden regardless of which the platform set; when the
    # platform set p_affinity (not p_active), p_active is NaN here.
    if expected["p_active"] is None:
        assert pd.isna(row["p_active"])
    else:
        assert row["p_active"] == expected["p_active"]


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

    poses = job.get_poses()
    assert isinstance(poses, PoseSet)
    assert len(poses) == len(_PANEL_ACCESSIONS)
    for pose in poses:
        assert isinstance(pose, Pose)
        assert pose.ligand_id == synced_ligand_id
        assert pose.local_path is not None, "get_poses() downloads the SDF"
        assert pose.smiles is not None
        receptor = pose.props.get("receptor_local_path")
        assert receptor is not None, "get_poses() downloads the panel receptor"
        assert Path(receptor).is_file()


def test_secondary_pharma_show_panel_pose_renders(client: DeepOriginClient) -> None:
    """``show_panel_pose()`` builds a viewer holding the panel receptor and the labeled pose.

    Only the notebook display is replaced; the viewer HTML is the real thing.
    """
    job = _completed_docking_job(client)
    ligand = job.ligands[0]
    accession, gene, _pdb = MOCK_SECONDARY_PHARMA_PANEL[0]
    receptor_text = (Path(__file__).parent / "fixtures" / "1eby.pdb").read_text(
        encoding="utf-8"
    )
    receptor_b64 = base64.b64encode(receptor_text.encode("utf-8")).decode("ascii")

    with patch(
        "deeporigin.utils.notebook.render_html",
        side_effect=lambda html, **kwargs: html,
    ):
        by_accession = job.show_panel_pose(ligand_id=ligand.id, uniprot_id=accession)
        by_gene = job.show_panel_pose(ligand=ligand, gene_name=gene)

    for html in (by_accession, by_gene):
        assert "visualizeDockedLigands" in html
        assert receptor_b64 in html, "the panel receptor is in the viewer"
    assert f"{gene} (" in by_gene, "the pose is labeled with its target"


def test_secondary_pharma_show_panel_pose_matches_unsynced_ligand_by_smiles(
    client: DeepOriginClient,
) -> None:
    """A ligand rebuilt from SMILES (no id), as after reloading a run, still finds its pose."""
    job = _completed_docking_job(client)
    rebuilt = Ligand.from_smiles(job.ligands[0].smiles)
    assert rebuilt.id is None
    _accession, gene, _pdb = MOCK_SECONDARY_PHARMA_PANEL[0]

    with patch(
        "deeporigin.utils.notebook.render_html",
        side_effect=lambda html, **kwargs: html,
    ):
        html = job.show_panel_pose(ligand=rebuilt, gene_name=gene)
        assert "visualizeDockedLigands" in html
        with pytest.raises(ValueError, match="No panel poses"):
            job.show_panel_pose(ligand=Ligand.from_smiles("CCCCN"), gene_name=gene)


def test_secondary_pharma_show_panel_pose_ligand_lookup_errors(
    client: DeepOriginClient,
) -> None:
    """Ligand arguments must agree, and an ambiguous SMILES points at ``ligand_id``."""
    job = _completed_docking_job(client)
    synced = job.ligands[0]
    _accession, gene, _pdb = MOCK_SECONDARY_PHARMA_PANEL[0]

    with pytest.raises(ValueError, match="does not match ligand.id"):
        job.show_panel_pose(ligand_id="OTHER", ligand=synced, gene_name=gene)
    with pytest.raises(ValueError, match="Provide ligand_id or a ligand"):
        job.show_panel_pose(gene_name=gene)
    with pytest.raises(ValueError, match="Pass ligand_id from get_results"):
        job.show_panel_pose(ligand=Ligand.from_smiles("CCCCN"), gene_name=gene)

    def _twin(rows: list[dict]) -> None:
        source = next(row for row in rows if row["gene_name"] == gene)
        rows.append({**source, "ligand_id": "TWIN"})

    with _with_mutated_rows(_twin):
        with pytest.raises(ValueError, match="Several ligands share this SMILES"):
            job.show_panel_pose(
                ligand=Ligand.from_smiles(synced.smiles), gene_name=gene
            )


def test_secondary_pharma_show_panel_pose_needs_exactly_one_matching_pose(
    client: DeepOriginClient,
) -> None:
    """The target is named once, and must match a pose from this run."""
    job = _completed_docking_job(client)
    ligand_id = job.ligands[0].id
    accession, gene, _pdb = MOCK_SECONDARY_PHARMA_PANEL[0]

    with pytest.raises(ValueError, match="exactly one of uniprot_id or gene_name"):
        job.show_panel_pose(ligand_id=ligand_id)
    with pytest.raises(ValueError, match="exactly one of uniprot_id or gene_name"):
        job.show_panel_pose(ligand_id=ligand_id, uniprot_id=accession, gene_name=gene)
    with pytest.raises(ValueError, match="No panel poses"):
        job.show_panel_pose(ligand_id=ligand_id, gene_name="NOT-A-GENE")


def test_secondary_pharma_show_panel_pose_requires_receptor_file_path(
    client: DeepOriginClient,
) -> None:
    """``show_panel_pose()`` fails clearly when receptor metadata is absent."""
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
        job.show_panel_pose(ligand_id="L1", uniprot_id=_PANEL_ACCESSIONS[0])


def _completed_docking_job(client: DeepOriginClient) -> SecondaryPharmacology:
    """Run a docking job to completion on the local mock, receptor and SDF staged."""
    _assert_tool_available(client)
    client.files.upload(
        local_path=BRD_DATA_DIR / "brd-2.sdf",
        remote_path=MOCK_SECONDARY_PHARMA_POSE_SDF_PATH,
    )
    _upload_mock_panel_receptor(client)
    job = SecondaryPharmacology(
        ligands=[Ligand.from_smiles("CCO")], method="docking", client=client
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
    return job


def _with_mutated_rows(mutate):
    """Patch ``_load_panel_pose_rows`` so its real rows pass through ``mutate``."""
    from deeporigin.drug_discovery import secondary_pharma

    real = secondary_pharma._load_panel_pose_rows

    def _wrapped(*args, **kwargs):
        rows = real(*args, **kwargs)
        mutate(rows)
        return rows

    return patch.object(secondary_pharma, "_load_panel_pose_rows", _wrapped)


def test_secondary_pharma_get_poses_row_without_receptor_still_returns_pose(
    client: DeepOriginClient,
) -> None:
    """A row with an absent or null ``receptor_file_path`` yields a pose without one."""
    job = _completed_docking_job(client)

    def _strip(rows: list[dict]) -> None:
        for i, row in enumerate(rows):
            if i % 2:
                row["receptor_file_path"] = None
            else:
                row.pop("receptor_file_path", None)

    with _with_mutated_rows(_strip):
        poses = job.get_poses()

    assert len(poses) == len(_PANEL_ACCESSIONS)
    assert all("receptor_local_path" not in pose.props for pose in poses)


def test_secondary_pharma_get_poses_rejects_receptor_digest_mismatch(
    client: DeepOriginClient,
) -> None:
    """Receptor bytes that don't match ``structure_sha256`` are rejected clearly."""
    job = _completed_docking_job(client)

    def _bad_digest(rows: list[dict]) -> None:
        for row in rows:
            row["structure_sha256"] = "0" * 64

    with _with_mutated_rows(_bad_digest):
        with pytest.raises(DeepOriginException, match="digest mismatch"):
            job.get_poses()
        # Opt-out still hands back the pose and receptor.
        poses = job.get_poses(verify_receptor_digest=False)
    assert all(Path(p.props["receptor_local_path"]).is_file() for p in poses)


def test_secondary_pharma_get_poses_digest_check_ignores_case(
    client: DeepOriginClient,
) -> None:
    """A correct ``structure_sha256`` written in uppercase is not a mismatch."""
    job = _completed_docking_job(client)
    receptor = (Path(__file__).parent / "fixtures" / "1eby.pdb").read_bytes()

    def _upper_digest(rows: list[dict]) -> None:
        for row in rows:
            row["structure_sha256"] = hashlib.sha256(receptor).hexdigest().upper()

    with _with_mutated_rows(_upper_digest):
        poses = job.get_poses()
    assert all(Path(p.props["receptor_local_path"]).is_file() for p in poses)


@pytest.mark.parametrize(
    "bad_path",
    [
        "protected/../secrets/x.pdb",
        "protected\\..\\x.pdb",
        "someorg/panels/v1/x.pdb",
        "protected/%2e%2e/x.pdb",
        "protected/a\x00b.pdb",
    ],
)
def test_secondary_pharma_get_poses_rejects_unsafe_receptor_path(
    client: DeepOriginClient, bad_path: str
) -> None:
    """A receptor path outside ``protected/`` or with ``..`` is refused, not fetched."""
    job = _completed_docking_job(client)

    def _bad_path(rows: list[dict]) -> None:
        for row in rows:
            row["receptor_file_path"] = bad_path

    with (
        _with_mutated_rows(_bad_path),
        patch.object(PoseSet, "download", side_effect=AssertionError("downloaded")),
    ):
        # Refused before any pose file is downloaded.
        with pytest.raises(DeepOriginException, match="Invalid panel file path"):
            job.get_poses()


def test_secondary_pharma_get_poses_redownloads_corrupted_cached_receptor(
    client: DeepOriginClient,
) -> None:
    """A cached receptor that fails its digest check is re-downloaded once."""
    job = _completed_docking_job(client)
    first = job.get_poses()
    cached = Path(first[0].props["receptor_local_path"])
    good_bytes = (Path(__file__).parent / "fixtures" / "1eby.pdb").read_bytes()
    assert cached.read_bytes() == good_bytes

    cached.write_bytes(b"corrupted")
    second = job.get_poses()

    assert Path(second[0].props["receptor_local_path"]) == cached
    assert cached.read_bytes() == good_bytes


def test_secondary_pharma_get_results_rejects_self_test_docking(
    client: DeepOriginClient,
) -> None:
    """A rehydrated self_test docking run gets a clear error from ``get_results()``."""
    job = SecondaryPharmacology.from_dto(
        _hand_built_docking_dto(self_test=True), client=client
    )
    with pytest.raises(ValueError, match="self_test"):
        job.get_results()


def test_secondary_pharma_backfill_keeps_api_supplied_ligand_ids(
    client: DeepOriginClient,
) -> None:
    """Backfill fills missing ids from SMILES but never overwrites an existing one."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    ligand.id = "local-id"  # already synced, so backfill's sync is a no-op
    job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml", client=client)

    with_ids = pd.DataFrame(
        {
            "ligand_smiles": [ligand.smiles, ligand.smiles, "C"],
            "ligand_id": ["api-id", None, None],
        }
    )
    out = job._backfill_ligand_ids(with_ids)
    assert out["ligand_id"].tolist()[:2] == ["api-id", "local-id"]
    assert pd.isna(out["ligand_id"].iloc[2]), "unmatched SMILES stays missing"

    no_ids = pd.DataFrame({"ligand_smiles": [ligand.smiles]})
    assert job._backfill_ligand_ids(no_ids)["ligand_id"].tolist() == ["local-id"]


# --- list(): project scoping through a real tool subclass ------------------------


def test_secondary_pharma_list_and_from_last_run_are_scoped_to_the_client_project(
    client: DeepOriginClient,
) -> None:
    """``list()`` and ``from_last_run()`` return only this project's runs, newest first.

    Runs real ligand-ml executions through the local mock server under two
    projects (``client.project_id`` is mutable) and lists them back, covering
    ``Execution.list()``'s project scoping through a real tool subclass.
    """
    _assert_tool_available(client)
    project_a = f"scope-a-{uuid.uuid4().hex}"
    project_b = f"scope-b-{uuid.uuid4().hex}"

    def run_in(project_id: str) -> str:
        client.project_id = project_id
        job = SecondaryPharmacology(
            ligands=[Ligand.from_smiles("CCO")], method="ligand-ml", client=client
        )
        job.run()
        assert job.id is not None
        return job.id

    first_in_a, second_in_a, only_in_b = (
        run_in(project_a),
        run_in(project_a),
        run_in(project_b),
    )

    client.project_id = project_a
    listed = SecondaryPharmacology.list(client=client)
    assert [job.id for job in listed] == [second_in_a, first_in_a]
    assert all(job.method == "ligand-ml" for job in listed)
    # The newest run overall is in the other project; this project's newest wins.
    assert SecondaryPharmacology.from_last_run(client=client).id == second_in_a

    client.project_id = project_b
    assert [job.id for job in SecondaryPharmacology.list(client=client)] == [only_in_b]
    assert SecondaryPharmacology.from_last_run(client=client).id == only_in_b

    # With no project set there is nothing to scope to, so everything is listed.
    client.project_id = None
    everything = {job.id for job in SecondaryPharmacology.list(client=client)}
    assert {first_in_a, second_in_a, only_in_b} <= everything
    assert SecondaryPharmacology.from_last_run(client=client).id == only_in_b


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


# --- run history: the panel a run actually used ----------------------------------


def test_secondary_pharma_results_stamp_the_panel_version(
    client: DeepOriginClient,
) -> None:
    """Loading a run's results notes the panel it ran against; the request is untouched."""
    job = _completed_docking_job(client)
    reloaded = SecondaryPharmacology.from_id(job.id, client=client)

    assert reloaded.panel_version is None, "not known until results are loaded"
    reloaded.get_results()
    assert reloaded.panel_version == MOCK_SECONDARY_PHARMA_PANEL_VERSION
    assert reloaded.uniprots is None, "what was asked for is left as asked"


def test_secondary_pharma_ligand_ml_runs_have_no_panel_version(
    client: DeepOriginClient,
) -> None:
    """Ligand-ml results don't name a panel version, so there is nothing to stamp."""
    _assert_tool_available(client)
    job = SecondaryPharmacology(
        ligands=[Ligand.from_smiles("CCO")], method="ligand-ml", client=client
    )
    job.run()
    assert job.panel_version is None


def test_secondary_pharma_gap_checks_use_the_panel_the_run_used(
    client: DeepOriginClient,
) -> None:
    """A panel that grew later isn't a gap, because the run's own version is used.

    Runs whose results don't name a version can only fall back to the live
    panel, so they do see the new target as missing.
    """
    job = _completed_docking_job(client)
    reloaded = SecondaryPharmacology.from_id(job.id, client=client)
    added_later = "Q99999"
    grown_panel = [*_definition_enum(client), added_later]

    with patch.object(
        SecondaryPharmacology, "_fetch_definition_uniprots", return_value=grown_panel
    ):
        assert reloaded.get_missing_pairs() is None

        def _unversioned(rows: list[dict]) -> None:
            for row in rows:
                row.pop("panel_version", None)

        legacy = SecondaryPharmacology.from_id(job.id, client=client)
        with _with_mutated_rows(_unversioned):
            legacy_missing = legacy.get_missing_pairs()

    assert legacy.panel_version is None
    assert legacy_missing is not None
    assert {uniprot for _ligand, uniprot in legacy_missing} == {added_later}


def test_secondary_pharma_rows_from_two_panel_versions_are_an_error(
    client: DeepOriginClient,
) -> None:
    """Rows from two panel versions can't belong to one run, so reading them is an error."""
    job = _completed_docking_job(client)

    def _mix(rows: list[dict]) -> None:
        rows[0]["panel_version"] = "mock-panel-v2"

    with _with_mutated_rows(_mix):
        reloaded = SecondaryPharmacology.from_id(job.id, client=client)
        with pytest.raises(DeepOriginException, match="more than one panel version"):
            reloaded.get_results()


def test_secondary_pharma_get_panel_by_version(client: DeepOriginClient) -> None:
    """``get_panel(panel_version=...)`` returns exactly that version's members."""
    panel = SecondaryPharmacology.get_panel(
        panel_version=MOCK_SECONDARY_PHARMA_PANEL_VERSION, full=True, client=client
    )
    assert list(panel["uniprot_id"]) == _PANEL_ACCESSIONS
    assert list(panel["gene_name"]) == [
        gene for _, gene, _ in MOCK_SECONDARY_PHARMA_PANEL
    ]


def test_secondary_pharma_get_panel_by_version_rejects_bad_and_unknown_versions(
    client: DeepOriginClient,
) -> None:
    """An unsafe or oversized version is a clean error; an unknown one leaves no cache behind."""
    from deeporigin.utils.env import _ensure_do_folder

    with pytest.raises(DeepOriginException, match="Invalid panel file path"):
        SecondaryPharmacology.get_panel(panel_version="../secrets", client=client)
    with pytest.raises(DeepOriginException):
        SecondaryPharmacology.get_panel(panel_version="a" * 400, client=client)

    with pytest.raises(DeepOriginException, match="Panel catalog unavailable"):
        SecondaryPharmacology.get_panel(panel_version="mock-panel-v404", client=client)
    assert not (
        _ensure_do_folder() / "protected" / "panels" / "mock-panel-v404"
    ).exists()


def test_secondary_pharma_get_panel_recovers_from_a_corrupt_cached_catalog(
    client: DeepOriginClient,
) -> None:
    """A truncated cached catalog is fetched again instead of failing forever."""
    from deeporigin.utils.env import _ensure_do_folder

    version = MOCK_SECONDARY_PHARMA_PANEL_VERSION
    SecondaryPharmacology.get_panel(panel_version=version, full=True, client=client)
    cached = _ensure_do_folder() / "protected" / "panels" / version / "members.json"
    cached.write_text('{"members": [{"uniprot')

    panel = SecondaryPharmacology.get_panel(
        panel_version=version, full=True, client=client
    )
    assert list(panel["uniprot_id"]) == _PANEL_ACCESSIONS
    assert json.loads(cached.read_text())["members"], "the cache was repaired"


def test_secondary_pharma_duplicate_forgets_the_panel_version(
    client: DeepOriginClient,
) -> None:
    """A duplicated draft hasn't run yet, so it carries no panel version."""
    job = _completed_docking_job(client)
    job.get_results()
    assert job.panel_version == MOCK_SECONDARY_PHARMA_PANEL_VERSION
    assert job.duplicate().panel_version is None


def test_secondary_pharma_new_execution_id_forgets_the_panel_version(
    client: DeepOriginClient,
) -> None:
    """Re-syncing the same execution keeps its panel version; a new execution drops it."""
    job = _completed_docking_job(client)
    job.get_results()
    assert job.panel_version == MOCK_SECONDARY_PHARMA_PANEL_VERSION

    job.update_from_dto(dict(job._dto))
    assert job.panel_version == MOCK_SECONDARY_PHARMA_PANEL_VERSION

    job.update_from_dto({**job._dto, "executionId": "another-execution"})
    assert job.panel_version is None


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
