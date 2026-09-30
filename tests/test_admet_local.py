"""Local mock-server tests for :class:`~deeporigin.drug_discovery.admet.Admet`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import pytest

from deeporigin.drug_discovery import Admet, Ligand
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from deeporigin.utils.constants import (
    ADMET_INLINE_LIGAND_CAP,
    ADMET_WORKFLOW_LIGAND_THRESHOLD,
)
from tests.conftest import assert_quote_only_execution, check_tool_exists
from tests.mock_server.routers.tools import (
    MOCK_ADMET_ENDPOINTS,
    _synthesize_admet_prediction_row,
)

if TYPE_CHECKING:
    from deeporigin.platform.client import DeepOriginClient

_ADMET_PROPERTIES = ["hERG_classification", "AMES_classification"]


def _assert_tool_available(client: DeepOriginClient) -> None:
    """Require the mock admet-properties definition."""
    cfg = TOOL_KEYS_AND_VERSIONS["admet"]
    assert check_tool_exists(client, cfg["tool_key"], cfg["tool_version"])


def _definition_enum(client: DeepOriginClient) -> list[str]:
    """Endpoint enum from the mock tool definition (independent of Admet)."""
    cfg = TOOL_KEYS_AND_VERSIONS["admet"]
    definition = client.tools.get(
        tool_key=cfg["tool_key"],
        tool_version=cfg["tool_version"],
    )
    return definition["inputs"]["properties"]["properties"]["items"]["enum"]


def test_admet_construct_copies_definition_enum(client: DeepOriginClient) -> None:
    """``Admet(...)`` fills ``properties`` from the live tool definition."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)

    enum = _definition_enum(client)
    assert enum == list(MOCK_ADMET_ENDPOINTS)
    assert job.properties == enum
    assert isinstance(job.properties, list)
    assert "Fu_regression" in job.properties
    assert job.tool_version == "2"


def test_admet_constructor_rejects_properties_kwarg(
    client: DeepOriginClient,
) -> None:
    """The constructor does not take ``properties=``."""
    ligand = Ligand.from_smiles("CCO")
    with pytest.raises(TypeError):
        Admet(  # ty:ignore[unexpected-keyword]
            ligands=[ligand],
            properties=_ADMET_PROPERTIES,
            client=client,
        )


def test_admet_properties_assign_and_inplace_trim(client: DeepOriginClient) -> None:
    """Draft ``properties`` can be replaced or trimmed in place."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)

    job.properties = list(_ADMET_PROPERTIES)
    assert job.properties == _ADMET_PROPERTIES

    job.properties.remove("AMES_classification")
    assert job.properties == ["hERG_classification"]

    with pytest.raises(ValueError, match="Unknown"):
        job.properties = ["not_an_endpoint"]
    with pytest.raises(ValueError, match="non-empty"):
        job.properties = []
    with pytest.raises(ValueError, match="duplicates"):
        job.properties = ["hERG_classification", "hERG_classification"]


def test_admet_run_sends_full_enum_when_untrimmed(
    client: DeepOriginClient,
) -> None:
    """Untrimmed ``run()`` sends the definition enum, not an omitted field."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)
    enum = list(job.properties)

    inputs = job._make_inputs()
    assert inputs["properties"] == enum

    df = job.run()

    assert isinstance(job.properties, tuple)
    assert list(job.properties) == enum
    for prop in enum:
        assert prop in df.columns
    with pytest.raises(AttributeError, match="execution id"):
        job.properties = ["hERG_classification"]


def test_admet_run_returns_dataframe(client: DeepOriginClient) -> None:
    """Normal ``run()`` returns a DataFrame with deterministic mock predictions."""
    _assert_tool_available(client)

    lig1 = Ligand.from_smiles("CCO")
    lig2 = Ligand.from_smiles("CCN")
    job = Admet(ligands=[lig1, lig2], client=client)
    job.properties = list(_ADMET_PROPERTIES)

    df = job.run()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    for prop in _ADMET_PROPERTIES:
        assert prop in df.columns
    assert job.status == "Completed"
    assert job.id is not None
    assert isinstance(job.properties, tuple)

    lid1 = lig1.id or "0"
    expected_lig1 = _synthesize_admet_prediction_row(
        smiles="CCO",
        ligand_id=str(lid1),
        requested=_ADMET_PROPERTIES,
    )
    row1 = df[df["ligand_id"].astype(str) == str(lid1)].iloc[0]
    for prop in _ADMET_PROPERTIES:
        assert row1[prop] == expected_lig1[prop]


def test_admet_run_quote_true(client: DeepOriginClient) -> None:
    """``run(quote=True)`` returns the job with estimate; no prediction DataFrame."""
    _assert_tool_available(client)

    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)
    job.properties = list(_ADMET_PROPERTIES)
    result = job.run(quote=True)

    assert result is job
    assert ligand.id is None
    assert_quote_only_execution(job)
    assert isinstance(job.properties, tuple)


def test_admet_run_rejects_cleared_properties(client: DeepOriginClient) -> None:
    """In-place empty ``properties`` fails at ``run()``."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)
    job.properties.clear()
    with pytest.raises(ValueError, match="non-empty"):
        job.run()


def test_admet_make_inputs_defaults_method_to_togo(client: DeepOriginClient) -> None:
    """Default ``method`` is Togo and is omitted from inputs (tool default)."""
    _assert_tool_available(client)

    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)
    job.properties = list(_ADMET_PROPERTIES)
    inputs = job._make_inputs()

    assert job.method == "togo"
    assert "method" not in inputs
    assert inputs["properties"] == _ADMET_PROPERTIES


def test_admet_make_inputs_includes_method(client: DeepOriginClient) -> None:
    """``method`` is forwarded to the tool inputs payload."""
    _assert_tool_available(client)

    ligand = Ligand.from_smiles("CCO")
    job = Admet(
        ligands=[ligand],
        method="maplight",
        client=client,
    )
    job.properties = list(_ADMET_PROPERTIES)
    inputs = job._make_inputs()

    assert inputs["method"] == "maplight"
    assert inputs["properties"] == _ADMET_PROPERTIES


def test_admet_from_dto_restores_recorded_properties(
    client: DeepOriginClient,
) -> None:
    """``from_dto`` restores the subset that ran; it does not refetch latest."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)
    job.properties = list(_ADMET_PROPERTIES)
    job.run()
    assert job.dto is not None

    restored = Admet.from_dto(job.dto, client=client)
    assert restored.id == job.id
    assert restored.properties == tuple(_ADMET_PROPERTIES)
    assert isinstance(restored.properties, tuple)
    with pytest.raises(AttributeError, match="execution id"):
        restored.properties = ["hERG_classification"]


def _historical_omit_dto() -> dict:
    """Completed Admet DTO whose stored inputs omitted properties."""
    return {
        "executionId": "admet-historical-omit",
        "status": "Completed",
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["admet"]["tool_key"],
            "version": "0.8.4",
        },
        "userInputs": {
            "ligands": [{"smiles": "CCO", "id": "0"}],
        },
        "jobOutputs": {
            "admet_properties": [
                {
                    "smiles": "CCO",
                    "ligand_id": "0",
                    "hERG_classification": 0.1,
                }
            ]
        },
    }


def test_admet_from_dto_omitted_properties_stays_none(
    client: DeepOriginClient,
) -> None:
    """A historical payload that omitted properties keeps ``properties is None``."""
    restored = Admet.from_dto(_historical_omit_dto(), client=client)
    assert restored.properties is None
    assert restored.ligands[0].smiles == "CCO"
    assert restored.method == "togo"


def test_admet_duplicate_makes_properties_writable(
    client: DeepOriginClient,
) -> None:
    """``duplicate()`` clears ``id`` and returns a mutable properties list."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)
    job.properties = list(_ADMET_PROPERTIES)
    job.run()

    copy = job.duplicate()
    assert copy.id is None
    assert isinstance(copy.properties, list)
    copy.properties = ["hERG_classification"]
    assert copy.properties == ["hERG_classification"]


def test_admet_from_dto_duplicate_can_assign_properties(
    client: DeepOriginClient,
) -> None:
    """``from_dto`` then ``duplicate()`` fetches the enum so assignment works."""
    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)
    job.properties = list(_ADMET_PROPERTIES)
    job.run()
    assert job.dto is not None

    restored = Admet.from_dto(job.dto, client=client)
    copy = restored.duplicate()
    assert copy.id is None
    copy.properties = ["hERG_classification"]
    assert copy.properties == ["hERG_classification"]


def test_admet_from_dto_duplicate_fills_omitted_properties(
    client: DeepOriginClient,
) -> None:
    """``duplicate()`` of an omitted-properties DTO fills the live enum."""
    _assert_tool_available(client)
    restored = Admet.from_dto(_historical_omit_dto(), client=client)
    assert restored.properties is None

    copy = restored.duplicate()
    enum = _definition_enum(client)
    assert copy.id is None
    assert copy.properties == enum
    assert isinstance(copy.properties, list)
    copy.properties.remove("AMES_classification")
    assert "AMES_classification" not in copy.properties


def test_admet_run_quoted_parks_without_dataframe(client: DeepOriginClient) -> None:
    """When cost requires confirmation, ``run()`` returns ``None`` (Docking parity)."""

    _assert_tool_available(client)
    ligand = Ligand.from_smiles("CCO")
    job = Admet(ligands=[ligand], client=client)
    job.properties = list(_ADMET_PROPERTIES)
    # Force a Quoted response without using quote=True (approve cap below estimate).
    result = job.run(approve_amount=0)
    assert result is None
    assert job.status == "Quoted"


def test_admet_start_above_inline_cap_uses_ligands_file(
    client: DeepOriginClient,
) -> None:
    """Batches above the inline cap submit ``ligands_file`` and ``ligands_count``."""

    _assert_tool_available(client)
    n = ADMET_INLINE_LIGAND_CAP + 1
    ligands = [Ligand.from_smiles("CCO")] * n
    job = Admet(ligands=ligands, client=client)
    inputs = job._make_inputs()
    assert "ligands" not in inputs
    assert inputs["ligands_count"] == n
    remote = inputs["ligands_file"]
    assert remote.startswith("admet-properties/ligand-lists/")

    job.start()
    dto = job._dto or {}
    stored = dto.get("userInputs") or {}
    assert stored.get("ligands_file") == remote
    assert stored.get("ligands_count") == n


def test_admet_run_rejects_workflow_scale_batch(client: DeepOriginClient) -> None:
    """``run()`` refuses 101+ ligands."""

    n = ADMET_WORKFLOW_LIGAND_THRESHOLD
    job = Admet(ligands=[Ligand.from_smiles("CCO")] * n, client=client)
    with pytest.raises(ValueError, match="run\\(\\) supports at most"):
        job.run()


def test_admet_project_wide_start(client: DeepOriginClient) -> None:
    """``ligands=[]`` submits ``project.id`` from ``client.project_id``."""

    _assert_tool_available(client)
    job = Admet(ligands=[], client=client)
    job.properties = list(_ADMET_PROPERTIES)
    inputs = job._make_inputs()
    assert inputs["project"]["id"] == client.project_id
    assert "ligands" not in inputs
    job.start()
    assert job.id is not None
