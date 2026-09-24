import os
from pathlib import Path
import tempfile
import uuid

import numpy as np
import pytest

from deeporigin.drug_discovery import BRD_DATA_DIR, Protein
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient


def test_load_protein_from_cif_structure_factor():
    """Test that loading a structure factor CIF file (without atom_site) raises a helpful error."""
    cif_path = Path(__file__).parent / "fixtures" / "1NSG-sf.cif"

    # Structure factor files don't have atomic coordinates, so this should raise ValueError
    with pytest.raises(ValueError, match="does not contain atomic coordinates"):
        _ = Protein.from_file(cif_path)


def test_to_pdb_requires_rehydration_when_remote_path_only():
    """to_pdb/to_file must not perform I/O; fail if remote_path set but no local file."""
    protein = Protein(
        name="test",
        structure=None,
        remote_path="entities/proteins/fake.pdb",
    )

    with pytest.raises(DeepOriginException, match="not rehydrated"):
        protein.to_pdb()

    with pytest.raises(DeepOriginException, match="not rehydrated"):
        protein.to_file()


def test_dump_state_writes_cif_when_resnames_exceed_pdb_limit(tmp_path: Path) -> None:
    """_dump_state falls back to mmCIF when residue names exceed PDB limits."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    assert protein.structure is not None
    protein.structure.res_name = np.array(
        [
            "ABCD" if i == 0 else name
            for i, name in enumerate(protein.structure.res_name)
        ]
    )

    dumped = Path(protein._dump_state())
    assert dumped.suffix == ".cif"
    assert dumped.is_file()
    assert "data_" in dumped.read_text(encoding="utf-8")


def test_to_cif_writes_mmcif(tmp_path: Path) -> None:
    """to_cif serializes the current structure as mmCIF."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    out = tmp_path / "protein.cif"
    written = protein.to_cif(out)
    assert written == str(out)
    assert out.is_file()
    assert "atom_site" in out.read_text(encoding="utf-8")


def test_dump_state_writes_pdb_when_compatible() -> None:
    """_dump_state keeps PDB when the structure fits classic PDB limits."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    dumped = Path(protein._dump_state())
    assert dumped.suffix == ".pdb"
    assert dumped.is_file()


def test_from_id_without_file_path_lv0(client: DeepOriginClient) -> None:
    """from_id returns metadata-only when the platform record has no file_path."""
    from unittest.mock import patch

    record = {
        "id": "metadata-only",
        "protein_name": "orphan",
        "file_path": None,
        "pdb_id": None,
        "project_id": None,
    }
    with patch.object(client.entities, "get_protein", return_value=record):
        protein = Protein.from_id("metadata-only", client=client)

    assert protein.id == "metadata-only"
    assert protein.name == "orphan"
    assert protein.structure is None
    assert protein.remote_path is None


def test_from_id_download_false_rehydrates_lv1(
    client: DeepOriginClient,
    registered_protein: Protein,
) -> None:
    """Rehydration tests must use a record with file_path; download() loads structure."""
    assert registered_protein.id is not None
    assert registered_protein.remote_path is not None

    protein = Protein.from_id(
        str(registered_protein.id),
        client=client,
        download=False,
    )
    assert protein.remote_path == registered_protein.remote_path
    assert protein.structure is None

    protein.download(client=client)
    assert protein.structure is not None
    assert protein.local_path is not None


def test_from_file_lv0():
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")

    assert (
        str(protein.sequence[0])
        == "STNPPPPETSNPNKPKRQTNQLQYLLRVVLKTLWKHQFAWPFQQPVDAVKLNLPDYYKIIKTPMDMGTIKKRLENNYYWNAQECIQDFNTMFTNCYIYNKPGDDIVLMAEALEKLFLQKINELPTE"
    )


def test_bounding_box_volume_lv0():
    """Bounding box volume matches the product of coordinate spans in Å³."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    coords = protein.coordinates
    span = coords.max(axis=0) - coords.min(axis=0)
    expected = float(span[0] * span[1] * span[2])

    volume = protein.bounding_box_volume()

    assert volume == expected
    assert volume > 0


def test_bounding_box_volume_requires_loaded_structure(
    client: DeepOriginClient,
) -> None:
    """Metadata-only platform proteins cannot compute bounding box volume."""
    protein = Protein.from_id("metadata-only-bbox", client=client)

    assert protein.structure is None
    assert protein.remote_path is None

    with pytest.raises(ValueError, match="Protein structure is not loaded"):
        protein.bounding_box_volume()


def test_from_file_invalid_pdb_lv0():
    pdb_path = Path(__file__).parent / "fixtures" / "1eby-illegal-element-name.pdb"
    with pytest.raises(
        DeepOriginException,
        match="The PDB file is invalid. It could not be parsed by RDKit.",
    ):
        _ = Protein.from_file(pdb_path)


def test_from_name_lv0(pytestconfig):
    """Test creating a protein from a name.

    Note: This test is skipped when using --mock flag as it requires
    a real network connection to the RCSB search API.
    """
    use_mock = pytestconfig.getoption("--mock", default=False)
    if use_mock:
        pytest.skip("Skipping test_from_name with --mock (requires RCSB search API)")

    protein = Protein.from_name("conotoxin")
    # Check that a valid protein with PDB ID is returned
    assert protein.pdb_id is not None
    assert len(protein.pdb_id) == 4  # PDB IDs are 4 characters

    # Check that we have at least one sequence
    assert len(protein.sequence) > 0
    # Check that the sequence contains cysteine residues (conotoxins are cysteine-rich)
    sequence_str = str(protein.sequence[0])
    assert "C" in sequence_str
    # Check that the sequence length is reasonable for a conotoxin (typically 10-40 amino acids)
    assert 10 <= len(sequence_str) <= 100


def test_from_pdb_id_lv0():
    conotoxin = Protein.from_pdb_id("2JUQ")

    os.remove(conotoxin.local_path)

    _ = Protein.from_pdb_id("2JUQ")


def test_from_pdb_id_with_invalid_id_lv0():
    with pytest.raises(DeepOriginException, match=r".*Failed to create Protein.*"):
        Protein.from_pdb_id("foobar")


def test_find_missing_residues():
    protein = Protein.from_pdb_id("5QSP")
    missing = protein.find_missing_residues()
    # The expected output is based on the documentation example
    expected = {
        "A": [(511, 514), (547, 550), (679, 682), (841, 855)],
        "B": [(509, 516), (546, 551), (679, 684), (840, 854)],
    }
    assert missing == expected


def test_pdb_id():
    protein = Protein.from_pdb_id("1EBY")
    assert protein.pdb_id == "1EBY"


def test_extract_ligand():
    protein = Protein.from_pdb_id("1EBY")
    ligand = protein.extract_ligand()

    # BEB: benzyl ethers, indanols and amide carbonyls, with bond orders
    # from the Chemical Component Dictionary (CONECT records carry none).
    assert (
        ligand.smiles
        == "O=C(N[C@H]1c2ccccc2C[C@H]1O)[C@H](OCc1ccccc1)[C@H](O)[C@@H](O)[C@@H](OCc1ccccc1)C(=O)N[C@H]1c2ccccc2C[C@H]1O"
    )


def test_extract_ligand_mutates_protein():
    """Test that extract_ligand both extracts the ligand and removes it from the protein."""
    protein = Protein.from_pdb_id("1EBY")

    # Store initial state
    initial_structure_length = len(protein.structure)
    initial_block_content_length = (
        len(protein.block_content) if protein.block_content else 0
    )

    # Extract the ligand
    ligand = protein.extract_ligand()

    # Verify the ligand was extracted correctly
    expected_smiles = "O=C(N[C@H]1c2ccccc2C[C@H]1O)[C@H](OCc1ccccc1)[C@H](O)[C@@H](O)[C@@H](OCc1ccccc1)C(=O)N[C@H]1c2ccccc2C[C@H]1O"
    assert ligand.smiles == expected_smiles

    # Verify the protein structure was mutated (ligand removed)
    assert len(protein.structure) < initial_structure_length

    # Verify the block_content was updated
    if protein.block_content:
        assert len(protein.block_content) < initial_block_content_length

        # Verify that the protein structure no longer contains the ligand atoms
        # The structure should have fewer atoms after ligand removal
        assert len(protein.structure) < initial_structure_length


def test_extract_ligand_updates_master_record():
    """Test that extract_ligand properly updates the MASTER record in the PDB content."""
    protein = Protein.from_pdb_id("1EBY")

    # Find the initial MASTER record
    initial_master_line = None
    for line in protein.block_content.split("\n"):
        if line.startswith("MASTER"):
            initial_master_line = line
            break

    assert initial_master_line is not None, "MASTER record should exist in PDB"

    # Parse initial values
    parts = initial_master_line.split()
    initial_atom_count = int(parts[8])  # Field 9: total number of atoms
    initial_conect_count = int(parts[10])  # Field 11: total number of CONECT records

    # Extract the ligand
    ligand = protein.extract_ligand()

    # Find the updated MASTER record
    updated_master_line = None
    for line in protein.block_content.split("\n"):
        if line.startswith("MASTER"):
            updated_master_line = line
            break

    assert updated_master_line is not None, (
        "MASTER record should still exist after ligand extraction"
    )

    # Parse updated values
    parts = updated_master_line.split()
    updated_atom_count = int(parts[8])
    updated_conect_count = int(parts[10])

    # Verify that the MASTER record was updated
    assert updated_atom_count < initial_atom_count, (
        "Atom count should decrease after ligand removal"
    )
    assert updated_conect_count <= initial_conect_count, (
        "CONECT count should not increase after ligand removal"
    )

    # Verify the ligand was extracted correctly
    expected_smiles = "O=C(N[C@H]1c2ccccc2C[C@H]1O)[C@H](OCc1ccccc1)[C@H](O)[C@@H](O)[C@@H](OCc1ccccc1)C(=O)N[C@H]1c2ccccc2C[C@H]1O"
    assert ligand.smiles == expected_smiles


def test_protein_base64():
    """Test that we can convert a Protein to base64 and back"""
    # Create a protein using from_pdb_id
    protein = Protein.from_pdb_id("1EBY")

    # Convert to base64
    b64 = protein.to_base64()

    # Convert back from base64
    new_protein = Protein.from_base64(b64)

    # Verify the structures have the same number of atoms
    assert len(new_protein.structure) == len(protein.structure)

    # Verify the structures have the same coordinates (within numerical precision)

    np.testing.assert_array_almost_equal(
        new_protein.structure.coord,
        protein.structure.coord,
        decimal=3,
    )


def test_protein_hash():
    """Test that we can convert a Protein to SHA256 hash"""
    # Create a protein using from_pdb_id
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")

    assert (
        "db4aa32e2e8ffa976a60004a8361b86427a2e5653a6623bb60b7913445902549"
        == protein.to_hash()
    ), "Protein hash did not match"


def test_extract_ligand_remove_water():
    """check that we can remove waters after we extract the ligand"""

    protein = Protein.from_pdb_id("1EBY")
    _ = protein.extract_ligand()

    protein.remove_water()


def test_extract_ligand_filters_water():
    """Test that extract_ligand filters out water molecules (HOH, WAT, H2O)."""
    protein = Protein.from_pdb_id("1EBY")

    # Count water molecules before extraction
    water_count_before = sum(
        1
        for line in protein.block_content.split("\n")
        if line.startswith("HETATM")
        and line[17:20].strip().upper() in {"HOH", "WAT", "H2O"}
    )

    # Extract ligand - should exclude water molecules
    ligand = protein.extract_ligand()

    # Verify ligand was extracted (should not be None)
    assert ligand is not None

    # Verify that water molecules were not included in the extracted ligand
    # The ligand should have atoms, but they should not be water
    assert len(ligand.mol.GetAtoms()) > 0

    # Verify that water molecules are still in the protein block_content
    # (extract_ligand only removes the ligand, not water)
    water_count_after = sum(
        1
        for line in protein.block_content.split("\n")
        if line.startswith("HETATM")
        and line[17:20].strip().upper() in {"HOH", "WAT", "H2O"}
    )

    # Water should still be in block_content until explicitly removed
    # (extract_ligand only removes the ligand, not water)
    assert water_count_after == water_count_before


def test_extract_ligand_with_custom_exclude_resnames():
    """Test that extract_ligand respects custom exclude_resnames parameter."""
    protein = Protein.from_pdb_id("1EBY")

    # Extract ligand excluding a custom residue name (should work even if not present)
    ligand = protein.extract_ligand(exclude_resnames={"HOH", "CUSTOM"})

    assert ligand is not None
    assert len(ligand.mol.GetAtoms()) > 0


# 3JVS ligand AGY (chain A): a nitro-substituted aromatic acyl semicarbazide.
_AGY_HETATM_BLOCK = """\
HETATM 2090  C1  AGY A 900      33.993  -2.124  17.638  1.00 38.11           C
HETATM 2091  N1  AGY A 900      31.494  -2.422  17.781  1.00 36.13           N
HETATM 2092  O1  AGY A 900      31.389  -3.621  15.852  1.00 37.96           O
HETATM 2093  C2  AGY A 900      32.624  -1.631  17.588  1.00 37.29           C
HETATM 2094  N2  AGY A 900      29.793  -4.018  17.347  1.00 36.24           N
HETATM 2095  O2  AGY A 900      30.434  -5.459  19.401  1.00 33.94           O
HETATM 2096  C3  AGY A 900      35.136  -1.187  17.415  1.00 36.67           C
HETATM 2097  N3  AGY A 900      29.137  -3.804  18.606  1.00 32.73           N
HETATM 2098  O3  AGY A 900      24.819  -4.761  22.699  1.00 44.05           O
HETATM 2099  C4  AGY A 900      34.274  -3.517  17.902  1.00 38.08           C
HETATM 2100  N4  AGY A 900      25.645  -3.809  22.368  1.00 42.51           N
HETATM 2101  O4  AGY A 900      25.168  -2.548  22.031  1.00 41.99           O
HETATM 2102  C5  AGY A 900      32.412  -0.211  17.318  1.00 37.27           C
HETATM 2103  C6  AGY A 900      34.899   0.211  17.150  1.00 38.14           C
HETATM 2104  C7  AGY A 900      36.476  -1.676  17.465  1.00 38.49           C
HETATM 2105  C8  AGY A 900      35.637  -3.993  17.949  1.00 39.33           C
HETATM 2106  C9  AGY A 900      33.526   0.702  17.101  1.00 38.65           C
HETATM 2107  C10 AGY A 900      30.916  -3.351  16.964  1.00 36.25           C
HETATM 2108  C11 AGY A 900      36.735  -3.078  17.732  1.00 39.36           C
HETATM 2109  C12 AGY A 900      29.547  -4.611  19.622  1.00 36.47           C
HETATM 2110  C13 AGY A 900      28.951  -4.490  20.951  1.00 36.20           C
HETATM 2111  C14 AGY A 900      27.580  -4.181  21.071  1.00 38.33           C
HETATM 2112  C15 AGY A 900      29.735  -4.682  22.130  1.00 37.75           C
HETATM 2113  C16 AGY A 900      26.943  -4.057  22.348  1.00 39.76           C
HETATM 2114  C17 AGY A 900      29.139  -4.565  23.440  1.00 39.30           C
HETATM 2115  C18 AGY A 900      27.709  -4.243  23.595  1.00 38.59           C
HETATM 2116  C19 AGY A 900      27.122  -4.133  25.024  1.00 37.78           C
HETATM 2117  C20 AGY A 900      28.026  -3.363  26.017  1.00 36.59           C
HETATM 2118  C21 AGY A 900      25.795  -3.327  25.291  1.00 37.53           C
HETATM 2119  C22 AGY A 900      26.812  -5.570  25.486  1.00 37.68           C
END
"""


def test_assign_ccd_bond_orders_restores_orders_and_charges():
    """PDB CONECT records have no bond orders; the CCD supplies them and the nitro charges."""
    from rdkit import Chem

    from deeporigin.drug_discovery.structures.protein import _assign_ccd_bond_orders

    mol = Chem.MolFromPDBBlock(_AGY_HETATM_BLOCK, sanitize=False, removeHs=False)
    assert _assign_ccd_bond_orders(mol) == []
    Chem.SanitizeMol(mol)

    assert Chem.MolToSmiles(mol) == (
        "CC(C)(C)c1ccc(C(=O)NNC(=O)Nc2cccc3ccccc23)cc1[N+](=O)[O-]"
    )


def test_assign_ccd_bond_orders_skips_residue_with_mismatched_atom_names():
    """A reused CCD code (LIG is a real, different component) must not be trusted."""
    from rdkit import Chem

    from deeporigin.drug_discovery.structures.protein import _assign_ccd_bond_orders

    block = _AGY_HETATM_BLOCK.replace(" AGY ", " LIG ")
    mol = Chem.MolFromPDBBlock(block, sanitize=False, removeHs=False)

    assert _assign_ccd_bond_orders(mol) == ["LIG"]
    assert all(b.GetBondType() == Chem.BondType.SINGLE for b in mol.GetBonds())


def test_extract_ligand_assigns_bond_orders_offline():
    """extract_ligand on a local PDB yields aromatic rings and carbonyls, not all-single bonds."""
    from rdkit.Chem import rdMolDescriptors

    protein = Protein.from_file(Path(__file__).parent / "fixtures" / "1eby.pdb")
    ligand = protein.extract_ligand()

    assert rdMolDescriptors.CalcNumAromaticRings(ligand.mol) == 4
    assert any(b.GetBondTypeAsDouble() == 2.0 for b in ligand.mol.GetBonds())


def test_extract_ligand_warns_when_bond_orders_unresolved(tmp_path):
    """An unresolvable ligand residue still extracts, but with a warning."""
    source = Path(__file__).parent / "fixtures" / "1eby.pdb"
    renamed = tmp_path / "1eby-renamed-ligand.pdb"
    renamed.write_text(
        "".join(
            line[:17] + "LIG" + line[20:]
            if line.startswith("HETATM") and line[17:20] == "BEB"
            else line
            for line in source.read_text().splitlines(keepends=True)
        )
    )
    protein = Protein.from_file(renamed)

    with pytest.warns(UserWarning, match="Could not assign bond orders.*LIG"):
        ligand = protein.extract_ligand()

    assert len(ligand.mol.GetAtoms()) > 0


def test_extract_ligand_from_cif_with_many_hetatms():
    """Test that extract_ligand works correctly with CIF files containing many HETATMs including water."""
    cif_path = Path(__file__).parent / "fixtures" / "1nsg-assembly1.cif"
    protein = Protein.from_file(cif_path)

    # Verify it's a CIF file
    assert protein.block_type == "cif"
    assert protein.block_content is not None

    # Count water molecules before extraction
    # Convert to PDB to count HETATMs

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".pdb", delete=False
    ) as temp_file:
        temp_pdb_path = temp_file.name

    try:
        protein.to_pdb(temp_pdb_path)
        with open(temp_pdb_path, "r") as pdb_file:
            all_hetatm_lines = [line for line in pdb_file if line.startswith("HETATM")]
            water_hetatm_lines = [
                line
                for line in all_hetatm_lines
                if line[17:20].strip().upper() in {"HOH", "WAT", "H2O"}
            ]
            non_water_hetatm_lines = [
                line
                for line in all_hetatm_lines
                if line[17:20].strip().upper() not in {"HOH", "WAT", "H2O"}
            ]

        # Verify we have both water and non-water HETATMs
        assert len(water_hetatm_lines) > 0, "Should have water molecules"
        assert len(non_water_hetatm_lines) > 0, "Should have non-water HETATMs"

        # Extract ligand - should exclude water molecules and succeed
        ligand = protein.extract_ligand()

        # Verify ligand was extracted successfully
        assert ligand is not None
        assert len(ligand.mol.GetAtoms()) > 0

        # Verify that water molecules were filtered out
        # The ligand should not contain only water atoms
        # (we can't easily verify the exact count without parsing the PDB block,
        # but we can verify RDKit successfully parsed a non-water ligand)
        assert ligand.smiles is not None
        assert len(ligand.smiles) > 0

    finally:
        if os.path.exists(temp_pdb_path):
            os.remove(temp_pdb_path)


def test_extract_ligand_mutates_protein_cif():
    """Test that extract_ligand both extracts the ligand and removes it from a CIF protein."""
    cif_path = Path(__file__).parent / "fixtures" / "1EBY.cif"
    protein = Protein.from_file(cif_path)

    # Verify it's a CIF file
    assert protein.block_type == "cif"
    assert protein.block_content is not None

    # Store initial state
    initial_structure_length = len(protein.structure)
    initial_block_content_length = len(protein.block_content)

    # Extract the ligand
    ligand = protein.extract_ligand()

    # Verify the ligand was extracted correctly
    assert ligand is not None
    assert ligand.smiles is not None
    assert len(ligand.mol.GetAtoms()) > 0

    # Verify the protein structure was mutated (ligand removed)
    assert len(protein.structure) < initial_structure_length

    # Verify the block_content was updated
    assert len(protein.block_content) < initial_block_content_length

    # Verify that the protein structure no longer contains the ligand atoms
    # The structure should have fewer atoms after ligand removal
    assert len(protein.structure) < initial_structure_length


def test_from_file_cif():
    """Test creating a protein from a CIF file."""
    cif_path = Path(__file__).parent / "fixtures" / "1EBY.cif"
    protein = Protein.from_file(cif_path)

    assert protein.name == "1EBY"
    assert protein.block_type == "cif"
    assert protein.local_path == str(cif_path.resolve())
    assert len(protein.structure) > 0
    assert protein.block_content is not None
    assert (
        "data_1EBY" in protein.block_content or "data_r1ebysf" in protein.block_content
    )


def test_from_file_invalid_extension():
    """Test that from_file raises ValueError for unsupported file types."""
    # Create a temporary file with an unsupported extension
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp_file:
        tmp_file.write("test content")
        tmp_path = tmp_file.name

    try:
        with pytest.raises(ValueError, match=r".*Unsupported file type.*"):
            Protein.from_file(tmp_path)
    finally:
        os.unlink(tmp_path)


def test_load_structure_from_block_cif():
    """Test loading structure from CIF block content."""
    cif_path = Path(__file__).parent / "fixtures" / "1EBY.cif"
    cif_content = cif_path.read_text()

    structure = Protein.load_structure_from_block(cif_content, "cif")

    assert len(structure) > 0
    assert hasattr(structure, "coord")


def test_load_structure_from_block_invalid_type():
    """Test that load_structure_from_block raises ValueError for unsupported types."""
    with pytest.raises(ValueError, match=r".*Unsupported block type.*"):
        Protein.load_structure_from_block("test content", "xyz")


def test_protein_sync_lv1(client: DeepOriginClient):
    """Test that we can sync a protein"""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    protein.sync(client=client)
    assert protein.id is not None
    assert protein.project_id == client.project_id


def test_protein_update_lv1(client: DeepOriginClient):
    """Test domain Protein.update patches file_path on an existing record."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.sync(client=client)
    assert protein.id is not None
    fetched = client.entities.get_protein(id=protein.id)
    original_path = fetched["file_path"]

    new_path = f"testing/updated-protein-{uuid.uuid4().hex[:8]}.pdb"
    try:
        protein.update(client=client, remote_path=new_path)
        assert protein.remote_path == new_path

        fetched = client.entities.get_protein(id=protein.id)
        assert fetched["file_path"] == new_path
        assert fetched["version"] >= 2
    finally:
        client.entities.update_protein(protein.id, file_path=original_path)


def test_protein_update_requires_id():
    """Test that Protein.update raises when id is unset."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    with pytest.raises(ValueError, match="platform id"):
        protein.update()


def test_protein_download_raises_when_structure_loaded_without_paths() -> None:
    """download() must not return an empty string when no local path exists."""
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.local_path = None
    assert protein.structure is not None
    with pytest.raises(ValueError, match="local file path"):
        protein.download()


def test_from_remote_file_sets_remote_path_lv0(client: DeepOriginClient) -> None:
    """from_remote_file downloads via the client and sets remote_path."""
    from unittest.mock import patch

    remote = "org/files/protein.pdb"
    local_pdb = str(BRD_DATA_DIR / "brd.pdb")
    with patch.object(client.files, "download", return_value=local_pdb) as dl:
        protein = Protein.from_remote_file(remote, client=client)
    dl.assert_called_once_with(remote_path=remote, lazy=True)
    assert protein.remote_path == remote
    assert protein.local_path == local_pdb
    assert protein.structure is not None


def test_protein_show_accepts_pose_set_and_pose_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Protein.show converts PoseSet / list[Pose] via to_ligand for molstar."""
    from unittest.mock import patch

    from deeporigin.drug_discovery.structures.pose import Pose, PoseSet

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    local = tmp_path / "pose.sdf"
    local.write_bytes((BRD_DATA_DIR / "brd-3.sdf").read_bytes())
    pose = Pose(
        ligand_id="L1",
        id="P1",
        local_path=str(local),
        remote_path="entities/poses/p1.sdf",
        name="ethanol",
    )

    monkeypatch.setattr(
        "deeporigin.utils.notebook.render_html",
        lambda html: html,
    )
    with patch(
        "deeporigin.viz.molstar_html.render_protein_with_poses_html",
        return_value="<poses/>",
    ) as render_poses:
        out = protein.show(poses=PoseSet(poses=[pose]))
        assert out == "<poses/>"
        render_poses.assert_called_once()
        out2 = protein.show(poses=[pose])
        assert out2 == "<poses/>"
        assert render_poses.call_count == 2
