"""Benchmark docking effort levels on crystal ligand pose recovery.

Each PDB structure is prepared with Protein Prep (``find_pockets=
"from-crystal-ligand"``), which extracts the crystal ligand and returns its
pocket. The crystal ligand is then re-docked into that pocket on the prepared
protein. Runs each effort level several times per PDB structure, records wall
time, execution id, and best-pose RMSD vs the crystal pose, and appends each
result to a CSV as it completes. Re-running the script skips (pdb_id, effort,
repeat) triples already present in the CSV so you can resume after failures.

Results go to ``benchmark_effort_crystal_ligand_prepared.csv``. Earlier versions
of this script docked into the raw PDB with a locally built pocket and wrote
``benchmark_effort_crystal_ligand.csv``; that file is never read or appended to,
so the two protocols cannot mix.
"""

from __future__ import annotations

import csv
from pathlib import Path
import time

from deeporigin.drug_discovery import (
    Docking,
    Ligand,
    Pocket,
    Protein,
    ProteinPrep,
    chemistry,
)
from deeporigin.drug_discovery.structures.pose import Pose

DEFAULT_CSV = (
    Path(__file__).resolve().parent / "benchmark_effort_crystal_ligand_prepared.csv"
)
CSV_COLUMNS = ["pdb_id", "effort", "repeat", "execution_id", "time", "rmsd"]
PDB_IDS = ["1stp", "3ptb"]
EFFORT_LEVELS = [1, 2, 3, 4, 5]
REPEATS = 3


def load_completed_runs(csv_path: Path) -> set[tuple[str, int, int]]:
    """Return (pdb_id, effort, repeat) triples already recorded in ``csv_path``."""
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return set()
    completed: set[tuple[str, int, int]] = set()
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return set()
        fields = [h.strip() if h else "" for h in reader.fieldnames]
        if not all(x in fields for x in ("pdb_id", "effort", "repeat")):
            return set()
        for row in reader:
            if not row:
                continue
            try:
                pdb_raw = row.get("pdb_id", "")
                e_raw = row.get("effort", "")
                r_raw = row.get("repeat", "")
                if (
                    pdb_raw is None
                    or e_raw is None
                    or r_raw is None
                    or pdb_raw == ""
                    or e_raw == ""
                    or r_raw == ""
                ):
                    continue
                pdb_norm = str(pdb_raw).strip().lower()
                completed.add((pdb_norm, int(e_raw), int(r_raw)))
            except (TypeError, ValueError):
                continue
    return completed


def write_benchmark_row(
    csv_path: Path,
    pdb_id: str,
    effort: int,
    repeat: int,
    execution_id: str,
    elapsed_s: float,
    rmsd: float,
) -> None:
    """Append one benchmark row to ``csv_path``, writing the header if the file is new."""
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(CSV_COLUMNS)
        writer.writerow([pdb_id, effort, repeat, execution_id, elapsed_s, rmsd])


def prepare_crystal_pocket(pdb_id: str) -> tuple[Protein, Pocket, Ligand, Pose]:
    """Prepare ``pdb_id`` and return its crystal pocket, ligand, and pose.

    Uses the first ligand that Protein Prep recommends extracting.

    Returns:
        The prepared protein, the crystal-ligand pocket on it, the extracted
        ligand, and its crystal pose (downloaded).
    """
    protein = Protein.from_pdb_id(pdb_id)
    protein.sync()
    prep = ProteinPrep(protein)
    recommendation = prep.recommend()
    extracted = recommendation[
        (recommendation["kind"] == "ligand") & (recommendation["decision"] == "extract")
    ]
    if extracted.empty:
        raise RuntimeError(
            f"Protein Prep found no crystal ligand to extract in {pdb_id}"
        )
    component_id = str(extracted["id"].iloc[0])
    prep.skip(decision="review")
    prep.find_pockets = "from-crystal-ligand"
    prep.component_id = component_id
    prepared = prep.run()
    if prepared is None:
        raise RuntimeError(f"Protein Prep returned no prepared protein for {pdb_id}")

    pockets = prep.get_pockets() or []
    pocket = next((p for p in pockets if p.component_id == component_id), None)
    if pocket is None or pocket.ligand_id is None:
        raise RuntimeError(f"No crystal pocket for {component_id} in {pdb_id}")
    crystal_poses = prep.get_crystal_poses()
    crystal_pose = next(
        (
            p
            for p in (crystal_poses.poses if crystal_poses is not None else [])
            if p.component_id == component_id
        ),
        None,
    )
    if crystal_pose is None:
        raise RuntimeError(f"No crystal pose for {component_id} in {pdb_id}")
    crystal_pose.download()
    ligand = Ligand.from_id(pocket.ligand_id)
    return prepared, pocket, ligand, crystal_pose


def main() -> None:
    csv_path = DEFAULT_CSV
    completed = load_completed_runs(csv_path)

    pdb_ids_norm = [p.strip().lower() for p in PDB_IDS]
    total_runs = len(pdb_ids_norm) * len(EFFORT_LEVELS) * REPEATS
    planned_keys = {
        (p, e, r)
        for p in pdb_ids_norm
        for e in EFFORT_LEVELS
        for r in range(1, REPEATS + 1)
    }
    done_count = len(planned_keys & completed)

    print(
        f"Benchmark: PDBs {PDB_IDS}, efforts {EFFORT_LEVELS}, {REPEATS} repeats each."
    )
    print(f"Total runs: {total_runs}. Already completed (in CSV): {done_count}.")
    print(f"Results append to {csv_path}", flush=True)

    run_index = 0
    for pdb_id in PDB_IDS:
        pdb_key = pdb_id.strip().lower()
        print(f"\n========== PDB {pdb_id.upper()} ==========", flush=True)
        print("Preparing structure and crystal pocket…", flush=True)
        protein, pocket, ligand, crystal_pose = prepare_crystal_pocket(pdb_id)
        print("Structure ready. Docking loop for this PDB.\n", flush=True)

        docking = Docking(protein=protein, ligand=ligand, pocket=pocket)
        for effort in EFFORT_LEVELS:
            docking.effort = effort
            print(
                f"--- {pdb_id.upper()} effort {effort} (of {max(EFFORT_LEVELS)}) ---",
                flush=True,
            )
            for repeat in range(1, REPEATS + 1):
                run_index += 1
                if (pdb_key, effort, repeat) in completed:
                    print(
                        f"[{run_index}/{total_runs}] {pdb_key} effort={effort} "
                        f"repeat={repeat}/{REPEATS} — skip (already in CSV).",
                        flush=True,
                    )
                    continue

                print(
                    f"[{run_index}/{total_runs}] {pdb_key} effort={effort} "
                    f"repeat={repeat}/{REPEATS} — docking…",
                    flush=True,
                )
                start_time = time.perf_counter()
                poses = docking.run()
                elapsed_s = time.perf_counter() - start_time
                if poses is None:
                    raise RuntimeError("Docking returned no poses (quoted or failed)")

                # run() → get_results() is metadata-only; hydrate SDFs before RMSD.
                poses.download(client=docking.client, lazy=True)

                pose_scores = [
                    pose.pose_score
                    for pose in poses.poses
                    if pose.pose_score is not None
                ]
                if not pose_scores:
                    raise RuntimeError("Docking returned no scored poses")
                best_pose = max(
                    poses.poses,
                    key=lambda p: (
                        p.pose_score if p.pose_score is not None else float("-inf")
                    ),
                )
                if best_pose.mol is None:
                    raise RuntimeError(
                        "Best pose has no molecule after download; cannot compute RMSD"
                    )
                best_rmsd_val = chemistry.pose_rmsd(best_pose.mol, crystal_pose.mol)
                best_rmsd = (
                    float(best_rmsd_val) if best_rmsd_val is not None else float("nan")
                )

                exec_id = docking.id or ""
                write_benchmark_row(
                    csv_path, pdb_key, effort, repeat, exec_id, elapsed_s, best_rmsd
                )
                print(
                    f"[{run_index}/{total_runs}] done: {elapsed_s:.2f}s, "
                    f"execution_id={exec_id!r}, "
                    f"best-pose RMSD vs crystal = {best_rmsd:.4f} Å (row appended)",
                    flush=True,
                )
    print(f"\nFinished benchmark loop. CSV: {csv_path}", flush=True)


if __name__ == "__main__":
    main()
