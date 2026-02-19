"""Temporary script to capture docking API responses as fixtures.

Runs the same docking call as test_docking_lv2 against dev with record=True,
then copies the downloaded SDF file into the mock server's fixtures/files directory.
"""

import os
from pathlib import Path
import shutil

from deeporigin.drug_discovery import BRD_DATA_DIR, Ligand, Pocket, Protein
from deeporigin.platform.client import DeepOriginClient


def main():
    """Capture docking fixtures from the dev environment."""
    os.environ["DEEPORIGIN_ENV"] = "dev"

    FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

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
        quote=False,
        use_cache=False,
    )

    print(f"Result: {result}")
    print(f"Result data: {result.data}")
    print(f"Result cost: {result.cost}")

    from deeporigin.utils.core import hash_dict

    payload = {
        "protein_path": protein._remote_path,
        "ligand_smiles": ligand.smiles,
        "box_size": [20.0, 20.0, 20.0],
        "pocket_center": pocket.get_center().tolist(),
    }
    cache_hash = hash_dict(payload)
    print(f"Payload: {payload}")
    print(f"Cache hash: {cache_hash}")

    normalized_body = {"inputs": payload}
    body_hash = hash_dict(normalized_body)
    print(f"Body hash (for fixture lookup): {body_hash}")

    fixture_json = (
        FIXTURES_DIR / "function-runs" / "deeporigin.docking" / f"{body_hash}.json"
    )
    print(f"Fixture JSON exists: {fixture_json.exists()}")
    print(f"Fixture JSON path: {fixture_json}")

    import json

    if fixture_json.exists():
        with open(fixture_json) as f:
            response_data = json.load(f)
        sdf_remote_path = response_data.get("functionOutputs", {}).get("sdf_path")
        if sdf_remote_path:
            print(f"SDF remote path from fixture: {sdf_remote_path}")
            sdf_fixture_path = FIXTURES_DIR / "files" / sdf_remote_path
            sdf_fixture_path.parent.mkdir(parents=True, exist_ok=True)

            from deeporigin.utils.core import _ensure_do_folder

            local_sdf = str(Path(_ensure_do_folder() / "docking") / f"{cache_hash}.sdf")
            print(f"Local SDF path: {local_sdf}")
            if os.path.exists(local_sdf):
                shutil.copy2(local_sdf, sdf_fixture_path)
                print(f"Copied SDF to fixture: {sdf_fixture_path}")
            else:
                print(f"Local SDF not found at {local_sdf}")
    else:
        print("Fixture JSON was NOT created by record mode")


if __name__ == "__main__":
    main()
