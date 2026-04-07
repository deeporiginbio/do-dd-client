"""Benchmark deeporigin.docking across ligands, effort levels, and repeats.

Results are written to the CSV after each docking run (header first, then one row
per completion with flush) so partial progress is preserved if the process stops
early.

If the output CSV already exists, completed (ligand_id, effort, repeat_number)
combinations are skipped so you can resume without redoing finished runs. Docking
failures are logged and do not stop the benchmark.
"""

from __future__ import annotations

import csv
from itertools import product
from pathlib import Path
import sys
import time
import traceback

from beartype import beartype
import pandas as pd

from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Docking,
    Ligand,
    LigandSet,
    Pocket,
    Protein,
)

DEFAULT_OUTPUT_CSV = Path(__file__).resolve().parent / "benchmark_docking_results.csv"

_RESULT_FIELDNAMES: tuple[str, ...] = (
    "execution_id",
    "ligand_id",
    "effort",
    "time_taken",
    "binding_energy",
    "repeat_number",
)


@beartype
def _best_binding_energy(poses: LigandSet) -> float | None:
    """Return the lowest binding energy (kcal/mol) among docked poses, if any.

    Args:
        poses: Docked poses from :meth:`~deeporigin.drug_discovery.docking.Docking.run`.

    Returns:
        Minimum binding energy across poses with a ``Binding Energy`` property,
        or ``None`` if none could be parsed.
    """
    values: list[float] = []
    for lig in poses:
        raw = lig.properties.get("Binding Energy")
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return min(values) if values else None


@beartype
def _load_completed_run_keys(csv_path: Path) -> set[tuple[str, int, int]]:
    """Return (ligand_id, effort, repeat_number) tuples already stored in the CSV.

    Args:
        csv_path: Path to an existing results CSV, or a missing path.

    Returns:
        Set of completed run keys; empty if the file is missing, empty, or unreadable.
    """
    if not csv_path.is_file() or csv_path.stat().st_size == 0:
        return set()
    completed: set[tuple[str, int, int]] = set()
    try:
        with csv_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames is None:
                return set()
            for row in reader:
                if not row:
                    continue
                try:
                    lig = row["ligand_id"]
                    eff = int(row["effort"])
                    rep = int(row["repeat_number"])
                except (KeyError, TypeError, ValueError):
                    continue
                completed.add((lig, eff, rep))
    except OSError:
        return set()
    return completed


def _run_one_docking(
    *,
    protein: Protein,
    pocket: Pocket,
    ligand: Ligand,
    effort: int,
    repeat_number: int,
) -> dict[str, float | int | str | None] | None:
    """Run a single docking job; log and return ``None`` on failure.

    Args:
        protein: Receptor structure.
        pocket: Docking box / pocket.
        ligand: Ligand to dock.
        effort: Effort level (1–5 in the benchmark grid).
        repeat_number: Repeat index for this ligand/effort pair.

    Returns:
        Result row dict for the CSV, or ``None`` if docking raised an exception.
    """
    print(
        f"[benchmark] start ligand_id={ligand.id!r} "
        f"effort={effort} repeat={repeat_number}",
        flush=True,
    )
    docking = Docking(
        protein=protein,
        pocket=pocket,
        ligand=ligand,
        effort=effort,
    )
    try:
        t0 = time.perf_counter()
        poses = docking.run()
        elapsed = time.perf_counter() - t0
        binding_energy = _best_binding_energy(poses)
    except Exception:
        print(
            f"[benchmark] ERROR ligand_id={ligand.id!r} "
            f"effort={effort} repeat={repeat_number}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        return None

    print(
        f"[benchmark] done  ligand_id={ligand.id!r} "
        f"effort={effort} repeat={repeat_number} "
        f"time_taken={elapsed:.3f}s execution_id={docking.id!r} "
        f"binding_energy={binding_energy!r}",
        flush=True,
    )
    return {
        "execution_id": docking.id,
        "ligand_id": ligand.id,
        "effort": effort,
        "time_taken": elapsed,
        "binding_energy": binding_energy,
        "repeat_number": repeat_number,
    }


def run_benchmark(*, output_csv: Path | None = None) -> pd.DataFrame:
    """Run all ligand × effort × repeat docking jobs and save results to CSV.

    Skips runs whose (ligand_id, effort, repeat_number) already appear in the CSV
    so interrupted benchmarks can be resumed. Per-run exceptions are reported and
    skipped so one failure does not abort the whole benchmark.

    Args:
        output_csv: CSV path. Defaults to :data:`DEFAULT_OUTPUT_CSV`.

    Returns:
        DataFrame with execution id, ligand id, effort, time, binding energy, repeat
        (full file contents after the run).
    """
    out_path = output_csv if output_csv is not None else DEFAULT_OUTPUT_CSV

    completed_keys = _load_completed_run_keys(out_path)
    if completed_keys:
        print(
            f"[benchmark] resuming: {len(completed_keys)} run(s) already in "
            f"{out_path!s}",
            flush=True,
        )

    protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
    protein.remove_water()
    protein.sync()

    ligands = LigandSet.from_dir(BRD_DATA_DIR)
    ligands.sync()

    pockets = Pocket.from_result(protein_id=protein.id)
    pocket = pockets[0]

    rows: list[dict[str, float | int | str | None]] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)

    file_exists_nonempty = out_path.is_file() and out_path.stat().st_size > 0
    open_mode = "a" if file_exists_nonempty else "w"

    with out_path.open(open_mode, newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(_RESULT_FIELDNAMES))
        if open_mode == "w":
            writer.writeheader()
            csv_file.flush()

        for ligand, effort, repeat_number in product(
            ligands,
            range(1, 6),
            range(1, 4),
        ):
            run_key = (ligand.id, effort, repeat_number)
            if run_key in completed_keys:
                print(
                    f"[benchmark] skip (already in CSV) ligand_id={ligand.id!r} "
                    f"effort={effort} repeat={repeat_number}",
                    flush=True,
                )
                continue

            row = _run_one_docking(
                protein=protein,
                pocket=pocket,
                ligand=ligand,
                effort=effort,
                repeat_number=repeat_number,
            )
            if row is None:
                continue

            rows.append(row)
            writer.writerow(row)
            csv_file.flush()
            completed_keys.add(run_key)

    return pd.read_csv(out_path)


if __name__ == "__main__":
    run_benchmark()
