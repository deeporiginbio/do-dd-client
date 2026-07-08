"""Tests for :mod:`deeporigin.drug_discovery.patent`."""

from __future__ import annotations

import json
from pathlib import Path
import time
from unittest.mock import patch

import pandas as pd
import pytest

from deeporigin.drug_discovery.patent import (
    Patent,
    _patent_ligands_with_results_dataframe,
    _patent_results_dataframe,
)
from deeporigin.platform.client import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS
from tests.conftest import FIXTURES_DIR, check_tool_exists

PATENT_PDF_PATH = FIXTURES_DIR / "patent" / "one-page.pdf"


def test_patent_build_params_uploads_pdf(client: DeepOriginClient) -> None:
    """_build_params uploads the PDF and returns a UFA input_file ref."""
    patent = Patent(pdf=PATENT_PDF_PATH, client=client)
    with patch.object(client.files, "upload") as upload_mock:
        params = patent._build_params()

    upload_mock.assert_called_once()
    assert params["input_file"]["$provider"] == "ufa"
    assert params["input_file"]["key"].startswith("patent/")
    assert patent.remote_pdf_path == params["input_file"]["key"]


def test_patent_start_quote_populates_estimate(client: DeepOriginClient) -> None:
    """start(quote=True) should set estimate from quotationResult.priceTotal."""
    patent = Patent(pdf=PATENT_PDF_PATH, name="Test Patent", client=client)
    quoted_dto = {
        "executionId": "exec-quoted",
        "status": "Quoted",
        "approveAmount": 0,
        "tool": {
            "key": TOOL_KEYS_AND_VERSIONS["patent"]["tool_key"],
            "version": "1.3.5",
        },
        "quotationResult": {
            "successfulQuotations": [{"priceTotal": 0.1}],
        },
    }
    with (
        patch.object(client.files, "upload"),
        patch.object(client.executions, "create", return_value=quoted_dto),
    ):
        patent.start(quote=True)

    assert patent.id == "exec-quoted"
    assert patent.status == "Quoted"
    assert patent.estimate == pytest.approx(0.1)
    assert patent.cost is None


def test_patent_start_rejects_non_none_status(client: DeepOriginClient) -> None:
    """start() raises ValueError when the execution is already in a non-None state."""
    patent = Patent(pdf=PATENT_PDF_PATH, client=client)
    patent._id = "exec-quoted-123"
    patent.status = "Quoted"

    with pytest.raises(ValueError, match="'Quoted'"):
        patent.start()


def test_patent_validates_pdf_path(tmp_path: Path) -> None:
    """Constructor rejects missing files and non-PDF extensions."""
    with pytest.raises(ValueError, match="not found"):
        Patent(pdf="/no/such/file.pdf")

    txt = tmp_path / "not-a-pdf.txt"
    txt.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected a .pdf"):
        Patent(pdf=txt)


def test_patent_from_dto_round_trip(client: DeepOriginClient) -> None:
    """from_dto rehydrates remote PDF path and execution fields."""
    fixture_path = FIXTURES_DIR / "executions" / "patent-test-execution.json"
    dto = json.loads(fixture_path.read_text())

    patent = Patent.from_dto(dto, client=client)

    assert patent.id == dto["executionId"]
    assert patent.status == dto["status"]
    assert patent.pdf is None
    assert patent.remote_pdf_path == "patent/one-page.pdf"
    assert patent.name == dto["name"]


def test_patent_from_dto_raises_on_tool_key_mismatch(client: DeepOriginClient) -> None:
    """from_dto fails fast when DTO tool key does not match Patent.tool_key."""
    dto = {
        "executionId": "x",
        "status": "Completed",
        "tool": {"key": "deeporigin.docking", "version": "3"},
        "userInputs": {
            "input_file": {"$provider": "ufa", "key": "patent/x.pdf"},
        },
    }
    with pytest.raises(ValueError, match="tool key mismatch"):
        Patent.from_dto(dto, client=client)


def test_patent_results_dataframe_maps_ligand_columns() -> None:
    """_patent_results_dataframe maps do-patent rows to ligand-oriented columns."""
    fixture_path = FIXTURES_DIR / "result-explorer-patent.json"
    response = json.loads(fixture_path.read_text())

    df = _patent_results_dataframe(response)

    assert df is not None
    assert list(df.columns[:2]) == ["smiles", "name"]
    assert len(df) == 2
    assert df.iloc[0]["smiles"] == "CCO"
    assert df.iloc[0]["name"] == "ethanol"


def test_patent_get_results_returns_none_before_success(
    client: DeepOriginClient,
) -> None:
    """get_results returns None when the job has not succeeded."""
    patent = Patent(pdf=PATENT_PDF_PATH, client=client)
    patent._id = "exec-running"
    patent.status = "Running"

    with patch.object(Patent, "sync"):
        result = patent.get_results()

    assert result is None


def test_patent_ligands_with_results_dataframe_maps_nested_results() -> None:
    """_patent_ligands_with_results_dataframe flattens ligand.results rows."""
    response = {
        "data": [
            {
                "id": "lig-1",
                "smiles": "CCO",
                "results": [
                    {
                        "page": 5,
                        "smiles": "CCO",
                        "iupac_name": "ethanol",
                        "confidence": 0.9,
                        "type": "S",
                        "record_id": "rec-1",
                        "source": "one-page.pdf",
                    }
                ],
            }
        ]
    }
    df = _patent_ligands_with_results_dataframe(response)
    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["smiles"] == "CCO"
    assert df.iloc[0]["name"] == "ethanol"


def test_patent_get_results_falls_back_to_job_outputs(client: DeepOriginClient) -> None:
    """get_results uses jobOutputs when the result explorer returns no rows."""
    patent = Patent(pdf=PATENT_PDF_PATH, client=client)
    patent._id = "exec-done"
    patent.status = "Completed"
    patent._dto = {
        "jobOutputs": {
            "do_patent_molecules": [
                {
                    "record_id": "rec-001",
                    "source": "one-page.pdf",
                    "page": 1,
                    "smiles": "CCO",
                    "confidence": 0.9,
                    "confidence_details": None,
                    "type": "S",
                    "extracted_image_path": None,
                    "predicted_structure_image_path": None,
                    "iupac_name": "ethanol",
                    "created_at": "2025-11-06T19:20:00.000Z",
                },
            ],
        },
    }

    with (
        patch.object(Patent, "sync"),
        patch(
            "deeporigin.drug_discovery.patent._fetch_patent_ligands_with_results",
            return_value={"data": []},
        ),
        patch.object(client.results, "get", return_value={"data": []}),
    ):
        df = patent.get_results()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["smiles"] == "CCO"


def test_patent_get_results_builds_dataframe(client: DeepOriginClient) -> None:
    """get_results returns a ligand DataFrame from ligands_with_results."""
    patent = Patent(pdf=PATENT_PDF_PATH, client=client)
    patent._id = "47de46da-71f6-4cb0-84b3-dcaadf01d04e"
    patent.status = "Completed"
    patent.tool_version = "1.3.5"

    ligands_response = {
        "data": [
            {
                "id": "lig-1",
                "smiles": "CCO",
                "results": [
                    {
                        "page": 1,
                        "smiles": "CCO",
                        "iupac_name": "ethanol",
                        "confidence": 0.9,
                        "type": "S",
                        "record_id": "rec-001",
                        "source": "one-page.pdf",
                    }
                ],
            }
        ]
    }

    with (
        patch.object(Patent, "sync"),
        patch(
            "deeporigin.drug_discovery.patent._fetch_patent_ligands_with_results",
            return_value=ligands_response,
        ),
    ):
        df = patent.get_results()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["smiles"] == "CCO"


def test_patent_cancel_while_running(client: DeepOriginClient) -> None:
    """cancel() calls executions.cancel and syncs state."""
    patent = Patent(pdf=PATENT_PDF_PATH, client=client)
    patent._id = "exec-cancel"
    patent.status = "Running"

    cancelled_dto = {
        "executionId": "exec-cancel",
        "status": "Cancelled",
        "tool": {"key": patent.tool_key, "version": "1.3.5"},
    }
    with (
        patch.object(client.executions, "cancel") as cancel_mock,
        patch.object(client.executions, "get", return_value=cancelled_dto),
    ):
        patent.cancel()

    cancel_mock.assert_called_once_with("exec-cancel")
    assert patent.status == "Cancelled"


def test_patent_start_quote_true_lv1(client: DeepOriginClient) -> None:
    """Patent.start(quote=True) returns Quoted status and sets estimate."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["patent"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["patent"]["tool_version"],
    ), "Patent tool not registered on platform (expected key/version)."

    patent = Patent(pdf=PATENT_PDF_PATH, client=client)
    patent.start(quote=True)

    if patent.status == "FailedQuotation":
        pytest.skip(
            f"Patent quote returned FailedQuotation on {client.env}; platform tool may be unavailable."
        )
    assert patent.status == "Quoted"
    assert patent.estimate is not None
    if patent.estimate <= 0:
        pytest.skip(
            f"Patent quote on {client.env} returned non-positive estimate "
            f"({patent.estimate!r}); skipping price assertion."
        )
    assert patent.cost is None


def test_patent_cancel_lv1(client: DeepOriginClient) -> None:
    """Start a run and cancel it while queued or running."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["patent"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["patent"]["tool_version"],
    ), "Patent tool not registered on platform (expected key/version)."

    patent = Patent(pdf=PATENT_PDF_PATH, client=client)
    patent.start(quote=True)
    if patent.status == "FailedQuotation":
        pytest.skip(
            f"Patent quote returned FailedQuotation on {client.env}; platform tool may be unavailable."
        )
    patent.confirm()

    for _ in range(30):
        patent.sync()
        if patent.status in {"Queued", "Running", "Created"}:
            break
        if patent.status == "Cancelled":
            break
        time.sleep(2.0)

    if patent.status not in {"Queued", "Running", "Created"}:
        pytest.skip(
            f"Patent job reached {patent.status!r} before cancel window; "
            "cannot test cancel."
        )

    patent.cancel()
    assert patent.status == "Cancelled"
