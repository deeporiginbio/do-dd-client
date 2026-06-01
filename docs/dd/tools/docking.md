# Docking

Dock ligands to a [`Protein`](../ref/protein.md) with the Deep Origin docking tool.

## Prerequisites

- You have a prepared [Protein](../how-to/proteins.md)
- You have a [Ligand or LigandSet](../how-to/ligands.md)
- You have [protonated your ligands](../how-to/ligands.md#protonation)
- You have found pockets in your protein using [PocketFinder](pocketfinder.md)

## Docking a single `Ligand`

Use [`Docking`](../ref/docking.md) with your protein, pocket, and ligand. Here `pocket` is a `Pocket` from [PocketFinder](pocketfinder.md) :octicons-book-24: . Both [`Docking.run()`](../ref/docking.md) and [`Docking.start()`](../ref/docking.md) use `client.executions.create`: `run()` sets `sync=True` for **one** ligand (one blocking request until completion), and `start()` sets `sync=False` for a single persisted async job with **two or more** ligands. [`Docking.run()`](../ref/docking.md) returns a `LigandSet` of poses.

```{.python notest}
from deeporigin.drug_discovery import Docking

docking = Docking(protein=protein, pocket=pocket, ligand=ligand)
poses = docking.run()
```

### Estimating cost

To get a cost estimate without running the docking, call [`quote()`](../ref/docking.md) on the [`Docking`](../ref/docking.md) instance:

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligand=ligand)
docking.quote()       # populates docking.estimate
docking.estimate      # estimated cost in dollars
docking.cost          # None until a billable run completes
```

After a completed run, the actual cost is on the same object:

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligand=ligand)
poses = docking.run()

docking.cost  # actual cost in dollars
```


### Viewing docked poses

Docked poses for that ligand can be viewed using:

```{.python notest}
protein.show(poses=poses)
```

You will see something similar to the following. Use the arrows to inspect individual poses.

<iframe
    src="../../images/1eby-docked-poses.html"
    width="100%"
    height="650"
    style="border:none;"
    title="Docked poses of ligand in 1EBY"
></iframe>

### Viewing pose scores and binding energy

Every pose is assigned a pose score and a binding energy. These can be viewed using:

```{.python notest}
poses
```

A widget similar to the following will be shown:

<div style='width: 500px; padding: 15px; border: 1px solid #ddd; border-radius: 6px; background-color: #f9f9f9;'><h3 style='margin-top: 0; color: #333;'>LigandSet with 15 poses</h3><p style='margin: 8px 0;'><strong>SMILES:</strong> Cc1[nH]c2cc(Cl)cc(Cl)c2c1CCN</p><p style='margin: 8px 0;'>Properties: Binding Energy, POSE SCORE, SMILES, initial_smiles</p><div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #ddd;'><p style='margin: 4px 0; font-size: 0.9em; color: #666;'><em>Use <code>.to_dataframe()</code> to convert to a dataframe, <code>.show_df()</code> to view dataframewith structures, or <code>.show()</code> for 3D visualization</em></p></div></div>

To work with a dataframe containing this data, use:

```{.python notest}
df = poses.to_dataframe()
```

### Exporting poses to SDF

Poses can be saved to a SDF file using:


```{.python notest}
poses.to_sdf()
```

## Docking many ligands

### Using batch jobs

!!! tip "Tutorial"
    Follow [the tutorial](../tutorial/docking.md) on how to dock ligands using batch jobs. This is best suited for large jobs with 100+ ligands.

### Using functions

Several ligands in a LigandSet can be docked by passing `ligands` to [`Docking`](../ref/docking.md), then [`Docking.start()`](../ref/docking.md) (async). Poll with [`sync()`](../ref/docking.md) or Jupyter helpers until the job completes, then call [`get_results()`](../ref/docking.md) to retrieve a `LigandSet` of poses.

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligands=ligands)
docking.start()
# … wait for completion (docking.sync() in a loop, or watch() in notebooks) …
poses = docking.get_results()
```

`poses` is a `LigandSet` containing the docked poses. To work with a DataFrame:

```{.python notest}
df = poses.to_dataframe()
```

To filter poses to keep only top poses, use:

```{.python notest}
top_poses = poses.filter_top_poses()
```

These poses can be visualized as before:

```{.python notest}
protein.show(poses=poses)
```

If you need SDF files for the poses (e.g. for export), use [`get_poses()`](../ref/docking.md) instead, which downloads the SDF files from the platform:

```{.python notest}
poses = docking.get_poses()
poses.to_sdf("my_poses.sdf")
```

To estimate the cost of docking a full LigandSet without running it:

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligands=ligands)
docking.quote()
docking.estimate  # total estimated cost across all ligands
```


## Constrained docking

We can use constrained docking to dock a Ligand to a Protein while constraining certain atoms to certain locations.

Typically, these constraints are computed from a reference docked pose for another (similar) ligand, using a Maximum Common Substructure (MCS) shared across ligands.

Assuming we have docked a ligand to a protein and picked a pose to be the "reference". When constrained docking is available, it will be configured through [`Docking`](../ref/docking.md) (reference-pose parameters are not exposed yet). A standard run looks like:

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligand=ligand)
poses = docking.run()

# view poses
protein.show(poses=poses)
```

To view new poses together with the reference pose, combine the `LigandSet` values (for example):

```{.python notest}
protein.show(poses=reference_pose + poses)
```

## Filtering docking outputs

Filter docking results by score and related properties.

!!! warning "Deprecated: `Complex`"
    The examples below use the deprecated [`Complex`](../ref/complex.md) type. New workflows should use [`Docking`](../ref/docking.md) (and related APIs) instead of `Complex.docking`.

Here we assume that you have constructed a `Complex` object and successfully run [Docking](../tutorial/docking.md).
Following convention, we assume that the `Complex` object is called `sim`.

### Fetch docked poses

First, we get the results of Docking in a pandas DataFrame using:

```{.python notest}
poses = sim.docking.get_poses()
```
Inspecting the `poses` object shows us:

<div style='width: 500px; padding: 15px; border: 1px solid #ddd; border-radius: 6px; background-color: #f9f9f9;'><h3 style='margin-top: 0; color: #333;'>LigandSet with 2246 ligands</h3><p style='margin: 8px 0;'><strong>157</strong> unique SMILES</p><p style='margin: 8px 0;'>Properties: Binding Energy, POSE SCORE, SCORE, SMILES, initial_smiles</p><div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #ddd;'><p style='margin: 4px 0; font-size: 0.9em; color: #666;'><em>Use <code>.to_dataframe()</code> to convert to a dataframe, <code>.show_df()</code> to view dataframewith structures, or <code>.show()</code> for 3D visualization</em></p></div></div>

### Plot docking results

The metrics of all docked poses can be plotted in a scatter plot using:

```{.python notest}
poses.plot()
```

<iframe
    src="../../images/docking-scatter.html"
    width="100%"
    height="660"
    style="border:none;"
    title="Scatter plot of docking scores"
></iframe>

### Pick top results

We can pick the top pose for each SMILES string using:

```{.python notest}
poses.filter_top_poses()
```
