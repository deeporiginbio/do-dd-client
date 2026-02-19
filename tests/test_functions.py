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
from deeporigin.utils.cost import Estimate
from deeporigin.utils.result import Result

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
    """Test pocket finder function."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    pockets = protein.find_pockets(
        pocket_count=1,
        use_cache=False,
    )

    assert len(pockets) == 1, "Incorrect number of pockets"


def test_docking_lv2():
    """Test docking function."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    pocket = Pocket.from_pdb_file(
        FIXTURES_DIR / "pockets" / "brd_pocket_1.pdb", name="brd_pocket_1"
    )

    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )

    result = protein.dock(
        ligand=ligand,
        pocket=pocket,
        quote=False,
        use_cache=False,
    )

    assert isinstance(result, Result), "Expected protein.dock() to return a Result"
    assert result.data is not None, (
        "Expected result.data to be populated when quote=False"
    )
    assert isinstance(result.data, LigandSet), "Expected result.data to be a LigandSet"
    assert result.cost is not None, (
        "Expected result.cost to be populated when quote=False"
    )
    assert isinstance(result.cost, Estimate), (
        "Expected result.cost to be an Estimate object"
    )
    assert result.estimate is None, (
        "Expected result.estimate to be None when quote=False"
    )


def test_docking_quote_lv1():
    """Test docking function with quote=True."""

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    pocket = Pocket.from_pdb_file(
        FIXTURES_DIR / "pockets" / "brd_pocket_1.pdb", name="brd_pocket_1"
    )

    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )

    result = protein.dock(
        ligand=ligand,
        pocket=pocket,
        quote=True,
        use_cache=False,
    )

    assert isinstance(result, Result), "Expected protein.dock() to return a Result"
    assert result.data is None, "Expected result.data to be None when quote=True"
    assert result.estimate is not None, (
        "Expected result.estimate to be populated when quote=True"
    )
    assert isinstance(result.estimate, Estimate), (
        "Expected result.estimate to be an Estimate object"
    )
    assert result.cost is None, "Expected result.cost to be None when quote=True"


def test_docking_multiple_ligands_quote_lv1():
    """Test docking function with multiple ligands and quote=True.

    it's lv1 because quote=True"""

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    pocket = Pocket.from_pdb_file(
        FIXTURES_DIR / "pockets" / "brd_pocket_1.pdb", name="brd_pocket_1"
    )

    # Load 3 ligands from BRD_DATA_DIR fixtures
    ligands = [
        Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf"),
        Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf"),
        Ligand.from_sdf(BRD_DATA_DIR / "brd-4.sdf"),
    ]

    result = protein.dock(
        ligands=ligands,
        pocket=pocket,
        quote=True,
        use_cache=False,
    )

    assert isinstance(result, Result), "Expected protein.dock() to return a Result"
    assert result.data is None, "Expected result.data to be None when quote=True"
    assert result.estimate is not None, (
        "Expected result.estimate to be populated when quote=True"
    )
    assert isinstance(result.estimate, Estimate), (
        "Expected result.estimate to be an Estimate object"
    )
    assert result.cost is None, "Expected result.cost to be None when quote=True"
    # Verify estimate includes all ligands (should have items from all 3)
    assert len(result.estimate.items) >= 3, (
        f"Expected estimate to include items for all 3 ligands, got {len(result.estimate.items)} items"
    )
    assert result.estimate.total_price > 0, (
        "Expected estimate.total_price to be greater than 0"
    )


def test_docking_multiple_ligands_lv2():
    """Test docking function with multiple ligands and quote=False.

    it's lv2 because quote=False"""

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    pocket = Pocket.from_pdb_file(
        FIXTURES_DIR / "pockets" / "brd_pocket_1.pdb", name="brd_pocket_1"
    )

    # Load 2 ligands from BRD_DATA_DIR fixtures
    ligands = [
        Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf"),
        Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf"),
    ]

    result = protein.dock(
        ligands=ligands,
        pocket=pocket,
        quote=False,
        use_cache=False,
    )

    assert isinstance(result, Result), "Expected protein.dock() to return a Result"
    assert result.data is not None, (
        "Expected result.data to be populated when quote=False"
    )
    assert isinstance(result.data, LigandSet), "Expected result.data to be a LigandSet"
    assert len(result.data) > 0, (
        "Expected result.data to contain poses from all ligands"
    )
    assert result.cost is not None, (
        "Expected result.cost to be populated when quote=False"
    )
    assert isinstance(result.cost, Estimate), (
        "Expected result.cost to be an Estimate object"
    )
    assert result.cost.total_price > 0, (
        "Expected result.cost.total_price to be greater than 0"
    )
    assert result.estimate is None, (
        "Expected result.estimate to be None when quote=False"
    )


def test_sysprep_lv2():
    """Test system preparation function."""

    sim = Complex.from_dir(BRD_DATA_DIR)

    ligand = [ligand for ligand in sim.ligands if ligand.name == "cmpd 4 (Crotyl)"][0]

    # this is chosen to be one where it takes >1 min
    _ = sim.prepare(ligand=ligand)


def test_protonation_lv2():
    """Test protonation function."""

    ligand = Ligand.from_smiles("C=CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O")

    original_smiles = ligand.smiles
    ligand.protonate(ph=7.4, use_cache=False)

    assert ligand.smiles == original_smiles, "Expected SMILES to be the same at pH 7.4"

    ligand.protonate(ph=11.4, use_cache=False)

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
