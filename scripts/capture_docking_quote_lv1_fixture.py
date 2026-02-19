"""Temporary script to capture the single-ligand quote=True docking fixture."""

import os
from pathlib import Path

from deeporigin.drug_discovery import BRD_DATA_DIR, Pocket, Protein
from deeporigin.drug_discovery.structures import Ligand
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.core import hash_dict

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def main() -> None:
    """Capture the fixture."""
    os.environ["DEEPORIGIN_ENV"] = "dev"
    client = DeepOriginClient.get(record=True, replace=True)

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
        client=client,
    )

    print(f"Result: {result}")
    print(f"Estimate: {result.estimate}")

    payload = {
        "protein_path": protein._remote_path,
        "ligand_smiles": ligand.smiles,
        "box_size": [20.0, 20.0, 20.0],
        "pocket_center": pocket.get_center().tolist(),
    }
    body_hash = hash_dict({"inputs": payload, "approveAmount": 0})
    fixture = (
        FIXTURES_DIR / "function-runs" / "deeporigin.docking" / f"{body_hash}.json"
    )
    print(f"Fixture: {fixture.name} exists={fixture.exists()}")


if __name__ == "__main__":
    main()
