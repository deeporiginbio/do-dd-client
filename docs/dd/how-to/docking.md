
# Docking Ligands to a Protein

This document describes how to dock ligands to a Protein. 


## Prerequisites

- You have a prepared [Protein](./proteins.md)
- You have a [Ligand or LigandSet](./ligands.md)
- You have [protonated your ligands](./ligands.md#protonation)
- You have found pockets in your Protein using the [Pocket Finder](./find-pockets.md)


## Docking a single `Ligand`

Use [`Docking`](../ref/docking.md) with your protein, pocket, and ligand. Here `pocket` is a `Pocket` from the [Pocket Finder](find-pockets.md) :octicons-book-24: . Both [`Docking.run()`](../ref/docking.md) and [`Docking.start()`](../ref/docking.md) use `client.executions.create`: `run()` sets `sync=True` (one blocking request per ligand), and `start()` sets `sync=False` for a single persisted async job. [`Docking.run()`](../ref/docking.md) returns a `LigandSet` of poses.

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

## Docking a `LigandSet` 

### Using Batch Jobs

!!! tip "Tutorial"
    Follow [the tutorial](../tutorial/docking.md) on how to dock ligands using Batch Jobs. This is best suited for large jobs with 100+ ligands. 

### Using Functions

Several ligands in a LigandSet can be docked by passing `ligands` to [`Docking`](../ref/docking.md):

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligands=ligands)
poses = docking.run()
```

`poses` contains all poses for all ligands in the LigandSet. To filter poses to keep only top poses, use:

```{.python notest}
top_poses = poses.filter_top_poses()
```

These poses can be visualized as before:

```{.python notest}
protein.show(poses=poses)
```

To estimate the cost of docking a full LigandSet without running it:

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligands=ligands)
docking.quote()
docking.estimate  # total estimated cost across all ligands
```


## Constrained Docking


!!! danger "Under development"
    Constrained Docking is under active development and is not generally available. 

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