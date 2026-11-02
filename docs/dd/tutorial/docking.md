# Docking

This document describes how to [dock :octicons-link-external-16:](https://en.wikipedia.org/wiki/Docking_(molecular)) ligands to a protein using Deep Origin tools.

`Docking` always takes an explicit `pocket`. This tutorial covers the common case
where the binding site is known from a co-crystallized ligand:

1. Prepare the protein with [Protein Prep](../tools/proteinprep.md) and `find_pockets="from-crystal-ligand"`.
2. Get the prepared `Protein` and the crystal `Pocket` with `get_results()` and `get_pockets()`.
3. Inspect the pocket and its docking box.
4. Pass the pocket to `Docking`.

If your target has no known binding site, see
[Docking into a novel pocket](#docking-into-a-novel-pocket) below.

!!! tip "Notebook"
    The `docs/notebooks/clean/docking-crystal-pocket.ipynb` notebook runs this
    flow end to end.

## Prerequisites

First, import the necessary classes:

```{.python notest}
from deeporigin.drug_discovery import (
    Docking,
    Ligand,
    Protein,
    ProteinPrep,
)
```

## Load a holo structure

[1EBY :octicons-link-external-16:](https://www.rcsb.org/structure/1EBY) is
HIV-1 protease bound to the inhibitor `BEB`. Load it and register it on the
platform. Protein Prep handles the ligand, waters, and protonation, so there is
no need to edit the structure first:

```{.python notest}
protein = Protein.from_pdb_id("1EBY")
protein.sync()
```

We can view the protein and its crystal ligand:

```{.python notest}
protein.show()
```

<iframe
    src="../../images/1eby.html"
    width="100%"
    height="630"
    style="border:none;"
    title="Protein visualization"
></iframe>

## Prepare the protein and request the crystal pocket

Create a [`ProteinPrep`](../ref/protein_prep.md) with
`find_pockets="from-crystal-ligand"`. `component_id` names the crystal ligand
by its Selection id, which `recommend()` reports:

```{.python notest}
prep = ProteinPrep(
    protein,
    find_pockets="from-crystal-ligand",
    component_id="ligand:B:BEB:501:",
)
recommendation = prep.recommend()
recommendation[recommendation["kind"] != "water"][["id", "kind", "label", "decision"]]
```

!!! success "Expected Output"
    ```
                       id    kind      label decision
    0             chain:A   chain    chain A     keep
    1             chain:B   chain    chain B     keep
    42  ligand:B:BEB:501:  ligand  BEB B 501  extract
    ```

`BEB` is marked `extract`: preparation removes it from the receptor, registers
it as a `Ligand`, and keeps its crystal coordinates as a pose. Resolve any
`review` decisions (see [ProteinPrep](../tools/proteinprep.md#recommend-and-review)),
then prepare:

```{.python notest}
prepared = prep.run()
```

`run()` blocks until preparation completes and returns the prepared
[`Protein`](../ref/protein.md). It is a new platform protein; the input
`protein` is unchanged.

!!! tip "Choosing the crystal ligand"
    When the Selection extracts a ligand and you do not set `find_pockets`,
    Protein Prep requests a crystal-ligand pocket anyway. Set `find_pockets`
    and `component_id` explicitly when the structure has more than one ligand,
    or to make the intent clear. Use `component_id` (not `ligand_id`) for a
    ligand you extract: `ligand_id` must name a residue that is still in the
    structure, so the run fails once that ligand is extracted.

## Get the crystal pocket

`get_pockets()` returns the pockets from the same run:

```{.python notest}
pockets = prep.get_pockets()
pocket = pockets[0]
pocket
```

!!! success "Expected Output"
    ```
    Pocket:
    ╭──────────────────────┬────────────────────────────────╮
    │ Name                 │ Pocket from crystal ligand BEB │
    ├──────────────────────┼────────────────────────────────┤
    │ Protein ID           │ 0D2W6ZSJ28VCT                  │
    ├──────────────────────┼────────────────────────────────┤
    │ Origin               │ from-crystal-ligand            │
    ├──────────────────────┼────────────────────────────────┤
    │ Ligand ID            │ 0CNGVEX3A8RCJ                  │
    ├──────────────────────┼────────────────────────────────┤
    │ Ligand name          │ ligand:B:BEB:501:              │
    ├──────────────────────┼────────────────────────────────┤
    │ Component ID         │ ligand:B:BEB:501:              │
    ├──────────────────────┼────────────────────────────────┤
    │ Color                │ red                            │
    ├──────────────────────┼────────────────────────────────┤
    │ Center               │ (13.20, 23.04, 5.56)           │
    ├──────────────────────┼────────────────────────────────┤
    │ Box size (lab frame) │ 20.34 × 19.29 × 17.08 Å        │
    ├──────────────────────┼────────────────────────────────┤
    │ Docking box size     │ 23.23 × 17.05 × 13.74 Å        │
    ├──────────────────────┼────────────────────────────────┤
    │ rotation_deg         │ (-63.78, 35.55, 17.37)         │
    ├──────────────────────┼────────────────────────────────┤
    │ Pocket count         │ 1                              │
    ╰──────────────────────┴────────────────────────────────╯
    ```

The pocket belongs to the prepared protein (`pocket.protein_id == prepared.id`)
and records which crystal ligand it came from (`origin`, `component_id`,
`ligand_id`). `get_pockets()` returns `None` while outputs are still pending.

### Inspect the pocket

Show the pocket on the prepared protein:

```{.python notest}
pocket.show()
```

<iframe
    src="../../images/1eby-crystal-pocket.html"
    width="100%"
    height="630"
    style="border:none;"
    title="Crystal pocket in 1EBY"
></iframe>

See [Work with Pockets](../how-to/pockets.md) for other ways to build or
inspect pockets.

## Load the ligand

In this tutorial we re-dock the crystal ligand, which lets us compare the result
with the crystal pose. The extracted ligand is already registered;
`pocket.ligand_id` points to it:

```{.python notest}
ligand = Ligand.from_id(pocket.ligand_id)
```

To dock your own compounds, load them with `Ligand.from_sdf()`,
`Ligand.from_smiles()`, or a `LigandSet` and call `sync()`. See
[Work with Ligands](../how-to/ligands.md).

## Preview the docking search box

Create a `Docking` with the **prepared** protein and the crystal pocket. Use the
prepared protein, not the input `protein`: the crystal ligand has been removed
from it, and the pocket belongs to it.

```{.python notest}
docking = Docking(protein=prepared, pocket=pocket, ligand=ligand)
docking.show_box()
```

<iframe
    src="../../images/1eby-crystal-docking-box.html"
    width="100%"
    height="650"
    style="border:none;"
    title="Docking search box in the 1EBY crystal pocket"
></iframe>

The crystal pocket includes a nested `box` with sizes and `rotation_deg`
aligned to the ligand, so `show_box()` and docking runs use that orientation
automatically. `pocket.show_box()` shows the same box without creating a
`Docking`. See [Work with Pockets](../how-to/pockets.md#visualization) for
cavity-surface viz (`pocket.show()`) versus this search-box preview.

To overlay docked poses with the search box (e.g. after `run()` / `get_poses()`):

```{.python notest}
poses = docking.get_poses()
docking.show_box(poses=poses)
```

Docking samples the ligand **inside** that oriented box (the ligand's
placement / centroid is constrained to the search volume). Atoms of a
finite-size ligand can stick out of a tight box even when the pose is valid.
The pose should overlap the wireframe, not sit in a mirrored copy of it.

### Rotating the search box interactively

In JupyterLab, pass `interactive=True` to rotate the search box with molstar's
**Docking Box** controls (open **Settings** in the viewer). Releasing a slider
or ending a canvas drag stores the orientation on the `Docking` instance;
subsequent `run()` or `start()` calls include `rotation_deg` in the pocket sent
to the platform. The overlay shows the last synced rotation. Printed cell output
does not update until you re-run the cell.

```{.python notest}
handle = docking.show_box(interactive=True)
docking.rotation_deg  # after a rotation gesture — e.g. [0.0, 45.0, 0.0]
```

Interactive mode requires JupyterLab from this package's virtual environment
(`make jupyter-lab`).
See the [Interactive docking box](../../notebooks/html/interactive-docking-box.html)
notebook for a full walkthrough. Rotated docking on the platform requires
toolbox docking **3.4.32+** on your org.

When the pocket has a nested `box`, `show_box()` already applies that inferred
orientation. Interactive rotation replaces it only after you commit a gesture
(session rotation overrides inferred orientation on subsequent `run()` /
`start()` calls).

## Estimate the cost of a docking run

Request a cost estimate without running the job:

```{.python notest}
docking = Docking(protein=prepared, pocket=pocket, ligand=ligand)
docking.run(quote=True)
docking.estimate
```

The `estimate` property shows the predicted cost in dollars for the docking run.

??? info "Controlling effort"

    By default, the docking effort level is 1 (on a scale of 1–5). Lower effort is faster, higher effort is more thorough.

    ```{.python notest}
    docking.effort = 3
    ```

## Start the docking run

To dock this one ligand to the protein, use:

```{.python notest}
docking = Docking(protein=prepared, pocket=pocket, ligand=ligand)
poses = docking.run()
```

The returned `poses` is a `PoseSet` containing the docked poses. To dock many
ligands, pass `ligands=` and call `start()` instead; see
[Docking many ligands](../tools/docking.md#docking-many-ligands).

!!! tip "Monitoring jobs"
    In notebooks, use [`Docking.watch()`](../ref/docking.md) on a started job. To
    list or inspect executions across tools, see the
    [Executions API](../../platform/ref/executions.md).

## Results

### Viewing results

Each docked pose is assigned a Pose Score and a Binding Energy.

- The `pose_score` is a score that evaluates the quality of each ligand's pose, where higher scores indicate better predicted binding poses. This score can be more informative than binding energy for identifying the optimal conformation.
- The `binding_energy` is the predicted binding energy typically used to estimate the strength of interaction between the ligand and the protein. The units are in kcal/mol and generally the lower energy scores (more negative values) mean higher chances that the ligand would bind to the protein strongly.

When you load tabular results with `docking.get_results()`, each row includes a `best_pose` boolean: `True` for the single pose with the highest `pose_score` among poses for that ligand (for example, one of sixteen poses per ligand), and `False` for the others.

You can inspect the properties of individual poses:

```{.python notest}
poses[0].properties
```

### Viewing docked poses

To visualize the docked poses on the protein, use:

```{.python notest}
poses.download()
prepared.show(poses=poses)
```

All poses are loaded and overlaid on the protein. When there is more than one pose, a
navigation bar appears at the bottom of the viewer: use its ◀ / ▶ buttons or the
Left/Right arrow keys to cycle through an "all poses" view and each individual pose one
at a time.

<iframe
    src="../../images/1eby-crystal-redocked-poses.html"
    width="100%"
    height="650"
    style="border:none;"
    title="Docked poses in the 1EBY crystal pocket"
></iframe>

### Comparing with the crystal pose

Because we re-docked the crystal ligand, we can measure how close the best pose
is to the crystal coordinates. `get_crystal_poses()` returns the poses extracted
during preparation:

```{.python notest}
from deeporigin.drug_discovery import chemistry

crystal_pose = prep.get_crystal_poses().poses[0]
crystal_pose.download()
best = max(
    poses.poses,
    key=lambda pose: float("-inf") if pose.pose_score is None else pose.pose_score,
)
chemistry.pose_rmsd(best.mol, crystal_pose.mol)  # RMSD in Å, no realignment
```

### Retrieving poses from the platform

For async docking runs, you can retrieve docked poses after completion:

```{.python notest}
poses = docking.get_poses()
```

### Exporting for further analysis

Poses can be converted into a dataframe for further analysis or export:

```{.python notest}
df = poses.to_dataframe()
```

### Filtering poses

You typically want to filter these poses to only retain the top pose for each ligand. To do that, use:

```{.python notest}
poses = poses.filter_top_poses()
```

## Constrained docking from the crystal pose

To dock analogs while holding their shared scaffold near the crystal pose, pass
the same crystal pocket to
[`ConstrainedDocking`](../ref/constrained_docking.md) and use the crystal pose
as the reference:

```{.python notest}
from deeporigin.drug_discovery import ConstrainedDocking

constrained = ConstrainedDocking(
    protein=prepared,
    pocket=pocket,
    reference_ligand=ligand,
    reference_pose=crystal_pose.to_ligand(),
    ligand=analog,
)
poses = constrained.run()
```

The platform derives constraints from the maximum common substructure (MCS) of
each analog and the reference ligand. When no MCS matches, the analog is docked
without constraints and its poses have `constrained=False`.

## Docking into a novel pocket

When there is no crystal ligand, or you want to look for other binding sites,
discover pockets first and then choose one explicitly. Ask Protein Prep for
novel pockets during preparation; this uses the platform workflow, so call
`start()` instead of `run()`:

```{.python notest}
prep = ProteinPrep(protein, find_pockets="novel", pocket_count=3)
prep.recommend()
prep.start(quote=True)
prep.estimate  # inspect, then:
prep.confirm()
prep.wait()

prepared = prep.get_results()
pockets = prep.get_pockets()
prepared.show(pockets=pockets)
```

Inspect the candidates (volume, druggability score, location), choose one, and
pass it to `Docking` as above:

```{.python notest}
docking = Docking(protein=prepared, pocket=pockets[0], ligand=ligand)
```

To find pockets on an already-prepared protein without re-running preparation,
use [PocketFinder](../tools/pocketfinder.md).
