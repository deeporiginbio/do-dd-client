#!/usr/bin/env -S uv run python
"""PR #1126 validation: bulk docking with batchSize=4 and 8 ligands on dev."""

import json
import sys
import time
from typing import Any

from deeporigin.drug_discovery import BRD_DATA_DIR, Docking, LigandSet, Pocket, Protein
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import TERMINAL_STATES, is_success_status
from tests.integration_project import apply_integration_project, ensure_live_integration_project_id

TOOL_VERSION = "3.6.7"
BATCH_SIZE = 4

SMILES = [
    "COCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "CCCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "C=CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "C/C=C/Cn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "CCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "CCCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "C=CCn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O",
    "CN(C)C(=O)c1cccc(-c2cn(C)c(=O)c3[nH]ccc23)c1",
]

POCKET_CENTER = [
    -13.400676727294922,
    -5.5482563972473145,
    14.189638137817383,
]
POCKET_BOX = 14.409664294429042


def aggregate_docked_ids(progress_report: dict[str, Any]) -> list[str]:
    """Collect ligand ids from nested Argo workflow toolProgress nodes."""

    docked: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        tool_progress = node.get("toolProgress") or {}
        docked.extend(tool_progress.get("docked") or [])
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(progress_report)
    return docked


def main() -> int:
    ensure_live_integration_project_id()
    client = DeepOriginClient.from_disk(env="dev")
    apply_integration_project(client, "dev")
    if not client.tools.exists(
        tool_key="deeporigin.docking", tool_version=TOOL_VERSION
    ):
        print(f"Tool deeporigin.docking@{TOOL_VERSION} not registered on dev", file=sys.stderr)
        return 1

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    protein.sync(client=client, remote_path="testing/brd.pdb")

    pocket = Pocket(
        center=POCKET_CENTER,
        box_size_x=POCKET_BOX,
        box_size_y=POCKET_BOX,
        box_size_z=POCKET_BOX,
    )
    ligands = LigandSet.from_smiles(SMILES)

    docking = Docking(
        protein=protein,
        pocket=pocket,
        ligands=ligands,
        tool_version=TOOL_VERSION,
        effort=1,
        batch_size=BATCH_SIZE,
        client=client,
        name="PR1126 chunk test: 8 ligands batchSize=4",
    )

    payload = docking._build_docking_create_payload(sync=False, approve_amount=None)
    print("create payload batchSize:", payload.get("batchSize"))
    print("ligand count:", len(ligands))

    docking.start()
    print("execution id:", docking.id, "status:", docking.status)

    docking.sync()
    if docking.status == "Quoted":
        docking.start()
        print("confirmed quote; status:", docking.status)

    timeout_s = 3600
    poll_s = 20
    elapsed = 0
    while elapsed < timeout_s:
        docking.sync()
        pr = docking.progress or {}
        docked_ids = aggregate_docked_ids(pr)
        print(
            f"[{elapsed}s] status={docking.status!r} workflow={pr.get('status')!r} "
            f"docked={len(docked_ids)}"
        )
        if docking.status in TERMINAL_STATES:
            break
        time.sleep(poll_s)
        elapsed += poll_s

    raw = client.executions.get(docking.id)
    progress_report = raw.get("progressReport") or {}
    docked_ids = aggregate_docked_ids(progress_report)
    print("\n=== execution summary ===")
    print(json.dumps(
        {
            "executionId": raw.get("executionId"),
            "status": raw.get("status"),
            "tool": raw.get("tool"),
            "workflowStatus": progress_report.get("status"),
            "dockedLigandIds": docked_ids,
            "metadata": raw.get("metadata"),
        },
        indent=2,
    ))

    if not is_success_status(docking.status):
        print("FAILED: terminal status", docking.status, file=sys.stderr)
        return 2

    if len(docked_ids) != len(SMILES):
        print(
            f"FAILED: expected {len(SMILES)} docked ligand ids in workflow progress, "
            f"got {len(docked_ids)}",
            file=sys.stderr,
        )
        return 3

    poses = docking.get_results()
    if len(poses) < len(SMILES):
        print(
            f"FAILED: expected at least {len(SMILES)} poses from get_results(), got {len(poses)}",
            file=sys.stderr,
        )
        return 4

    print("SUCCESS: immediate fan-out; all ligands docked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
