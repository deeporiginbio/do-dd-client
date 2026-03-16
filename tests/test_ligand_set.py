import os

import pytest

from deeporigin.drug_discovery import DATA_DIR
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
        assert ligand.file_path in file_paths, (
            "Expected ligand.file_path to match source file"
        )
        assert os.path.exists(ligand.file_path), (
            "Expected ligand.file_path to exist on disk"
        )

    # Test with single file (should work the same as from_sdf)
    single_file_paths = [str(brd_file)]
    single_ligands = LigandSet.from_sdf_files(single_file_paths)
    assert len(single_ligands.ligands) == 8
    assert all(lig.file_path == str(brd_file) for lig in single_ligands.ligands), (
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
        with pytest.raises(DeepOriginException, match="missing 'POSE SCORE' property"):
            no_score_set.filter_top_poses(by_pose_score=True)

        # Restore original properties
        test_ligand1.properties = original_properties1
        test_ligand2.properties = original_properties2


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
    assert first_ligand.file_path is None

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


def test_show():
    """Test that we can show a LigandSet"""

    ligands = LigandSet.from_smiles(BRD_SMILES)
    ligands.show()


def test_from_dir():
    """Test that we can create a LigandSet from a directory"""

    ligands = LigandSet.from_dir(DATA_DIR / "brd")
    assert len(ligands) == 8

    for ligand in ligands:
        assert ligand.file_path is not None
        assert os.path.exists(ligand.file_path)


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


def test_render_view_shows_not_protonated_badge():
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
    ligand_set.protonate(ph=7.4, use_cache=False)
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
    ligand1.protonate(ph=7.4, use_cache=False)
    html = ligand_set._render_view()

    # Should show NOT PROTONATED badge since not all are protonated
    assert (
        "<span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span>"
        in html
    )


def test_render_view_shows_protonated_badge_with_ph():
    """Test that _render_view shows 'PROTONATED (pH={ph})' badge when all ligands are protonated at the same pH"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Protonate all ligands at pH 7.4
    ligand_set.protonate(ph=7.4, use_cache=False)
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


def test_render_view_shows_protonated_badge_different_ph():
    """Test that _render_view shows 'PROTONATED (pH={ph})' badge with different pH values"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Protonate all ligands at pH 11.4
    ligand_set.protonate(ph=11.4, use_cache=False)
    html = ligand_set._render_view()

    # Should show PROTONATED badge with pH 11.4
    assert (
        "<span class='badge text-bg-success' style='font-variant: small-caps;'>PROTONATED (pH=11.4)</span>"
        in html
    )


def test_render_view_no_protonated_badge_when_different_ph():
    """Test that _render_view does not show 'PROTONATED' badge when ligands are protonated at different pH values"""
    from deeporigin.drug_discovery.structures.ligand import LigandSet

    # Create ligands
    ligand1 = Ligand.from_smiles("CCO", name="ethanol")
    ligand2 = Ligand.from_smiles("CCCO", name="propanol")
    ligand_set = LigandSet(ligands=[ligand1, ligand2])

    # Protonate ligands at different pH values
    ligand1.protonate(ph=7.4, use_cache=False)
    ligand2.protonate(ph=11.4, use_cache=False)
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
    """Test syncing a LigandSet to the data platform.

    Creates ligands from SMILES, syncs them, then syncs again to verify
    that existing ligands are found rather than re-created.
    """
    smiles_list = [
        "CCO",
        "CCCO",
        "CCCCO",
    ]
    ligands = LigandSet.from_smiles(smiles_list)
    for i, lig in enumerate(ligands):
        lig.name = f"sync-test-{i}"

    ligands.sync()

    for lig in ligands:
        assert lig.id is not None, f"Expected id after sync for {lig.smiles}"

    first_ids = [lig.id for lig in ligands]

    # Sync again — same canonical SMILES should match existing records
    ligands2 = LigandSet.from_smiles(smiles_list)
    ligands2.sync()

    for lig in ligands2:
        assert lig.id is not None, f"Expected id after second sync for {lig.smiles}"

    second_ids = [lig.id for lig in ligands2]
    assert first_ids == second_ids, "IDs should match on re-sync"


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


def test_batch_create_ligands_lv1():
    """Test batch creating ligands via LigandSet.sync()."""
    client = DeepOriginClient()
    ligands = LigandSet.from_smiles(["CCO", "CCCO"])
    ligands.sync(client=client)

    for lig in ligands:
        assert lig.id is not None, f"Expected id after sync for {lig.smiles}"
        assert lig.canonical_smiles is not None, (
            f"Expected canonical_smiles for {lig.smiles}"
        )
