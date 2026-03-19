"""This module contains tests for functions.

These are meant to be run against a live instance.
"""

import pytest

from conftest import check_function_exists
from deeporigin.drug_discovery import (
    Ligand,
    Pocket,
    Protein,
)
from deeporigin.functions.docking import dock
from deeporigin.functions.pocket_finder import find_pockets
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


def test_molprops_lv2(client: DeepOriginClient):
    if not check_function_exists(client, f"{MOL_PROPS_FUNCTION_KEY_PREFIX}-logp"):
        pytest.skip("Mol props function does not exist")

    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )

    props = ligand.admet_properties(use_cache=False)

    assert isinstance(props, dict), "Expected a dictionary"
    assert "logP" in props, "Expected logP to be in the properties"
    assert "logD" in props, "Expected logD to be in the properties"
    assert "logS" in props, "Expected logS to be in the properties"


def test_pocket_finder_lv2(client: DeepOriginClient, brd_protein: Protein):
    """Test pocket finder function returns FunctionResult with pockets."""
    if not check_function_exists(
        client, POCKET_FINDER_FUNCTION_KEY, POCKET_FINDER_FUNCTION_VERSION
    ):
        pytest.skip("Pocket finder function does not exist")

    result = find_pockets(
        protein=brd_protein,
        pocket_count=1,
        client=client,
    )

    assert isinstance(result, FunctionResult), (
        "Expected find_pockets() to return a FunctionResult"
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


def test_sysprep_lv2(
    client: DeepOriginClient,
    brd_protein: Protein,
    brd_ligand: Ligand,
):
    """Test system preparation returns FunctionResult with prepared_systems."""
    if not check_function_exists(
        client, SYSPREP_FUNCTION_KEY, SYSPREP_FUNCTION_VERSION
    ):
        pytest.skip("System prep function does not exist")

    result = for_abfe(
        client=client,
        protein=brd_protein,
        ligand=brd_ligand,
        add_H_atoms=True,
        protonate_protein=True,
    )

    assert isinstance(result, FunctionResult), (
        "Expected sim.prepare() to return a FunctionResult"
    )


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
