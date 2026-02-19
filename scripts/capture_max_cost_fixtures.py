"""Temporary script to capture max_cost docking fixtures for local tests."""

import json
import os
from pathlib import Path
import shutil

from deeporigin.drug_discovery import BRD_DATA_DIR, Pocket, Protein
from deeporigin.drug_discovery.structures import Ligand
from deeporigin.platform.client import DeepOriginClient
from deeporigin.utils.core import _ensure_do_folder, hash_dict
from deeporigin.utils.cost import Cost

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def copy_sdf_fixture(*, protein: Protein, ligand: Ligand, pocket: Pocket) -> None:
    """Copy a cached SDF file to the fixtures/files directory."""
    payload = {
        "protein_path": protein._remote_path,
        "ligand_smiles": ligand.smiles,
        "box_size": [20.0, 20.0, 20.0],
        "pocket_center": pocket.get_center().tolist(),
    }

    body_hash = hash_dict({"inputs": payload, "approveAmount": 100})
    fixture_json = (
        FIXTURES_DIR / "function-runs" / "deeporigin.docking" / f"{body_hash}.json"
    )
    print(f"  Fixture: {fixture_json.name} exists={fixture_json.exists()}")

    if not fixture_json.exists():
        return

    with open(fixture_json) as f:
        response_data = json.load(f)
    sdf_remote_path = response_data.get("functionOutputs", {}).get("sdf_path")
    if not sdf_remote_path:
        return

    sdf_fixture_path = FIXTURES_DIR / "files" / sdf_remote_path
    sdf_fixture_path.parent.mkdir(parents=True, exist_ok=True)

    cache_hash = hash_dict(payload)
    local_sdf = str(Path(_ensure_do_folder() / "docking") / f"{cache_hash}.sdf")
    if os.path.exists(local_sdf):
        shutil.copy2(local_sdf, sdf_fixture_path)
        print(f"  Copied SDF → {sdf_fixture_path.name}")
    else:
        print(f"  WARNING: local SDF not found at {local_sdf}")


def main() -> None:
    """Capture max_cost docking fixtures."""
    os.environ["DEEPORIGIN_ENV"] = "dev"
    client = DeepOriginClient.get(record=True, replace=True)

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    pocket = Pocket.from_pdb_file(
        FIXTURES_DIR / "pockets" / "brd_pocket_1.pdb", name="brd_pocket_1"
    )

    print("=== Single ligand, max_cost=Cost(100) ===")
    ligand = Ligand.from_smiles(
        "Fc1c(-c2cccc3ccccc23)ncc2c(N3C[C@H]4CC[C@@H](C3)N4)nc(OCC34CCCN3CCC4)nc12"
    )
    result = protein.dock(
        ligand=ligand,
        pocket=pocket,
        quote=False,
        use_cache=False,
        max_cost=Cost(100),
        client=client,
    )
    print(f"Result: {result}")
    copy_sdf_fixture(protein=protein, ligand=ligand, pocket=pocket)

    print("\n=== Multiple ligands, max_cost=Cost(100) → Cost(50) per ligand ===")
    ligands = [
        Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf"),
        Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf"),
    ]
    result = protein.dock(
        ligands=ligands,
        pocket=pocket,
        quote=False,
        use_cache=False,
        max_cost=Cost(100),
        client=client,
    )
    print(f"Result: {result}")

    for lig in ligands:
        payload = {
            "protein_path": protein._remote_path,
            "ligand_smiles": lig.smiles,
            "box_size": [20.0, 20.0, 20.0],
            "pocket_center": pocket.get_center().tolist(),
        }
        body_hash = hash_dict({"inputs": payload, "approveAmount": 50})
        fixture_json = (
            FIXTURES_DIR / "function-runs" / "deeporigin.docking" / f"{body_hash}.json"
        )
        print(f"  Fixture: {fixture_json.name} exists={fixture_json.exists()}")

        if fixture_json.exists():
            with open(fixture_json) as f:
                response_data = json.load(f)
            sdf_remote_path = response_data.get("functionOutputs", {}).get("sdf_path")
            if sdf_remote_path:
                sdf_fixture_path = FIXTURES_DIR / "files" / sdf_remote_path
                sdf_fixture_path.parent.mkdir(parents=True, exist_ok=True)
                cache_hash = hash_dict(payload)
                local_sdf = str(
                    Path(_ensure_do_folder() / "docking") / f"{cache_hash}.sdf"
                )
                if os.path.exists(local_sdf):
                    shutil.copy2(local_sdf, sdf_fixture_path)
                    print(f"  Copied SDF → {sdf_fixture_path.name}")


if __name__ == "__main__":
    main()
