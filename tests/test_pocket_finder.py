"""End-to-end tests for PocketFinder (live instance)."""

import pytest

from conftest import check_tool_exists
from deeporigin.drug_discovery import Pocket, PocketFinder, Protein
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import TOOL_KEYS_AND_VERSIONS


def test_pocket_finder_quote_lv1(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """PocketFinder.quote() returns an estimate without running the tool."""
    assert check_tool_exists(
        client,
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_key"],
        TOOL_KEYS_AND_VERSIONS["pocket_finder"]["tool_version"],
    ), "Pocket finder tool not registered on platform (expected key/version)."

    pf = PocketFinder(protein=registered_protein, client=client)
    pf.quote()
    assert pf.estimate is not None, "Estimate should be set"
    assert pf.cost is None, (
        "Cost should be None because the pocket finder is not run yet"
    )


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
