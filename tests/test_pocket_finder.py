"""End-to-end and unit tests for PocketFinder (sync and async paths)."""

import json
from pathlib import Path
import time

import pytest

from deeporigin.drug_discovery import Pocket, PocketFinder, Protein
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import (
    TERMINAL_STATES,
    TOOL_KEYS_AND_VERSIONS,
    is_success_status,
)
from tests.conftest import check_tool_exists


def test_pocket_finder_run_quote_true_lv1(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """PocketFinder.run(quote=True) returns None and populates estimate."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
    ), "Pocket finder tool not registered on platform (expected key/version)."

    pf = PocketFinder(protein=registered_protein, client=client)
    result = pf.run(quote=True)
    if pf.status == "FailedQuotation":
        pytest.skip(
            "PocketFinder quote returned FailedQuotation; platform tool may be unavailable."
        )
    assert result is None, "run(quote=True) should return None"
    assert pf.estimate is not None, "Estimate should be set"
    assert pf.status == "Quoted"
    assert pf.cost is None, (
        "Cost should be None because the pocket finder is not run yet"
    )


def test_pocket_finder_from_dto_maps_async_execution_fields_from_fixture(
    client,
) -> None:
    """from_dto maps common async execution fields from fixture DTO."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/pocket-finder-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    pf = PocketFinder.from_dto(dto, client=client)

    assert pf.completed_at == dto["completedAt"]
    assert pf.id == dto["executionId"]
    assert pf.created_by == dto["createdBy"]
    assert pf.created_at == dto["createdAt"]
    assert pf.started_at == dto["startedAt"]
    assert pf.session == dto["session"]
    assert pf.status == dto["status"]
    assert pf.app == dto["app"]
    assert pf.approve_amount == dto["approveAmount"]
    assert pf.pocket_count == dto["userInputs"]["pocket_count"]
    assert pf.pocket_min_size == dto["userInputs"]["pocket_min_size"]


def test_pocket_finder_from_dto_initializes_notebook_watch_state(client) -> None:
    """from_dto skips __init__; notebook watch attrs must exist for stop_watching."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/pocket-finder-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())

    pf = PocketFinder.from_dto(dto, client=client)
    assert pf._watch_task is None
    assert pf._display_id is None
    assert pf._last_html is None
    pf.stop_watching()


def test_pocket_finder_from_dto_raises_on_tool_key_mismatch(client) -> None:
    """from_dto fails fast when DTO tool key does not match PocketFinder.tool_key."""
    fixture_path = (
        Path(__file__).parent / "fixtures/executions/pocket-finder-test-execution.json"
    )
    dto = json.loads(fixture_path.read_text())
    dto["tool"]["key"] = "deeporigin.foo-fake-tool"

    with pytest.raises(ValueError, match="tool key mismatch"):
        PocketFinder.from_dto(dto, client=client)


def test_pocket_finder_start_submits_async_payload(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """``start`` submits an async (``sync=False``) payload and stores id/status."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
    ), "Pocket finder tool not registered on platform (expected key/version)."

    pf = PocketFinder(protein=registered_protein, client=client)
    pf.start()

    assert pf.id is not None
    # ``start()`` omits ``approveAmount`` and sends ``sync=False``; the platform
    # replies with ``status="Quoted"`` until ``start()`` is called again to confirm.
    assert pf.status == "Quoted"

    dto = pf._dto or {}
    assert (
        dto.get("tool", {}).get("key")
        == TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"]
    )
    user_inputs = dto.get("userInputs") or {}
    assert user_inputs.get("pocket_count") == pf.pocket_count
    assert user_inputs.get("pocket_min_size") == pf.pocket_min_size
    protein_input = user_inputs.get("protein") or {}
    assert protein_input.get("id") == registered_protein.id
    assert protein_input.get("file_path") == registered_protein.remote_path


def test_pocket_finder_start_rejects_non_initial_status(
    registered_protein: Protein,
) -> None:
    """``start`` must refuse to resubmit when an execution is already running."""
    pf = PocketFinder(protein=registered_protein)
    pf._id = "exec-pf-existing"
    pf.status = "Running"

    with pytest.raises(ValueError, match="already in 'Running' state"):
        pf.start()


def test_pocket_finder_start_sync_get_results_lv3(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """Start pocket finder asynchronously via start(); sync until done; get results."""
    if client.env == "local":
        pytest.skip(
            "start/sync/get_results pocket-finder flow not run against local mock"
        )

    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
    ), "Pocket finder tool not registered on platform (expected key/version)."

    pf = PocketFinder(protein=registered_protein, client=client)
    pf.start()

    pf.sync()
    if pf.status == "Quoted":
        pf.start()
    elif pf.status in TERMINAL_STATES and not is_success_status(pf.status):
        pytest.fail(f"PocketFinder reached terminal state {pf.status!r} before running")

    timeout_seconds = 600
    poll_interval = 10
    elapsed = 0
    while elapsed < timeout_seconds:
        pf.sync()
        if pf.status in TERMINAL_STATES:
            break
        time.sleep(poll_interval)
        elapsed += poll_interval
    else:
        pytest.fail(
            f"PocketFinder did not reach a terminal state within {timeout_seconds}s; "
            f"last status={pf.status!r}"
        )

    assert is_success_status(pf.status), f"Expected status Completed, got {pf.status!r}"

    pockets = pf.get_results()
    assert pockets is not None, "get_results() should return pockets after Completed"
    assert len(pockets) >= 1, "Expected at least one pocket"
    for pocket in pockets:
        assert isinstance(pocket, Pocket), "Each result should be a Pocket"


@pytest.mark.parametrize(
    "protein_fixture",
    [
        pytest.param("brd_protein", id="backend_only"),
        pytest.param("registered_protein", id="data_platform"),
    ],
)
def test_pocket_finder_lv2(
    client: DeepOriginClient,
    protein_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    """Exercise pocket finder with upload-only vs data-platform–registered protein.

    ``brd_protein`` checks the tool end-to-end using file path only (no platform
    entity in the fixture). ``registered_protein`` additionally asserts
    platform-linked IDs and ``Pocket.from_result`` hydration.
    """
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
    ), "Pocket finder tool not registered on platform (expected key/version)."

    protein: Protein = request.getfixturevalue(protein_fixture)
    num_pockets = 1

    pf = PocketFinder(
        protein,
        pocket_count=num_pockets,
        client=client,
    )
    pockets = pf.run()

    assert len(pockets) == num_pockets, f"Expected {num_pockets} pockets"
    pocket = pockets[0]
    assert isinstance(pocket, Pocket), "Expected Pocket object"

    assert pocket.protein is protein, (
        "PocketFinder results should attach the finder protein"
    )
    if protein.id is not None:
        assert pocket.protein_id == protein.id, (
            "Pocket protein_id should match protein.id"
        )

    if protein_fixture == "registered_protein":
        assert pocket.protein_id == protein.id, (
            "Pocket protein_id should match protein.id"
        )
        pockets_from_result = Pocket.from_result(
            execution_id=pf.id,
            client=client,
        )
        assert len(pockets_from_result) == num_pockets, (
            f"Expected {num_pockets} pockets from result"
        )
        pocket_from_result = pockets_from_result[0]
        assert isinstance(pocket_from_result, Pocket), "Expected Pocket object"
        assert pocket_from_result.protein_id == protein.id, (
            "Pocket protein_id should match protein.id"
        )
