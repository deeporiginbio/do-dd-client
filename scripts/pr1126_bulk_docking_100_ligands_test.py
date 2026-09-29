#!/usr/bin/env -S uv run python
"""PR #1126: bulk docking on dev with ~100 ligands (env JSON fan-out, no seed pod)."""

import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from deeporigin.drug_discovery import BRD_DATA_DIR, Docking, LigandSet, Pocket, Protein
from deeporigin.platform import DeepOriginClient
from deeporigin.platform.constants import TERMINAL_STATES, is_success_status
from tests.integration_project import apply_integration_project, ensure_live_integration_project_id

TOOL_VERSION = "3.6.7"
BATCH_SIZE = 8
LIGAND_COUNT = 100
LIGANDS_CSV = (
    Path(__file__).resolve().parents[1]
    / "src/data/ligands/1000-ligands.csv"
)

POCKET_CENTER = [
    -13.400676727294922,
    -5.5482563972473145,
    14.189638137817383,
]
POCKET_BOX = 14.409664294429042


def load_smiles(path: Path, limit: int) -> list[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        smiles: list[str] = []
        for row in reader:
            value = (row.get("smiles") or "").strip()
            if value:
                smiles.append(value)
            if len(smiles) >= limit:
                break
    if len(smiles) < limit:
        msg = f"expected {limit} SMILES in {path}, found {len(smiles)}"
        raise ValueError(msg)
    return smiles


def aggregate_docked_ids(progress_report: dict[str, Any]) -> list[str]:
    docked: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        tool_progress = node.get("toolProgress") or {}
        docked.extend(tool_progress.get("docked") or [])
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(progress_report)
    return docked


def workflow_node_names(progress_report: dict[str, Any]) -> list[str]:
    names: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        name = node.get("displayName")
        if name:
            names.append(str(name))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(progress_report)
    return names


def main() -> int:
    smiles = load_smiles(LIGANDS_CSV, LIGAND_COUNT)
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
    ligands = LigandSet.from_smiles(smiles)

    docking = Docking(
        protein=protein,
        pocket=pocket,
        ligands=ligands,
        tool_version=TOOL_VERSION,
        effort=1,
        batch_size=BATCH_SIZE,
        client=client,
        name=f"PR1126 chunk test: {LIGAND_COUNT} ligands batchSize={BATCH_SIZE}",
    )

    print(f"ligands: {len(smiles)}, batchSize: {BATCH_SIZE}")
    docking.start()
    print("execution id:", docking.id, "status:", docking.status)

    docking.sync()
    if docking.status == "Quoted":
        docking.start()
        print("confirmed quote; status:", docking.status)

    timeout_s = 7200
    poll_s = 30
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
    node_names = workflow_node_names(progress_report)
    print("\n=== execution summary ===")
    print(json.dumps(
        {
            "executionId": raw.get("executionId"),
            "status": raw.get("status"),
            "tool": raw.get("tool"),
            "workflowStatus": progress_report.get("status"),
            "workflowNodes": node_names,
            "dockedCount": len(docked_ids),
            "metadata": raw.get("metadata"),
        },
        indent=2,
    ))

    if any("seed-bulk-input" in name for name in node_names):
        print("FAILED: seed-bulk-input node present (expected immediate fan-out)", file=sys.stderr)
        return 2

    if not is_success_status(docking.status):
        print("FAILED: terminal status", docking.status, file=sys.stderr)
        return 3

    if len(docked_ids) != LIGAND_COUNT:
        print(
            f"FAILED: expected {LIGAND_COUNT} docked ligand ids, got {len(docked_ids)}",
            file=sys.stderr,
        )
        return 4

    poses = docking.get_results()
    if len(poses) < LIGAND_COUNT:
        print(
            f"FAILED: expected at least {LIGAND_COUNT} poses, got {len(poses)}",
            file=sys.stderr,
        )
        return 5

    print(f"SUCCESS: {LIGAND_COUNT} ligands docked, no seed-bulk-input gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
