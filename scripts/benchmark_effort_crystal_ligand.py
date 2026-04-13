"""Benchmark docking effort levels on crystal ligand pose recovery.

Runs each effort level several times per PDB structure, records wall time,
execution id, and best-pose RMSD vs the crystal ligand, and appends each result
to a CSV as it completes. Re-running the script skips (pdb_id, effort, repeat)
triples already present in the CSV so you can resume after failures.
"""

from __future__ import annotations

import csv
from pathlib import Path
import time

from deeporigin.drug_discovery import Docking, LigandSet, Pocket, Protein

DEFAULT_CSV = Path(__file__).resolve().parent / "benchmark_effort_crystal_ligand.csv"
CSV_COLUMNS = ["pdb_id", "effort", "repeat", "execution_id", "time", "rmsd"]
PDB_IDS = ["1stp", "3ptb"]
EFFORT_LEVELS = [1, 2, 3, 4, 5]
REPEATS = 3


def _migrate_csv_schema_if_needed(csv_path: Path) -> None:
    """Rewrite legacy CSV files to the current schema (add ``pdb_id``, etc.)."""
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return
    with csv_path.open(newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return
    header = [h.strip() for h in rows[0]]
    if header and header[0].lower() == "pdb_id":
        return

    data_rows = rows[1:]
    new_rows: list[list[object]] = []
    legacy_pdb = "1eby"

    if header == ["effort", "time", "rmsd"]:
        per_effort: dict[int, int] = {}
        for row in data_rows:
            if len(row) < 3:
                continue
            e = int(row[0])
            per_effort[e] = per_effort.get(e, 0) + 1
            r = per_effort[e]
            new_rows.append([legacy_pdb, e, r, "", float(row[1]), float(row[2])])
    elif header == ["effort", "repeat", "execution_id", "time", "rmsd"]:
        for row in data_rows:
            if len(row) < 5:
                continue
            new_rows.append(
                [
                    legacy_pdb,
                    int(row[0]),
                    int(row[1]),
                    row[2],
                    float(row[3]),
                    float(row[4]),
                ]
            )
    else:
        return

    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        w.writerows(new_rows)
    print(
        f"Migrated {csv_path} to schema {CSV_COLUMNS} "
        f"(legacy rows use pdb_id={legacy_pdb!r}).",
        flush=True,
    )


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


def main() -> None:
    csv_path = DEFAULT_CSV
    _migrate_csv_schema_if_needed(csv_path)
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
        print("Loading structure…", flush=True)
        protein = Protein.from_pdb_id(pdb_id)
        ligand = protein.extract_ligand()
        pocket = Pocket.from_ligand(ligand)
        ligand.sync()
        protein.sync()
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

                pose_scores = [pose.properties["pose_score"] for pose in poses]
                idx = pose_scores.index(max(pose_scores))

                rmsd_matrix = LigandSet([poses[idx], ligand]).compute_rmsd()
                best_rmsd = float(rmsd_matrix[0][1])

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
