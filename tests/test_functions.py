"""this module contains tests for functions. These are meant to be run against a live instance"""

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    DATA_DIR,
    Complex,
    Ligand,
    LigandSet,
    Protein,
)
from tests.utils import client  # noqa: F401


def test_molprops(client):  # noqa: F811
    ligand = Ligand.from_identifier("serotonin")

    props = ligand.admet_properties(use_cache=False)

    assert isinstance(props, dict), "Expected a dictionary"
    assert "logP" in props, "Expected logP to be in the properties"
    assert "logD" in props, "Expected logD to be in the properties"
    assert "logS" in props, "Expected logS to be in the properties"


def test_pocket_finder(client):  # noqa: F811
    protein = Protein.from_pdb_id("1EBY")
    pockets = protein.find_pockets(
        pocket_count=1,
        use_cache=False,
    )

    assert len(pockets) == 1, "Incorrect number of pockets"


def test_docking(client):  # noqa: F811
    protein = Protein.from_pdb_id("1EBY")
    pockets = protein.find_pockets(pocket_count=1)
    pocket = pockets[0]

    ligand = Ligand.from_smiles("CN(C)C(=O)c1cccc(-c2cn(C)c(=O)c3[nH]ccc23)c1")

    poses = protein.dock(
        ligand=ligand,
        pocket=pocket,
        use_cache=False,
    )

    assert isinstance(poses, LigandSet), "Expected protien.dock() to return a LigandSet"


def test_sysprep(client):  # noqa: F811
    from deeporigin.functions.sysprep import run_sysprep

    sim = Complex.from_dir(BRD_DATA_DIR)

    # this is chosen to be one where it takes >1 min
    run_sysprep(
        protein=sim.protein,
        ligand=sim.ligands[3],
        is_lig_protonated=True,
        use_cache=False,
    )


def test_loop_modelling(client):  # noqa: F811
    protein = Protein.from_pdb_id("5QSP")
    assert len(protein.find_missing_residues()) > 0, "Missing residues should be > 0"
    protein.model_loops(use_cache=False)

    assert protein.structure is not None, "Structure should not be None"

    assert len(protein.find_missing_residues()) == 0, "Missing residues should be 0"


def test_konnektor(client):  # noqa: F811
    ligands = LigandSet.from_sdf(DATA_DIR / "ligands" / "ligands-brd-all.sdf")

    ligands.map_network(use_cache=False)

    assert len(ligands.network.keys()) > 0, "Expected network to be non-empty"

    assert len(ligands.network["edges"]) == 7, "Expected 7 edges"
