#!/usr/bin/env python3
"""Verify ABFE solvation trajectory topology resolution for one execution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from deeporigin.drug_discovery.abfe import (
    ABFE,
    _abfe_local_trajectory_topology_path,
    _abfe_prepare_trajectory_topology,
    _abfe_remote_trajectory_topology_path,
    _abfe_xtc_atom_count,
)
from deeporigin.platform.client import DeepOriginClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "execution_id",
        default="2ea8d564-4dee-4aef-89f0-a8b8b7bbcff4",
        nargs="?",
    )
    parser.add_argument("--window", type=int, default=2)
    args = parser.parse_args()

    client = DeepOriginClient()
    client.project_id = None

    abfe = ABFE.from_id(args.execution_id, client=client)
    print(f"execution_id={abfe.id} status={abfe.status} tool_key={abfe.tool_key}")

    data = abfe._fetch_merged_abfe_result_data()
    print("merged keys:", sorted(data.keys()))
    print(
        "solute_pdb_file_path:",
        data.get("solute_pdb_file_path"),
    )
    print(
        "solvation_xml_ligand_file_path:",
        data.get("solvation_xml_ligand_file_path"),
    )

    step = "solvation"
    remote_pdb = _abfe_remote_trajectory_topology_path(data, step=step)
    print(f"remote topology for {step}: {remote_pdb}")

    blocks = data.get("solvation_analysis")
    if not isinstance(blocks, list) or not blocks:
        print("ERROR: no solvation_analysis", file=sys.stderr)
        return 1
    traj = blocks[0].get("trajectories") or {}
    window_key = f"window_{args.window}"
    remote_xtc = traj.get(window_key)
    if not remote_xtc:
        print(f"ERROR: missing {window_key} in trajectories", file=sys.stderr)
        return 1
    print(f"remote xtc: {remote_xtc}")

    local_pdb = client.files.download(remote_pdb, lazy=True)
    print(f"downloaded topology -> {local_pdb} (suffix={Path(local_pdb).suffix})")
    local_pdb = _abfe_local_trajectory_topology_path(local_pdb, step=step)
    print(f"after local topology resolve -> {local_pdb}")

    local_xtc = client.files.download(remote_xtc, lazy=True)
    print(f"downloaded xtc -> {local_xtc}")
    print(f"xtc atom count: {_abfe_xtc_atom_count(local_xtc)}")

    pdb_lines = Path(local_pdb).read_text(encoding="utf-8").splitlines()
    coord = [ln for ln in pdb_lines if ln.startswith(("ATOM  ", "HETATM"))]
    print(f"pdb coordinate records before prepare: {len(coord)}")

    try:
        prepared = _abfe_prepare_trajectory_topology(
            pdb_path=local_pdb,
            trajectory_path=local_xtc,
            step=step,
        )
        print(f"prepare_trajectory_topology OK -> {prepared}")
    except Exception as exc:
        print(f"prepare_trajectory_topology FAILED: {exc}", file=sys.stderr)
        return 1

    try:
        abfe.show_trajectory(step="solvation", window=args.window, show_progress=False)
        print("show_trajectory OK")
    except Exception as exc:
        print(f"show_trajectory FAILED: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
