"""This module contains tests for functions.

These are meant to be run against a live instance.
"""

import pytest

from conftest import check_function_exists
from deeporigin.drug_discovery import (
    Ligand,
    Molprops,
    Pocket,
    PocketFinder,
    Protein,
)
from deeporigin.functions.docking import dock
from deeporigin.functions.result import FunctionResult
from deeporigin.functions.sysprep import for_abfe
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import (
    DOCKING_FUNCTION_KEY,
    DOCKING_FUNCTION_VERSION,
    MOL_PROPS_FUNCTION_KEY_PREFIX,
    POCKET_FINDER_FUNCTION_KEY,
    POCKET_FINDER_FUNCTION_VERSION,
    PROTONATION_FUNCTION_KEY,
    SYSPREP_FUNCTION_KEY,
    SYSPREP_FUNCTION_VERSION,
)
from deeporigin.utils.constants import MOLPROPS_PROPERTY_KEYS


def test_molprops_lv2(client: DeepOriginClient):
    missing_molprops = [
        f"{MOL_PROPS_FUNCTION_KEY_PREFIX}-{p}"
        for p in sorted(MOLPROPS_PROPERTY_KEYS)
        if not check_function_exists(client, f"{MOL_PROPS_FUNCTION_KEY_PREFIX}-{p}")
    ]
    if missing_molprops:
        pytest.skip(f"Mol props functions not available: {missing_molprops}")

    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )

    mp = Molprops(ligands=[ligand], use_cache=False, client=client)
    mp.run()

    assert ligand.get_property("logP") is not None or ligand.log_p is not None
    assert ligand.get_property("logD") is not None or ligand.log_d is not None
    assert ligand.get_property("logS") is not None or ligand.log_s is not None


def test_pocket_finder_quote_lv1(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """PocketFinder.quote() returns an estimate without running the tool."""
    if not check_function_exists(
        client, POCKET_FINDER_FUNCTION_KEY, POCKET_FINDER_FUNCTION_VERSION
    ):
        pytest.skip("Pocket finder function does not exist")

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
    if not check_function_exists(
        client, POCKET_FINDER_FUNCTION_KEY, POCKET_FINDER_FUNCTION_VERSION
    ):
        pytest.skip("Pocket finder function does not exist")

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


def test_docking_lv2(
    client: DeepOriginClient,
    brd_protein: Protein,
    brd_ligand: Ligand,
    registered_pocket: Pocket,
):
    """Test docking function."""
    if not check_function_exists(
        client, DOCKING_FUNCTION_KEY, DOCKING_FUNCTION_VERSION
    ):
        pytest.skip("Docking function does not exist")

    result = dock(
        client=client,
        protein=brd_protein,
        ligand=brd_ligand,
        pocket=registered_pocket,
    )

    assert isinstance(result, FunctionResult), (
        "Expected protein.dock() to return a FunctionResult"
    )


@pytest.mark.parametrize(
    ("protein_fixture", "ligand_fixture"),
    [
        pytest.param("brd_protein", "brd_ligand", id="backend_only"),
        pytest.param("registered_protein", "registered_ligand", id="data_platform"),
    ],
)
def test_sysprep_lv2(
    client: DeepOriginClient,
    protein_fixture: str,
    ligand_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    """Exercise ABFE system prep with upload-only vs data-platform entities.

    ``brd_*`` checks the tool end-to-end with file paths only. ``registered_*``
    additionally checks the result-explorer row for this job (tool key, protein
    id, stored ``data`` payload).
    """
    if not check_function_exists(
        client, SYSPREP_FUNCTION_KEY, SYSPREP_FUNCTION_VERSION
    ):
        pytest.skip("System prep function does not exist")

    protein: Protein = request.getfixturevalue(protein_fixture)
    ligand: Ligand = request.getfixturevalue(ligand_fixture)

    result = for_abfe(
        client=client,
        protein=protein,
        ligand=ligand,
        add_H_atoms=True,
        protonate_protein=True,
    )

    assert isinstance(result, FunctionResult), (
        "Expected for_abfe() to return a FunctionResult"
    )

    if protein_fixture == "registered_protein":
        execution_id = result._responses[0]["id"]

        function_outputs = result._responses[0]["functionOutputs"]
        assert "system" in function_outputs.keys(), (
            f"Expected system in function data, got {function_outputs.keys()}"
        )

        response = client.results.get_prepared_systems(
            compute_job_id=execution_id,
            protein_id=protein.id,
        )
        records = response["data"]
        assert len(records) >= 1, "Expected a prepared-system row for this compute job"
        record = records[0]
        assert record.get("compute_job_id") == execution_id
        assert record.get("tool_key") == SYSPREP_FUNCTION_KEY
        data = record["data"]
        assert isinstance(data, dict) and len(data) > 0
        assert data.get("protein_id") == protein.id


def test_protonation_lv2(client: DeepOriginClient):
    """Test protonation function returns FunctionResult with ligands."""
    if not check_function_exists(client, PROTONATION_FUNCTION_KEY):
        pytest.skip("Protonation function does not exist")

    ligand = Ligand.from_smiles("C=CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O")

    original_smiles = ligand.smiles
    result = ligand.protonate(ph=7.4, use_cache=False)

    assert isinstance(result, FunctionResult), (
        "Expected ligand.protonate() to return a FunctionResult"
    )
    assert isinstance(result.ligands, list), "Expected result.ligands to be a list"
    assert len(result.ligands) == 1, "Expected result.ligands to contain one ligand"
    assert result.ligands[0] is ligand, (
        "Expected result.ligands[0] to be the same ligand"
    )
    assert ligand.smiles == original_smiles, "Expected SMILES to be the same at pH 7.4"

    result = ligand.protonate(ph=11.4, use_cache=False)

    assert isinstance(result, FunctionResult)
    assert ligand.smiles != original_smiles, (
        "Expected SMILES to be different at pH 11.4"
    )


# def test_loop_modelling(client):
#     protein = Protein.from_pdb_id("5QSP")
#     assert len(protein.find_missing_residues()) > 0, "Missing residues should be > 0"
#     protein.model_loops(use_cache=False, client=client)

#     assert protein.structure is not None, "Structure should not be None"

#     assert len(protein.find_missing_residues()) == 0, "Missing residues should be 0"


# def test_konnektor(client):
#     ligands = LigandSet.from_sdf(DATA_DIR / "ligands" / "ligands-brd-all.sdf")

#     ligands.map_network(use_cache=False, client=client)

#     assert len(ligands.network.keys()) > 0, "Expected network to be non-empty"

#     assert len(ligands.network["edges"]) == 7, "Expected 7 edges"
