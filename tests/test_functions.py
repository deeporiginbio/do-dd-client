"""this module contains tests for functions. These are meant to be run against a live instance"""

from pathlib import Path

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Complex,
    Ligand,
    LigandSet,
    Protein,
)

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
    protein = Protein.from_file(FIXTURES_DIR / "1eby.pdb")
    pockets = protein.find_pockets(
        pocket_count=1,
        use_cache=False,
    )

    assert len(pockets) == 1, "Incorrect number of pockets"


def test_docking_lv2():
    """Test docking function."""
    protein = Protein.from_file(FIXTURES_DIR / "1eby.pdb")
    pockets = protein.find_pockets(
        pocket_count=1,
        use_cache=False,
    )
    pocket = pockets[0]

    ligand = Ligand.from_smiles("CN(C)C(=O)c1cccc(-c2cn(C)c(=O)c3[nH]ccc23)c1")

    poses = protein.dock(
        ligand=ligand,
        pocket=pocket,
        use_cache=False,
    )

    assert isinstance(poses, LigandSet), "Expected protein.dock() to return a LigandSet"


def test_sysprep_lv2():
    """Test system preparation function."""
    from deeporigin.functions.sysprep import run_sysprep
    from deeporigin.platform.client import DeepOriginClient

    sim = Complex.from_dir(BRD_DATA_DIR)
    client = DeepOriginClient()

    # this is chosen to be one where it takes >1 min
    response = run_sysprep(
        protein=sim.protein,
        ligand=sim.ligands[3],
        add_H_atoms=True,
        use_cache=False,
        client=client,
    )

    # Verify response structure
    assert isinstance(response, dict), "Expected a dictionary response"
    assert "status" in response, "Expected 'status' in response"
    assert response["status"] == "success", "Expected status to be 'success'"
    assert "protein_path" in response, "Expected 'protein_path' in response"
    assert "ligand_path" in response, "Expected 'ligand_path' in response"
    assert "output_files" in response, "Expected 'output_files' in response"


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
