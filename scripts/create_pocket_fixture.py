"""One-off script to create a pocket fixture for testing.

This script runs against dev to get a pocket and saves it to tests/fixtures.
"""

import os
from pathlib import Path
import shutil

from deeporigin.drug_discovery import BRD_DATA_DIR, Pocket, Protein
from deeporigin.platform.client import DeepOriginClient


def main():
    """Create a pocket fixture by running pocket finder against dev."""
    # Set environment to dev
    os.environ["DEEPORIGIN_ENV"] = "dev"

    # Load protein
    print("Loading protein...")
    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()

    # Get client
    client = DeepOriginClient.get()
    print(f"Using environment: {client.env}")

    # Find pockets against dev
    print("Finding pockets against dev (this may take a while)...")
    pockets = protein.find_pockets(pocket_count=1, use_cache=False)

    if not pockets:
        raise ValueError("No pockets found!")

    pocket = pockets[0]
    print(f"Found pocket: {pocket.name}")

    # Get the fixture directory
    fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures"
    pocket_fixture_dir = fixtures_dir / "pockets"
    pocket_fixture_dir.mkdir(parents=True, exist_ok=True)

    # Copy the pocket PDB file to fixtures
    if pocket.file_path is None:
        raise ValueError("Pocket file_path is None!")

    fixture_pdb_path = pocket_fixture_dir / "brd_pocket_1.pdb"
    print(f"Copying pocket PDB file to {fixture_pdb_path}...")
    shutil.copy2(pocket.file_path, fixture_pdb_path)

    # Verify the pocket can be loaded from the fixture
    print("Verifying fixture can be loaded...")
    loaded_pocket = Pocket.from_pdb_file(fixture_pdb_path, name="brd_pocket_1")
    center = loaded_pocket.get_center()
    print(f"Pocket center: {center.tolist()}")
    print(f"Fixture created successfully at: {fixture_pdb_path}")


if __name__ == "__main__":
    main()
