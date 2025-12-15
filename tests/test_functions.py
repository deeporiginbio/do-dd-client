"""this module contains tests for functions. These are meant to be run against a live instance"""

from pathlib import Path

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Complex,
    Ligand,
    LigandSet,
    Protein,
)
from tests.utils import client  # noqa: F401

# Fixtures directory for test files
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_molprops(client):  # noqa: F811
    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )

    props = ligand.admet_properties(use_cache=False, client=client)

    assert isinstance(props, dict), "Expected a dictionary"
    assert "logP" in props, "Expected logP to be in the properties"
    assert "logD" in props, "Expected logD to be in the properties"
    assert "logS" in props, "Expected logS to be in the properties"


def test_pocket_finder(client):  # noqa: F811
    """Test pocket finder function."""
    protein = Protein.from_file(FIXTURES_DIR / "1eby.pdb")
    pockets = protein.find_pockets(
        pocket_count=1,
        use_cache=False,
        client=client,
    )

    assert len(pockets) == 1, "Incorrect number of pockets"


def test_docking(client):  # noqa: F811
    """Test docking function."""
    protein = Protein.from_file(FIXTURES_DIR / "1eby.pdb")
    pockets = protein.find_pockets(
        pocket_count=1,
        client=client,
        use_cache=False,
    )
    pocket = pockets[0]

    ligand = Ligand.from_smiles("CN(C)C(=O)c1cccc(-c2cn(C)c(=O)c3[nH]ccc23)c1")

    poses = protein.dock(
        ligand=ligand,
        pocket=pocket,
        use_cache=False,
        client=client,
    )

    assert isinstance(poses, LigandSet), "Expected protein.dock() to return a LigandSet"


def test_sysprep(client):  # noqa: F811
    """Test system preparation function."""
    from deeporigin.functions.sysprep import run_sysprep

    sim = Complex.from_dir(BRD_DATA_DIR, client=client)

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


def test_protonation(client):  # noqa: F811
    """Test protonation function."""
    from deeporigin.functions.protonation import protonate

    response = protonate(
        smiles_list=["CCO"],
        ph=7.4,
        filter_percentage=1.0,
        use_cache=False,
        client=client,
    )

    # Verify response structure
    assert isinstance(response, dict), "Expected a dictionary response"
    assert "pH" in response, "Expected 'pH' in response"
    assert response["pH"] == 7.4, "Expected pH to be 7.4"
    assert "protonation_states" in response, "Expected 'protonation_states' in response"
    assert "smiles_list" in response["protonation_states"], (
        "Expected 'smiles_list' in protonation_states"
    )
    assert len(response["protonation_states"]["smiles_list"]) > 0, (
        "Expected at least one SMILES in smiles_list"
    )


# def test_loop_modelling(client):  # noqa: F811
#     protein = Protein.from_pdb_id("5QSP")
#     assert len(protein.find_missing_residues()) > 0, "Missing residues should be > 0"
#     protein.model_loops(use_cache=False, client=client)

#     assert protein.structure is not None, "Structure should not be None"

#     assert len(protein.find_missing_residues()) == 0, "Missing residues should be 0"


# def test_konnektor(client):  # noqa: F811
#     ligands = LigandSet.from_sdf(DATA_DIR / "ligands" / "ligands-brd-all.sdf")

#     ligands.map_network(use_cache=False, client=client)

#     assert len(ligands.network.keys()) > 0, "Expected network to be non-empty"

#     assert len(ligands.network["edges"]) == 7, "Expected 7 edges"
