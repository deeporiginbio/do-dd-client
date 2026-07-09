"""tests functions in the chemistry module"""

from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from deeporigin.drug_discovery import chemistry
from deeporigin.drug_discovery.structures.ligand import LigandSet

# Import shared test fixtures
from tests.utils_ligands import ligands


@pytest.mark.parametrize("ligand", ligands)
def test_count_molecules_in_sdf_file_lv0(
    tmp_path,
    ligand,
):
    assert chemistry.count_molecules_in_sdf_file(ligand["file"]) == ligand["n_ligands"]


@pytest.mark.parametrize("ligand", ligands)
def test_split_sdf_file_lv0(
    tmp_path,
    ligand,
):
    """
    Test that split_sdf_using_names correctly splits the ligands SDF file
    into separate SDF files, and that the output is cleaned up (by pytest)
    after the test completes.
    """

    # Create an output directory within the pytest temp directory
    output_dir = tmp_path / "split_ligands"
    output_dir.mkdir(exist_ok=True)

    # Call the function to be tested
    sdf_file_names = chemistry.split_sdf_file(
        input_sdf_path=str(ligand["file"]),
        output_prefix="testLig",
        output_dir=str(output_dir),
        name_by_property=ligand["name_by_property"],
    )

    # Check that at least one output file was created
    sdf_files = list(output_dir.glob("*.sdf"))
    assert len(sdf_files) > 0, "No SDF files were created by the splitting function."

    assert len(sdf_file_names) == ligand["n_ligands"], (
        "The number of SDF files is incorrect."
    )

    for sdf_file in sdf_files:
        n_mol = chemistry.count_molecules_in_sdf_file(sdf_file)
        assert n_mol == 1, "The SDF file contains more than one molecule."


@pytest.mark.parametrize("ligand_set", ligands)
def test_pairwise_pose_rmsd_lv0(ligand_set):
    if ligand_set["n_ligands"] > 10:
        pytest.skip("Skipping test for large number of ligands")

    ligands = LigandSet.from_sdf(ligand_set["file"])
    mols = ligands.to_rdkit_mols()
    chemistry.pairwise_pose_rmsd(mols)


def test_canonicalize_smiles_valid() -> None:
    """canonicalize_smiles returns a canonical SMILES string."""
    assert chemistry.canonicalize_smiles("C(C)O") == chemistry.canonicalize_smiles(
        "CCO"
    )


def test_canonicalize_smiles_invalid() -> None:
    """canonicalize_smiles raises for invalid SMILES."""
    with pytest.raises(ValueError, match="Invalid SMILES"):
        chemistry.canonicalize_smiles("not-a-smiles")


def test_sdf_to_smiles_round_trip(tmp_path: Path) -> None:
    """smiles_to_sdf and sdf_to_smiles round-trip a molecule."""
    sdf_path = tmp_path / "ethanol.sdf"
    chemistry.smiles_to_sdf("CCO", str(sdf_path))

    smiles = chemistry.sdf_to_smiles(sdf_path)

    assert chemistry.canonicalize_smiles(smiles[0]) == chemistry.canonicalize_smiles(
        "CCO"
    )


def test_read_property_values() -> None:
    """read_property_values returns per-molecule property values."""
    brd = next(item for item in ligands if item["name_by_property"] == "_Name")
    values = chemistry.read_property_values(brd["file"], "_Name")

    assert len(values) == brd["n_ligands"]
    assert all(value is not None for value in values)


def test_group_by_prop_smiles_to_multiconf(tmp_path: Path) -> None:
    """group_by_prop_smiles_to_multiconf groups poses by SMILES property."""
    mol = Chem.MolFromSmiles("CCO")
    mol = Chem.AddHs(mol)
    AllChem.EmbedMolecule(mol, AllChem.ETKDG())
    mol.SetProp("SMILES", "CCO")

    pose_two = Chem.Mol(mol)
    params = AllChem.ETKDG()
    params.randomSeed = 11
    AllChem.EmbedMolecule(pose_two, params)
    pose_two.SetProp("SMILES", "CCO")

    sdf_path = tmp_path / "poses.sdf"
    writer = Chem.SDWriter(str(sdf_path))
    writer.write(mol)
    writer.write(pose_two)
    writer.close()

    grouped = chemistry.group_by_prop_smiles_to_multiconf(str(sdf_path))

    assert "CCO" in grouped
    assert grouped["CCO"].GetNumConformers() == 2


def test_raw_rmsd_from_map_identical_mols() -> None:
    """raw_rmsd_from_map returns zero for identical coordinates."""
    mol_a = Chem.MolFromSmiles("CCO")
    mol_b = Chem.MolFromSmiles("CCO")
    mol_a = Chem.AddHs(mol_a)
    mol_b = Chem.AddHs(mol_b)
    params_a = AllChem.ETKDG()
    params_a.randomSeed = 1
    params_b = AllChem.ETKDG()
    params_b.randomSeed = 1
    AllChem.EmbedMolecule(mol_a, params_a)
    AllChem.EmbedMolecule(mol_b, params_b)
    atom_map = list(
        zip(range(mol_a.GetNumAtoms()), range(mol_b.GetNumAtoms()), strict=False)
    )

    rmsd = chemistry.raw_rmsd_from_map(mol_a, mol_b, atom_map)

    assert rmsd == pytest.approx(0.0)
