# Secondary Pharmacology

Score ligands against a secondary-pharmacology kinase panel with
[`SecondaryPharmacology`](../ref/secondary_pharma.md). See what's currently
in the panel with `SecondaryPharmacology.get_panel()`.

## Two execution modes on one class

`SecondaryPharmacology` wraps two mutually-exclusive scoring paths, selected
by `method` at construction:

`method` has no default — the two paths differ enough in cost and latency
that picking one should be deliberate.

- `method="ligand-ml"` — fast ML-based activity predictions across the panel,
  returned immediately. Use [`run()`](../ref/secondary_pharma.md).
- `method="docking"` — physically docks each ligand against the panel and
  scores the poses. Submitted as a background job — use
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
```

`get_results()` always returns a `pandas.DataFrame` regardless of method,
with a `method` column so a saved/exported result is still self-identifying.
On the docking path, allow a moment after `wait()`/`watch()` completes —
results land in the platform's data index rather than the immediate
response, the same as [`Docking.get_results()`](../ref/docking.md).

## Ligand-ML scoring

```{.python notest}
from deeporigin.drug_discovery import SecondaryPharmacology, Ligand

ligand = Ligand.from_smiles("CCO")
job = SecondaryPharmacology(ligands=[ligand], method="ligand-ml")
df = job.run()
```

`df` has one row per ligand × panel member: `uniprot_id`, `gene_name`, and
either `p_active` (classification) or `p_affinity` (regression, -log10 M).
`ligand_id` should always be populated, even if `ligand` wasn't registered with the
platform beforehand.

See what's currently in the panel with `SecondaryPharmacology.get_panel()`:

```{.python notest}
SecondaryPharmacology.get_panel()          # first 10 members, with a count hint
SecondaryPharmacology.get_panel(full=True) # every member
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

`job.plot()` renders a heatmap of ligand × target, colored by score.

## Docking

```{.python notest}
job = SecondaryPharmacology(ligands=[ligand], method="docking", effort=2)
job.start()
job.wait()               # or `await job.watch()` in a notebook
df = job.get_results()
```

`df` has one row per docked pose: `pose_score`, `binding_energy`, and
`file_path`. Use `pose_score`/`binding_energy` to read results -- viewing
the docked structure itself isn't supported yet.

`job.plot()` renders a heatmap colored by `binding_energy` (default) or
`metric="pose_score"`. Both use a fixed, opinionated color range you can
override with `clim=(low, high)` -- a value outside it still renders,
clipped to the nearest edge color.

Check for gaps with `job.get_undocked_ligands()` (ligands with zero docked
poses) or `job.get_missing_pairs()` (specific ligand × target cells missing).

Compare a ligand-ml run against a docking run on one heatmap with
`SecondaryPharmacology.plot_ml_vs_docking(ml_job, dock_job)` -- a
`staticmethod` since it needs both. `pose_score` is rescaled onto the same
0-1 scale as `p_active` for this comparison; override the rescaling window
with `pose_score_clim=(low, high)`. By default the heatmap shows every
ligand/target either run covered (`coverage="union"`, grey where only one
has data); pass `coverage="intersection"` to show only what both covered.

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

Don't know the execution id? List every past run, newest first:

```{.python notest}
runs = SecondaryPharmacology.list(status=["Completed"], project_id=client.project_id)
ml_runs = [r for r in runs if r.method == "ligand-ml"]
dock_runs = [r for r in runs if r.method == "docking"]
```

`project_id` restricts the list to your own project.

Reload a ligand-ml run and a docking run by id to compare them:

```{.python notest}
ml_job = SecondaryPharmacology.from_id(ml_runs[0].id)
dock_job = SecondaryPharmacology.from_id(dock_runs[0].id)
SecondaryPharmacology.plot_ml_vs_docking(ml_job, dock_job)
```
