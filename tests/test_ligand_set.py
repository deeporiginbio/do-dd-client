import os
from pathlib import Path
import shutil
import tempfile

import pytest
from rdkit import Chem

from deeporigin.drug_discovery import BRD_DATA_DIR, DATA_DIR
from deeporigin.drug_discovery.protonation import Protonation
from deeporigin.drug_discovery.structures.ligand import Ligand, LigandSet
from deeporigin.exceptions import DeepOriginException
from deeporigin.platform.client import DeepOriginClient

# Import shared test fixtures


SDF_TEST_CASES = [
    (DATA_DIR / "ligands" / "ligands-brd-all.sdf", 8),
    (DATA_DIR / "ligands" / "42-ligands.sdf", 42),
]

BRD_SMILES = {
    "C/C=C/Cn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "C=CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "C=CCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "CCCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "CCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "CN(C)C(=O)c1cccc(-c2cn(C)c(=O)c3[nH]ccc23)c1",
    "COCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
}


@pytest.mark.parametrize("filename,expected_count", SDF_TEST_CASES)
def test_ligand_set_from_sdf_file_lv0(filename, expected_count):
    """Test that we can make many ligands from a single SDF file with many molecules"""
    ligands = LigandSet.from_sdf(filename)
    assert len(ligands.ligands) == expected_count, f"Expected {expected_count} ligands"
    for ligand in ligands.ligands:
        assert isinstance(ligand, Ligand), "Expected a Ligand object"


def test_ligand_set_from_file_matches_from_sdf():
    """from_file validates and loads the same as from_sdf."""
    filename = DATA_DIR / "ligands" / "ligands-brd-all.sdf"
    a = LigandSet.from_sdf(filename)
    b = LigandSet.from_file(filename)
    assert len(a.ligands) == len(b.ligands)
    assert [x.smiles for x in a.ligands] == [x.smiles for x in b.ligands]


def test_ligand_set_from_file_matches_from_csv():
    """from_file validates and loads the same as from_csv."""
    csv_path = DATA_DIR / "ligands" / "ligands.csv"
    a = LigandSet.from_csv(str(csv_path), smiles_column="SMILES")
    b = LigandSet.from_file(csv_path, smiles_column="SMILES")
    assert len(a.ligands) == len(b.ligands)
    assert [x.smiles for x in a.ligands] == [x.smiles for x in b.ligands]


def test_ligand_set_from_file_rejects_non_sdf_extension():
    sdf_path = DATA_DIR / "ligands" / "ligands-brd-all.sdf"
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(Path(sdf_path).read_bytes())
        tmp = f.name
    try:
        with pytest.raises(DeepOriginException, match="Unsupported file type"):
            LigandSet.from_file(tmp)
    finally:
        os.unlink(tmp)


def test_ligand_set_from_file_rejects_bad_content():
    with tempfile.NamedTemporaryFile(suffix=".sdf", mode="w", delete=False) as f:
        f.write("not a molecule file\n")
        tmp = f.name
    try:
        with pytest.raises(DeepOriginException, match="does not appear to contain"):
            LigandSet.from_file(tmp)
    finally:
        os.unlink(tmp)


def test_ligand_set_from_sdf_files_lv0():
    """Test that we can create a LigandSet from multiple SDF files by concatenating them"""

    # Get paths to test SDF files
    brd_file = DATA_DIR / "ligands" / "ligands-brd-all.sdf"
    ligands_42_file = DATA_DIR / "ligands" / "42-ligands.sdf"

    # Test with multiple files
    file_paths = [str(brd_file), str(ligands_42_file)]
    ligands = LigandSet.from_sdf_files(file_paths)

    # Should have combined count from both files (8 + 42 = 50)
    expected_total = 8 + 42
    assert len(ligands.ligands) == expected_total, (
        f"Expected {expected_total} ligands total"
    )

    # All should be Ligand objects
    for ligand in ligands.ligands:
        assert isinstance(ligand, Ligand), "Expected a Ligand object"
        assert ligand.local_path in file_paths, (
            "Expected ligand.local_path to match source file"
        )
        assert os.path.exists(ligand.local_path), (
            "Expected ligand.local_path to exist on disk"
        )

    # Test with single file (should work the same as from_sdf)
    single_file_paths = [str(brd_file)]
    single_ligands = LigandSet.from_sdf_files(single_file_paths)
    assert len(single_ligands.ligands) == 8
    assert all(lig.local_path == str(brd_file) for lig in single_ligands.ligands), (
        "Expected all ligands to keep their source file path"
    )
    assert set(single_ligands.to_smiles()) == set(
        LigandSet.from_sdf(brd_file).to_smiles()
    )


def test_ligand_set_from_sdf_files_error_handling_lv0():
    """Test error handling in from_sdf_files method"""

    # Test with non-existent file
    with pytest.raises(
        FileNotFoundError, match="Failed to process file 'nonexistent.sdf'"
    ):
        LigandSet.from_sdf_files(["nonexistent.sdf"])

    # Test with empty list
    empty_ligands = LigandSet.from_sdf_files([])
    assert len(empty_ligands.ligands) == 0

    # Test with valid and invalid files mixed
    brd_file = DATA_DIR / "ligands" / "ligands-brd-all.sdf"
    with pytest.raises(
        FileNotFoundError, match="Failed to process file 'nonexistent.sdf'"
    ):
        LigandSet.from_sdf_files([str(brd_file), "nonexistent.sdf"])


def test_filter_top_poses():
    """Test the filter_top_poses method for selecting best poses"""

    # Load test data from the provided SDF file
    ligand_set = LigandSet.from_sdf("tests/fixtures/brd-all-poses.sdf")

    # Verify we have multiple poses for testing
    assert len(ligand_set) > 0

    # Test filtering by binding energy (default)
    filtered_by_energy = ligand_set.filter_top_poses()

    # Should have fewer ligands after filtering (one per unique molecule)
    assert len(filtered_by_energy) <= len(ligand_set)
    assert len(filtered_by_energy) > 0

    # Verify that all filtered ligands have the required properties
    for ligand in filtered_by_energy:
        assert "initial_smiles" in ligand.properties
        assert "Binding Energy" in ligand.properties
        assert "POSE SCORE" in ligand.properties

    # Test filtering by pose score
    filtered_by_score = ligand_set.filter_top_poses(by_pose_score=True)

    # Should have the same number of unique molecules
    assert len(filtered_by_score) == len(filtered_by_energy)

    # Verify that all filtered ligands have the required properties
    for ligand in filtered_by_score:
        assert "initial_smiles" in ligand.properties
        assert "Binding Energy" in ligand.properties
        assert "POSE SCORE" in ligand.properties

    # Test that filtering actually reduces the number of ligands
    # (assuming the test file has multiple poses for some molecules)
    if len(ligand_set) > len(filtered_by_energy):
        print(
            f"Original ligands: {len(ligand_set)}, Filtered ligands: {len(filtered_by_energy)}"
        )
        print("Filtering successfully reduced the number of ligands")
    else:
        print("All ligands had unique initial_smiles, no filtering occurred")


def test_filter_top_poses_edge_cases():
    """Test edge cases for filter_top_poses method"""

    # Test with empty LigandSet
    empty_set = LigandSet(ligands=[])
    filtered = empty_set.filter_top_poses()
    assert len(filtered) == 0

    # Test with single ligand from SDF file
    # Create a single-ligand set by taking just the first ligand
    full_set = LigandSet.from_sdf("tests/fixtures/brd-all-poses.sdf")
    single_set = LigandSet(ligands=[full_set.ligands[0]])
    filtered = single_set.filter_top_poses()
    assert len(filtered) == 1

    # Test that filtering works with ligands that have all required properties
    # (which the SDF file should have)
    if len(full_set) > 0:
        # Take a subset of ligands that should have the required properties
        subset_ligands = [
            ligand
            for ligand in full_set.ligands
            if "initial_smiles" in ligand.properties
        ]
        if subset_ligands:
            subset_set = LigandSet(ligands=subset_ligands[:3])  # Take first 3
            filtered_subset = subset_set.filter_top_poses()
            assert len(filtered_subset) <= len(subset_set)
            assert len(filtered_subset) > 0


def test_filter_top_poses_error_handling():
    """Test error handling in filter_top_poses method"""

    from deeporigin.exceptions import DeepOriginException

    # Load the test SDF file
    ligand_set = LigandSet.from_sdf("tests/fixtures/brd-all-poses.sdf")

    # Create a test ligand with invalid binding energy by modifying properties
    if len(ligand_set) > 1:
        # We need at least 2 ligands to trigger the filtering logic
        test_ligand1 = ligand_set.ligands[0]
        test_ligand2 = ligand_set.ligands[1]

        # Temporarily modify properties to test error handling
        original_properties1 = test_ligand1.properties.copy()
        original_properties2 = test_ligand2.properties.copy()

        # Make both ligands have the same SMILES so filtering is triggered
        test_ligand1.properties["SMILES"] = "test_smiles"
        test_ligand2.properties["SMILES"] = "test_smiles"

        # Test with invalid binding energy
        test_ligand1.properties["Binding Energy"] = "not_a_number"
        test_ligand2.properties["Binding Energy"] = "-7.0"
        invalid_set = LigandSet(ligands=[test_ligand1, test_ligand2])
        with pytest.raises(DeepOriginException, match="Invalid binding energy value"):
            invalid_set.filter_top_poses(by_pose_score=False)

        # Test with invalid pose score
        test_ligand1.properties["Binding Energy"] = "-7.0"  # Restore valid value
        test_ligand1.properties["POSE SCORE"] = "not_a_number"
        test_ligand2.properties["POSE SCORE"] = "0.8"
        invalid_score_set = LigandSet(ligands=[test_ligand1, test_ligand2])
        with pytest.raises(DeepOriginException, match="Invalid pose score value"):
            invalid_score_set.filter_top_poses(by_pose_score=True)

        # Test with missing binding energy property
        test_ligand1.properties["POSE SCORE"] = "0.8"  # Restore valid value
        del test_ligand1.properties["Binding Energy"]
        no_energy_set = LigandSet(ligands=[test_ligand1, test_ligand2])
        with pytest.raises(
            DeepOriginException, match="missing 'Binding Energy' property"
        ):
            no_energy_set.filter_top_poses(by_pose_score=False)

        # Test with missing pose score property
        test_ligand1.properties["Binding Energy"] = "-7.0"  # Restore valid value
        del test_ligand1.properties["POSE SCORE"]
        no_score_set = LigandSet(ligands=[test_ligand1, test_ligand2])
        with pytest.raises(
            DeepOriginException,
            match="missing 'POSE SCORE' or 'pose_score' property",
        ):
            no_score_set.filter_top_poses(by_pose_score=True)

        # Restore original properties
        test_ligand1.properties = original_properties1
        test_ligand2.properties = original_properties2


def test_filter_top_poses_accepts_pose_score_snake_case():
    """Ranking by pose score accepts the ``pose_score`` property name alone."""
    ligand_set = LigandSet.from_sdf("tests/fixtures/brd-all-poses.sdf")
    if len(ligand_set) < 2:
        pytest.skip("need at least two ligands")
    ligand_a = ligand_set.ligands[0]
    ligand_b = ligand_set.ligands[1]
    ligand_a.properties = ligand_a.properties.copy()
    ligand_b.properties = ligand_b.properties.copy()
    ligand_a.properties["SMILES"] = ligand_b.properties["SMILES"] = "shared_smiles"
    ligand_a.properties.pop("POSE SCORE", None)
    ligand_b.properties.pop("POSE SCORE", None)
    ligand_a.properties["pose_score"] = "0.3"
    ligand_b.properties["pose_score"] = "0.9"
    filtered = LigandSet(ligands=[ligand_a, ligand_b]).filter_top_poses(
        by_pose_score=True
    )
    assert len(filtered) == 1
    assert filtered.ligands[0].properties["pose_score"] == "0.9"


def test_ligand_set_filter_unsupported():
    """filter_unsupported drops ligands with atoms outside SUPPORTED_ATOM_SYMBOLS."""
    ok = Ligand.from_smiles("CCO")
    bad = Ligand.from_smiles("B")
    original = LigandSet(ligands=[ok, bad])
    filtered = original.filter_unsupported()
    assert len(filtered) == 1
    assert filtered.ligands[0].smiles == ok.smiles
    assert len(original) == 2


def test_ligand_set_from_csv():
    """Test that we can create Ligands from a CSV file using the from_csv classmethod"""

    # Get the path to the test CSV file
    csv_path = DATA_DIR / "ligands" / "ligands.csv"

    # Create ligands from the CSV file
    ligands = LigandSet.from_csv(str(csv_path), smiles_column="SMILES")

    # Verify we got the expected number of ligands
    assert len(ligands.ligands) == 30  # Total number of valid SMILES in the file

    # Check a few properties of the first ligand
    first_ligand = ligands.ligands[0]
    assert isinstance(first_ligand, Ligand)
    assert first_ligand.mol is not None
    assert first_ligand.mol.GetNumAtoms() > 0
    assert first_ligand.local_path is None

    # Verify properties were correctly loaded
    props = ["score", "binding_energy", "pose_score"]
    df = ligands.to_dataframe()
    for prop in props:
        assert prop in df.columns
        assert df[prop].notna().all()

    # Test with invalid SMILES column
    with pytest.raises(
        DeepOriginException, match="Column 'invalid' not found in CSV file"
    ):
        LigandSet.from_csv(str(csv_path), smiles_column="invalid")

    # Test with non-existent file
    with pytest.raises(FileNotFoundError):
        LigandSet.from_csv("nonexistent.csv")


def test_ligandset_to_sdf_requires_rehydration_when_remote_path_only():
    """LigandSet.to_sdf fails if any ligand has remote_path but no local file."""
    ligands = LigandSet.from_smiles(["CCO", "c1ccccc1"])
    ligands.ligands[0].remote_path = "entities/ligands/fake.sdf"

    with pytest.raises(DeepOriginException, match="not rehydrated"):
        ligands.to_sdf()


@pytest.mark.parametrize("filename,expected_count", SDF_TEST_CASES)
def test_sdf_roundtrip(filename, expected_count):
    """Test that we can roundtrip a LigandSet to an SDF file and back for all SDF_TEST_CASES"""

    ligands = LigandSet.from_sdf(filename)
    assert len(ligands.ligands) == expected_count
    sdf_path = ligands.to_sdf()
    assert os.path.exists(sdf_path)

    new_ligands = LigandSet.from_sdf(sdf_path)
    assert len(new_ligands.ligands) == len(ligands.ligands)
    assert set(ligands.to_smiles()) == set(new_ligands.to_smiles()), (
        "SMILES strings should be the same"
    )

    os.unlink(sdf_path)


def test_to_smiles():
    """Test that we can convert a LigandSet to SMILES strings"""

    ligands = LigandSet.from_sdf(DATA_DIR / "ligands" / "ligands-brd-all.sdf")

    assert set(ligands.to_smiles()) == BRD_SMILES, "SMILES strings should be the same"


def test_from_smiles():
    """Test that we can create a LigandSet from a list of SMILES strings."""

    ligands = LigandSet.from_smiles(BRD_SMILES)
    assert isinstance(ligands, LigandSet)
    assert len(ligands) == len(BRD_SMILES)

    # Check that all SMILES are present (order-insensitive)
    assert set(ligands.to_smiles()) == set(BRD_SMILES)
    for ligand in ligands:
        assert isinstance(ligand, Ligand)


def test_prepare():
    """Test that we can prepare a LigandSet"""

    ligands = LigandSet.from_smiles(BRD_SMILES)
    result = ligands.prepare()

    # Should return self for chaining
    assert result is ligands

    # All ligands should be prepared
    for ligand in ligands:
        assert ligand.prepared, "Ligand should be prepared"


def test_prepare_remove_hydrogens():
    """Test that prepare passes remove_hydrogens parameter correctly"""

    ligands = LigandSet.from_smiles({"CCO", "CC"})  # Ethanol and Ethane

    # Add hydrogens first
    for ligand in ligands:
        ligand.add_hydrogens()

    # Prepare with remove_hydrogens=True
    ligands.prepare(remove_hydrogens=True)

    # Check that hydrogens were removed from SMILES
    for ligand in ligands:
        assert "H" not in ligand.smiles, "Hydrogens should be removed from SMILES"

    # Test with remove_hydrogens=False
    ligands2 = LigandSet.from_smiles({"CCO", "CC"})
    for ligand in ligands2:
        ligand.add_hydrogens()

    ligands2.prepare(remove_hydrogens=False)

    # Check that hydrogens are preserved in SMILES
    for ligand in ligands2:
        assert "H" in ligand.smiles, "Hydrogens should be preserved in SMILES"


def test_prepare_rejects_multiple_fragments():
    """Test that prepare raises exception when ligands have multiple non-identical fragments"""

    # Create a ligand with multiple non-identical fragments
    ligand_with_fragments = Ligand.from_smiles("CCO.CC")  # Ethanol + Ethane
    ligands = LigandSet(ligands=[ligand_with_fragments])

    with pytest.raises(DeepOriginException, match="Fragment validation failed"):
        ligands.prepare()


def test_embed():
    """Test that we can minimize a LigandSet"""

    ligands = LigandSet.from_smiles(BRD_SMILES)
    ligands.embed()


def test_show(monkeypatch):
    """Test that LigandSet.show uses legacy MoleculeViewer (multi-mol SDF)."""
    from deeporigin.drug_discovery.structures import ligand as ligand_mod

    captured: dict[str, object] = {}

    class FakeViewer:
        def __init__(self, path: str, format: str = "sdf") -> None:
            captured["path"] = path
            captured["format"] = format

        def get_ligand_visualization_config(self) -> dict:
            return {"fake": True}

        def render_ligand(self, *, ligand_config: dict) -> str:
            captured["ligand_config"] = ligand_config
            return "<div id='legacy-ligand-set'>ok</div>"

    monkeypatch.setattr(ligand_mod, "MoleculeViewer", FakeViewer)
    monkeypatch.setattr(
        "deeporigin.utils.notebook.render_html",
        lambda html, **_kwargs: html,
    )

    ligands = LigandSet.from_smiles(BRD_SMILES)
    result = ligands.show()

    assert result == "<div id='legacy-ligand-set'>ok</div>"
    assert captured["format"] == "sdf"
    assert Path(str(captured["path"])).suffix == ".sdf"
    assert captured["ligand_config"] == {"fake": True}


def test_from_dir():
    """Test that we can create a LigandSet from a directory"""

    ligands = LigandSet.from_dir(DATA_DIR / "brd")
    assert len(ligands) == 8

    for ligand in ligands:
        assert ligand.local_path is not None
        assert os.path.exists(ligand.local_path)


def test_mcs():
    """Test that we can generate the MCS for a set of ligands"""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    ligands.mcs()


def test_compute_constraints():
    """Test that we can align a ligandset to a reference ligand"""

    from deeporigin.drug_discovery import BRD_DATA_DIR, LigandSet

    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    ligands.compute_constraints(reference=ligands.ligands[0])


def test_random_sample():
    """Test the random_sample method of LigandSet"""

    # Create a test LigandSet
    test_smiles = ["CCO", "CCCO", "CCCC", "CCCCC", "CCCCCC"]
    ligands = LigandSet.from_smiles(test_smiles)

    # Test basic sampling
    sample = ligands.random_sample(3)
    assert isinstance(sample, LigandSet)
    assert len(sample) == 3
    assert len(sample.ligands) == 3

    # Test that original is unchanged
    assert len(ligands) == 5
    assert len(ligands.ligands) == 5

    # Test that sampled ligands are from original set
    for ligand in sample.ligands:
        assert ligand in ligands.ligands

    # Test edge cases
    sample_all = ligands.random_sample(5)
    assert len(sample_all) == 5
    assert set(sample_all.to_smiles()) == set(ligands.to_smiles())

    sample_one = ligands.random_sample(1)
    assert len(sample_one) == 1
    assert sample_one.ligands[0] in ligands.ligands


def test_random_sample_validation():
    """Test validation in random_sample method"""

    test_smiles = ["CCO", "CCCO", "CCCC"]
    ligands = LigandSet.from_smiles(test_smiles)

    # Test invalid n values
    with pytest.raises(ValueError, match="n must be at least 1"):
        ligands.random_sample(0)

    with pytest.raises(ValueError, match="n must be at least 1"):
        ligands.random_sample(-1)

    with pytest.raises(
        ValueError, match="Cannot sample 5 ligands from a set of 3 ligands"
    ):
        ligands.random_sample(5)

    with pytest.raises(
        ValueError, match="Cannot sample 10 ligands from a set of 3 ligands"
    ):
        ligands.random_sample(10)


def test_random_sample_deterministic():
    """Test that random_sample returns different results on multiple calls"""

    test_smiles = ["CCO", "CCCO", "CCCC", "CCCCC", "CCCCCC", "CCCCCCC"]
    ligands = LigandSet.from_smiles(test_smiles)

    # Sample multiple times and check we get different results
    samples = []
    for _ in range(5):
        sample = ligands.random_sample(3)
        samples.append(sample)

    # Check that at least some samples are different (this is probabilistic but should work)
    sample_smiles = [tuple(sorted(sample.to_smiles())) for sample in samples]
    unique_samples = set(sample_smiles)

    # With 6 ligands, sampling 3 should give us multiple unique combinations
    # This test might occasionally fail due to randomness, but it's very unlikely
    assert len(unique_samples) > 1, "Random sampling should produce different results"


# Test LigandSet functionality
def test_ligandset_operations():
    """Test basic LigandSet operations"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create test ligands
    ligand1 = Ligand.from_smiles("CCO", name="Ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="Propanol")

    # Test LigandSet creation
    ligandset = LigandSet(ligands=[ligand1, ligand2])
    assert len(ligandset) == 2

    # Test iteration
    for ligand in ligandset:
        assert isinstance(ligand, Ligand)

    # Test indexing
    assert ligandset[0] == ligand1
    assert ligandset[1] == ligand2

    # Test containment
    assert ligand1 in ligandset
    assert ligand2 in ligandset


def test_ligandset_addition():
    """Test LigandSet addition operations"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    ligand1 = Ligand.from_smiles("CCO", name="Ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="Propanol")

    set1 = LigandSet(ligands=[ligand1])
    set2 = LigandSet(ligands=[ligand2])

    # Test LigandSet + LigandSet
    combined = set1 + set2
    assert len(combined) == 2

    # Test LigandSet + Ligand
    combined = set1 + ligand2
    assert len(combined) == 2

    # Test Ligand + LigandSet
    combined = ligand2 + set1
    assert len(combined) == 2


def test_ligandset_from_smiles():
    """Test LigandSet creation from SMILES"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    smiles_list = ["CCO", "CCCO", "CCCCO"]
    ligandset = LigandSet.from_smiles(smiles_list)

    assert len(ligandset) == 3
    assert all(isinstance(ligand, Ligand) for ligand in ligandset)
    assert ligandset[0].smiles == "CCO"
    assert ligandset[1].smiles == "CCCO"
    assert ligandset[2].smiles == "CCCCO"


def test_ligandset_to_dataframe():
    """Test LigandSet to DataFrame conversion"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    ligand1 = Ligand.from_smiles("CCO", name="Ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="Propanol")

    ligandset = LigandSet(ligands=[ligand1, ligand2])

    # Add properties
    ligand1.set_property("logP", 0.32)
    ligand2.set_property("logP", 0.88)

    df = ligandset.to_dataframe()
    assert len(df) == 2
    assert "SMILES" in df.columns
    assert "logP" in df.columns
    assert list(df.columns[:2]) == ["id", "SMILES"]


def test_ligandset_to_dataframe_after_molprops():
    """Molprops rows must not duplicate id/SMILES; columns are id, SMILES, then ADMET."""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    ligand = Ligand.from_smiles("CCO")
    ligand.id = "0"
    ligand._apply_molprops_result(
        {
            "ligand_id": "0",
            "smiles": "CCO",
            "logP": 1.2,
            "cyp2c19": 0.5,
        }
    )

    df = LigandSet(ligands=[ligand]).to_dataframe()

    assert list(df.columns) == ["id", "SMILES", "logP", "cyp2c19"]
    assert "ligand_id" not in df.columns
    assert "smiles" not in df.columns
    assert df.loc[0, "id"] == "0"
    assert df.loc[0, "SMILES"] == "CCO"


def test_ligandset_indexing_and_slicing():
    """Test LigandSet indexing and slicing behavior"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create test ligands
    test_smiles = ["CCO", "CCCO", "CCCC", "CCCCC"]
    ligandset = LigandSet.from_smiles(test_smiles)

    # Test single indexing (should return Ligand)
    single_ligand = ligandset[0]
    assert isinstance(single_ligand, Ligand)
    assert single_ligand.smiles == "CCO"

    # Test slicing (should return LigandSet)
    subset = ligandset[1:3]
    assert isinstance(subset, LigandSet)
    assert len(subset) == 2
    assert subset[0].smiles == "CCCO"
    assert subset[1].smiles == "CCCC"

    # Test slice from beginning
    start_slice = ligandset[:2]
    assert isinstance(start_slice, LigandSet)
    assert len(start_slice) == 2

    # Test slice to end
    end_slice = ligandset[2:]
    assert isinstance(end_slice, LigandSet)
    assert len(end_slice) == 2

    # Test that original is unchanged
    assert len(ligandset) == 4


def test_filter_top_poses_single_top_pose():
    """this is a problematic case, and this should pass

    don't remove this test"""

    poses = LigandSet.from_sdf("tests/fixtures/docked-poses.sdf")

    assert len(poses) == 16, "Expected 16 poses in the initial pose set"

    poses = poses.filter_top_poses()

    assert len(poses) == 1, "Expected 1 poses in the filtered pose set"


def test_render_view_with_same_smiles():
    """Test that _render_view uses 'poses' when all ligands have the same SMILES"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create multiple ligands with the same SMILES (different poses)
    same_smiles = "CCO"
    ligand1 = Ligand.from_smiles(same_smiles, name="pose1")
    ligand2 = Ligand.from_smiles(same_smiles, name="pose2")
    ligand3 = Ligand.from_smiles(same_smiles, name="pose3")

    ligand_set = LigandSet(ligands=[ligand1, ligand2, ligand3])
    html = ligand_set._render_view()

    # Should use "poses" since all have the same SMILES
    assert "3 poses" in html
    # Check that "ligands" doesn't appear in the heading (it may appear in action hints)
    assert "3 ligands" not in html
    # Should show the actual SMILES string, not "1 unique SMILES"
    assert f"<strong>SMILES:</strong> {same_smiles}" in html
    assert "1 unique SMILES" not in html


def test_render_view_with_different_smiles():
    """Test that _render_view uses 'ligands' when ligands have different SMILES"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands with different SMILES
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")

    ligand_set = LigandSet(ligands=[ligand1, ligand2])
    html = ligand_set._render_view()

    # Should use "ligands" since they have different SMILES
    assert "2 ligands" in html
    assert "poses" not in html or html.count("poses") == 0
    # Should show count of unique SMILES, not the actual SMILES
    assert "<strong>2</strong> unique SMILES" in html


def test_render_view_single_pose():
    """Test that _render_view uses 'pose' (singular) for a single ligand with unique SMILES"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create a single ligand
    ligand = Ligand.from_smiles("CCO", name="ethanol")
    ligand_set = LigandSet(ligands=[ligand])
    html = ligand_set._render_view()

    # Should use "ligand" (singular) since there's only one
    assert "1 ligand" in html


def test_render_view_single_pose_same_smiles():
    """Test that _render_view uses 'ligand' for a single ligand even with same SMILES"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create a single ligand
    smiles = "CCO"
    ligand = Ligand.from_smiles(smiles, name="pose1")
    ligand_set = LigandSet(ligands=[ligand])
    html = ligand_set._render_view()

    # When there's only one ligand, should use "ligand" (not "pose")
    assert "1 ligand" in html
    # Should show the actual SMILES string, not "1 unique SMILES"
    assert f"<strong>SMILES:</strong> {smiles}" in html
    assert "1 unique SMILES" not in html


def test_render_view_shows_prepared_badge():
    """Test that _render_view shows 'prepared' badge when all ligands are prepared"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands and prepare them
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Not prepared yet - should not show badge
    html = ligand_set._render_view()
    assert (
        "<span class='badge text-bg-primary' style='font-variant: small-caps;'>PREPARED</span>"
        not in html
    )

    # Prepare all ligands
    ligand_set.prepare()
    html = ligand_set._render_view()

    # Should show prepared badge
    assert (
        "<span class='badge text-bg-primary' style='font-variant: small-caps;'>PREPARED</span>"
        in html
    )


def test_render_view_no_prepared_badge_when_partial():
    """Test that _render_view does not show 'prepared' badge when only some ligands are prepared"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Prepare only one ligand
    ligand1.prepare()
    html = ligand_set._render_view()

    # Should not show prepared badge since not all are prepared
    # Check that the badge with "PREPARED" text is not present
    assert (
        "<span class='badge text-bg-primary' style='font-variant: small-caps;'>PREPARED</span>"
        not in html
    )


def test_render_view_shows_prepare_hint_when_unprepared():
    """Test that _render_view shows prepare hint when any ligand is not prepared"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create unprepared ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    html = ligand_set._render_view()

    # Should show prepare hint (it's joined with commas, so check for the key part)
    assert "<code>.prepare()</code> to prepare ligands for docking" in html

    # Prepare all ligands
    ligand_set.prepare()
    html = ligand_set._render_view()

    # Should not show prepare hint when all are prepared
    assert "<code>.prepare()</code> to prepare ligands for docking" not in html


def test_render_view_shows_prepare_hint_when_partial():
    """Test that _render_view shows prepare hint when only some ligands are prepared"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Prepare only one ligand
    ligand1.prepare()
    html = ligand_set._render_view()

    # Should show prepare hint since not all are prepared
    assert "<code>.prepare()</code> to prepare ligands for docking" in html


def test_render_view_shows_not_protonated_badge(client: DeepOriginClient):
    """Test that _render_view shows 'NOT PROTONATED' badge when any ligand is not protonated"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands (none are protonated by default)
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Should show NOT PROTONATED badge since none are protonated
    html = ligand_set._render_view()
    assert (
        "<span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span>"
        in html
    )

    # Protonate all ligands
    for lig in ligand_set.ligands:
        Protonation(ligand=lig, ph=7.4, client=client).run()
    html = ligand_set._render_view()

    # Should not show NOT PROTONATED badge since all are protonated
    assert (
        "<span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span>"
        not in html
    )

    # Should show PROTONATED badge with pH value
    assert (
        "<span class='badge text-bg-success' style='font-variant: small-caps;'>PROTONATED (pH=7.4)</span>"
        in html
    )


def test_render_view_shows_not_protonated_badge_when_partial():
    """Test that _render_view shows 'NOT PROTONATED' badge when only some ligands are protonated"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Protonate only one ligand
    ligand1.protonated_at_ph = 7.4
    html = ligand_set._render_view()

    # Should show NOT PROTONATED badge since not all are protonated
    assert (
        "<span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span>"
        in html
    )


def test_render_view_shows_protonated_badge_with_ph(client: DeepOriginClient):
    """Test that _render_view shows 'PROTONATED (pH={ph})' badge when all ligands are protonated at the same pH"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Protonate all ligands at pH 7.4
    for lig in ligand_set.ligands:
        Protonation(ligand=lig, ph=7.4, client=client).run()
    html = ligand_set._render_view()

    # Should show PROTONATED badge with pH 7.4
    assert (
        "<span class='badge text-bg-success' style='font-variant: small-caps;'>PROTONATED (pH=7.4)</span>"
        in html
    )

    # Should not show NOT PROTONATED badge
    assert (
        "<span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span>"
        not in html
    )


def test_render_view_shows_protonated_badge_different_ph(
    client: DeepOriginClient,
):
    """Test that _render_view shows 'PROTONATED (pH={ph})' badge with different pH values"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Protonate all ligands at pH 11.4
    for lig in ligand_set.ligands:
        Protonation(ligand=lig, ph=11.4, client=client).run()
    html = ligand_set._render_view()

    # Should show PROTONATED badge with pH 11.4
    assert (
        "<span class='badge text-bg-success' style='font-variant: small-caps;'>PROTONATED (pH=11.4)</span>"
        in html
    )


def test_render_view_no_protonated_badge_when_different_ph(
    client: DeepOriginClient,
):
    """Test that _render_view does not show 'PROTONATED' badge when ligands are protonated at different pH values"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Protonate ligands at different pH values
    Protonation(ligand=ligand1, ph=7.4, client=client).run()
    Protonation(ligand=ligand2, ph=11.4, client=client).run()
    html = ligand_set._render_view()

    # Should not show PROTONATED badge since pH values differ
    assert (
        "<span class='badge text-bg-success' style='font-variant: small-caps;'>PROTONATED"
        not in html
    )

    # Should not show NOT PROTONATED badge either since all are protonated
    assert (
        "<span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span>"
        not in html
    )


def test_render_view_shows_2d_badge():
    """Test that _render_view shows '2D' badge when all ligands have only 2D structure"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands from SMILES (they have 2D coordinates, not 3D)
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    html = ligand_set._render_view()

    # Should show 2D badge since all ligands have only 2D structure
    assert (
        "<span class='badge text-bg-info' style='font-variant: small-caps;'>2D</span>"
        in html
    )

    # Should not show 3D badge
    assert (
        "<span class='badge text-bg-info' style='font-variant: small-caps;'>3D</span>"
        not in html
    )


def test_render_view_shows_3d_badge():
    """Test that _render_view shows '3D' badge when all ligands have 3D structure"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands and generate 3D coordinates
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Generate 3D coordinates for all ligands
    ligand_set.embed()
    html = ligand_set._render_view()

    # Should show 3D badge since all ligands have 3D structure
    assert (
        "<span class='badge text-bg-info' style='font-variant: small-caps;'>3D</span>"
        in html
    )

    # Should not show 2D badge
    assert (
        "<span class='badge text-bg-info' style='font-variant: small-caps;'>2D</span>"
        not in html
    )


def test_render_view_no_structure_badge_when_mixed():
    """Test that _render_view does not show structure badge when ligands have mixed 2D/3D structures"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")  # 2D
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")  # 2D
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Generate 3D coordinates for only one ligand
    ligand1.embed()
    html = ligand_set._render_view()

    # Should not show 2D badge since not all are 2D
    assert (
        "<span class='badge text-bg-info' style='font-variant: small-caps;'>2D</span>"
        not in html
    )

    # Should not show 3D badge since not all are 3D
    assert (
        "<span class='badge text-bg-info' style='font-variant: small-caps;'>3D</span>"
        not in html
    )


def test_ligand_set_sync_lv1():
    """Test syncing a LigandSet to the data platform using BRD ligands.

    Loads BRD ligands from BRD_DATA_DIR, syncs them, then syncs again to
    verify that existing ligands are found rather than re-created.
    """
    sdf_files = sorted(BRD_DATA_DIR.glob("*.sdf"))[:3]
    assert sdf_files, "No SDF files found in BRD_DATA_DIR"

    ligands = LigandSet.from_sdf_files([str(p) for p in sdf_files])
    ligands.sync()

    for lig in ligands:
        assert lig.id is not None, f"Expected id after sync for {lig.smiles}"

    first_ids = [lig.id for lig in ligands]

    # Sync again — same canonical SMILES should match existing records, not create new ones.
    ligands2 = LigandSet.from_sdf_files([str(p) for p in sdf_files])
    ligands2.sync()

    for lig in ligands2:
        assert lig.id is not None, f"Expected id after second sync for {lig.smiles}"

    second_ids = [lig.id for lig in ligands2]
    assert first_ids == second_ids, "IDs should match on re-sync"

    for lig in ligands2:
        assert lig.remote_path is not None, (
            f"Expected remote_path after re-sync (existing record) for {lig.smiles}"
        )


def test_ligand_set_sync_lazy_lv1():
    """Test that lazy=True skips ligands that already have an id."""
    smiles_list = ["CCO", "CCCO"]
    ligands = LigandSet.from_smiles(smiles_list)

    ligands.sync()
    original_ids = [lig.id for lig in ligands]
    assert all(i is not None for i in original_ids)

    # Set one id to None to simulate a "new" ligand
    ligands.ligands[0].id = None
    ligands.sync(lazy=True)

    # The first ligand should get an id back; the second should keep its original
    assert ligands.ligands[0].id is not None
    assert ligands.ligands[1].id == original_ids[1]


def test_ligand_set_sync_empty():
    """Test that syncing an empty LigandSet is a no-op."""
    empty = LigandSet(ligands=[])
    empty.sync()  # should not raise


def test_ligand_set_sync_rejects_unsupported_atoms():
    """sync() raises before platform calls if any ligand to sync has unsupported atoms."""
    ls = LigandSet(ligands=[Ligand.from_smiles("CCO"), Ligand.from_smiles("B")])
    with pytest.raises(DeepOriginException, match="Cannot sync ligand set"):
        ls.sync()


def test_ligand_set_sync_duplicate_smiles_lv1():
    """Syncing a LigandSet with duplicate canonical SMILES should succeed.

    The platform enforces a uniqueness constraint on
    ``(project_scope_key, canonical_smiles, variant_name_tag)``, so sync()
    must dedupe before calling ``batch_create_ligands``. All duplicates
    should end up pointing at the same platform record.
    """
    smiles = "CCO"
    ligands = LigandSet(ligands=[Ligand.from_smiles(smiles) for _ in range(3)])
    ligands.sync()

    ids = [lig.id for lig in ligands]
    assert all(i is not None for i in ids), "Every duplicate should receive an id"
    assert len(set(ids)) == 1, "All duplicates should share the same platform id"


def test_batch_create_ligands_lv1(client: DeepOriginClient):
    """Test batch creating ligands via LigandSet.sync()."""
    ligands = LigandSet.from_smiles(["CCO", "CCCO"])
    ligands.sync(client=client)

    for lig in ligands:
        assert lig.id is not None, f"Expected id after sync for {lig.smiles}"
        assert lig.canonical_smiles is not None, (
            f"Expected canonical_smiles for {lig.smiles}"
        )


def test_ligand_set_batches_none_is_single_chunk() -> None:
    ligands = [Ligand.from_smiles("C"), Ligand.from_smiles("CC")]
    ls = LigandSet(ligands=ligands)
    assert ls.batches(None) == [ligands]


def test_ligand_set_batches_chunk_sizes() -> None:
    ligands = [Ligand.from_smiles(s) for s in ["C", "CC", "CCC", "CCCC"]]
    ls = LigandSet(ligands=ligands)
    assert ls.batches(2) == [ligands[0:2], ligands[2:4]]
    assert ls.batches(3) == [ligands[0:3], ligands[3:4]]


@pytest.mark.parametrize("bad", [0, -1])
def test_ligand_set_batches_invalid_size_raises(bad: int) -> None:
    ls = LigandSet(ligands=[Ligand.from_smiles("C")])
    with pytest.raises(ValueError, match="batch_size"):
        ls.batches(bad)


def test_ligand_set_download_sets_local_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: DeepOriginClient
) -> None:
    """download() uses download_many once, maps paths to ligands, reloads mol from SDF."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "brd-all-poses.sdf"
    template = tmp_path / "one.sdf"
    sup = Chem.SDMolSupplier(str(fixture))
    mol0 = next(m for m in sup if m is not None)
    w = Chem.SDWriter(str(template))
    w.write(mol0)
    w.close()

    dm_kwargs: dict[str, object] = {}

    def _fake_download_many(*, files: object, **kwargs: object) -> dict[str, str]:
        dm_kwargs["files"] = files
        dm_kwargs.update(kwargs)
        keys = list(files.keys()) if isinstance(files, dict) else list(files)
        out: dict[str, str] = {}
        for k in keys:
            dest = tmp_path / str(k).replace("/", "__")
            shutil.copy(template, dest)
            out[k] = str(dest)
        return out

    monkeypatch.setattr(client.files, "download_many", _fake_download_many)

    a = Ligand.from_smiles("C")
    a.remote_path = "r/a.sdf"
    b = Ligand.from_smiles("CC")
    b.remote_path = "r/b.sdf"
    c = Ligand.from_smiles("CCC")
    c.remote_path = "r/a.sdf"
    d = Ligand.from_smiles("CCCC")
    d.local_path = "/already/local.sdf"
    d.remote_path = "r/ignored.sdf"
    e = Ligand.from_smiles("N")

    ls = LigandSet(ligands=[a, b, c, d, e])
    ls.download(client=client, lazy=False, max_workers=4)

    assert dm_kwargs["files"] == ["r/a.sdf", "r/b.sdf"]
    assert dm_kwargs.get("lazy") is False
    assert dm_kwargs.get("max_workers") == 4
    assert a.local_path == str(tmp_path / "r__a.sdf")
    assert b.local_path == str(tmp_path / "r__b.sdf")
    assert c.local_path == str(tmp_path / "r__a.sdf")
    assert d.local_path == "/already/local.sdf"
    assert e.local_path is None
    conf = a.mol.GetConformer()
    zs = [conf.GetAtomPosition(i).z for i in range(a.mol.GetNumAtoms())]
    assert max(abs(z) for z in zs) > 0.5


def test_ligand_set_from_json_remote_pose_requires_smiles() -> None:
    """from_json refuses remote-only poses without SMILES."""

    with pytest.raises(ValueError, match="smiles"):
        LigandSet.from_json([{"file_path": "tool-runs/x/pose.sdf"}])
