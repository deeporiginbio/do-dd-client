# Secondary Pharmacology

Score ligands against a secondary-pharmacology kinase panel (currently
EGFR, BRAF, and SRC — the panel is expected to grow) with
[`SecondaryPharmacology`](../ref/secondary_pharma.md).

## Two execution modes on one class

`SecondaryPharmacology` wraps two mutually-exclusive scoring paths, selected
by `method` at construction:

- `method="ligand-ml"` — fast ML-based activity predictions across the panel,
  returned immediately. Use [`run()`](../ref/secondary_pharma.md).
- `method="docking"` (the default) — physically docks each ligand against the
  panel and scores the poses. Submitted as a background job — use
  [`start()`](../ref/secondary_pharma.md), then wait for it to finish.

`run()`, `start()`, and `watch()` are all available on every instance, but
only the one matching `method` works — the others raise immediately, telling
you which to call instead:

```mermaid
flowchart TD
    ctor["SecondaryPharmacology(method=...)"] --> choose{"Choose method"}
    choose -->|"&nbsp;method='ligand-ml'&nbsp;"| ml_run["run()<br/>fast ML prediction"]
    choose -->|"&nbsp;method='docking'&nbsp;"| dock_start["start()<br/>docking job"]

    ml_run -->|"&nbsp;completes&nbsp;"| ml_results["get_results()<br/>DataFrame, returned immediately"]
    ml_run -.->|"&nbsp;start() raises&nbsp;"| blocked(("ValueError"))

    dock_start -->|"&nbsp;submits&nbsp;"| dock_wait["wait() / watch()<br/>poll until complete"]
    dock_start -.->|"&nbsp;run() raises&nbsp;"| blocked
    dock_wait --> dock_results["get_results()<br/>DataFrame, from the platform"]
    dock_results --> dock_poses["get_poses()<br/>downloaded PoseSet"]
```

`get_results()` always returns a `pandas.DataFrame` regardless of method. On
the docking path, allow a moment after `wait()`/`watch()` completes — results
land in the platform's data index rather than the immediate response, the
same as [`Docking.get_results()`](../ref/docking.md).

## Ligand-ML scoring

```{.python notest}
from deeporigin.drug_discovery import SecondaryPharmacology, Ligand

ligand = Ligand.from_smiles("CCO")
job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml")
df = job.run()
```

`df` has one row per ligand × panel member, with `uniprot_id`, `gene_name`,
and exactly one of `p_active` (classification) or `p_affinity` (regression,
-log10 M) set per row.

See what's currently in the panel with `SecondaryPharmacology.panel()`:

```{.python notest}
SecondaryPharmacology.panel()
```

Restrict to a subset of the panel with `uniprots`:

```{.python notest}
job = SecondaryPharmacology(
    ligands=[ligand],
    method="ligand-ml",
    uniprots=["P00533"],  # EGFR only
)
```

Passing `self_test=True` instead of `ligands` scores a test ligand
against the full panel using the real model, for checking scoring end to end.

## Docking

```{.python notest}
job = SecondaryPharmacology(ligands=[ligand], method="docking", effort=2)
job.start()
job.wait()               # or `await job.watch()` in a notebook
df = job.get_results()
```

`df` has one row per docked pose, including `pose_score`, `binding_energy`,
and `file_path`. To load and download the poses as a
[`PoseSet`](../ref/pose.md) instead — for visualization, SDF export, or
feeding into a downstream tool like `ABFE`:

```{.python notest}
poses = job.get_poses()
```

Currently no batching is supported for the docking path (unlike `deeporigin.docking`'s `batchSize`)
and it runs as a single job with a fixed resource/time budget for the entire ligand set.

## Working with existing runs

```{.python notest}
from deeporigin.drug_discovery import SecondaryPharmacology

# By execution id:
job = SecondaryPharmacology.from_id("<executionId>")

# Or the most recently created SecondaryPharmacology run:
job = SecondaryPharmacology.from_last_run()

job.sync()
df = job.get_results()
```

`from_dto`/`from_id`/`from_last_run` restore `method`, `ligands`, `uniprots`,
`effort`, and `self_test` from the stored execution inputs. `uniprots` of a
loaded run cannot be changed — call `duplicate()` first to get an editable
copy, validated against the current panel.
