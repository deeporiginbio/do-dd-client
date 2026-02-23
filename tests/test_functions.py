"""this module contains tests for functions. These are meant to be run against a live instance"""

from pathlib import Path

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Complex,
    Ligand,
    LigandSet,
    Pocket,
    Protein,
)
from deeporigin.functions.result import FunctionResult

# Fixtures directory for test files
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_molprops_lv2():
    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )

    props = ligand.admet_properties(use_cache=False)

    assert isinstance(props, dict), "Expected a dictionary"
    assert "logP" in props, "Expected logP to be in the properties"
    assert "logD" in props, "Expected logD to be in the properties"
    assert "logS" in props, "Expected logS to be in the properties"


def test_pocket_finder_lv2():
    """Test pocket finder function returns FunctionResult with pockets."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    result = protein.find_pockets(
        pocket_count=1,
        use_cache=False,
    )

    assert isinstance(result, FunctionResult), (
        "Expected protein.find_pockets() to return a FunctionResult"
    )
    assert isinstance(result.pockets, list), "Expected result.pockets to be a list"
    assert len(result.pockets) == 1, "Incorrect number of pockets"
    assert isinstance(result.pockets[0], Pocket), (
        "Expected pockets to contain Pocket objects"
    )


def test_docking_lv2():
    """Test docking function."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()

    pocket = Pocket.from_pdb_file(
        FIXTURES_DIR
        / "files"
        / "tool-runs"
        / "86ea3aea-accd-474d-9e0b-89a3f47ab61b"
        / "pocket_1.pdb",
    )

    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )

    result = protein.dock(
        ligand=ligand,
        pocket=pocket,
        use_cache=False,
    )

    assert isinstance(result, FunctionResult), (
        "Expected protein.dock() to return a FunctionResult"
    )
    assert isinstance(result.poses, LigandSet), (
        "Expected result.poses to be a LigandSet"
    )


def test_sysprep_lv2():
    """Test system preparation returns FunctionResult with prepared_systems."""

    sim = Complex.from_dir(BRD_DATA_DIR)

    ligand = [ligand for ligand in sim.ligands if ligand.name == "cmpd 4 (Crotyl)"][0]

    result = sim.prepare(ligand=ligand)

    assert isinstance(result, FunctionResult), (
        "Expected sim.prepare() to return a FunctionResult"
    )
    assert isinstance(result.prepared_systems, list), (
        "Expected result.prepared_systems to be a list"
    )
    assert len(result.prepared_systems) == 1
    assert isinstance(result.prepared_systems[0], Protein), (
        "Expected prepared_systems[0] to be a Protein"
    )


def test_protonation_lv2():
    """Test protonation function returns FunctionResult with ligands."""

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
