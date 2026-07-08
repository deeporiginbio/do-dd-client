# Docking

This document describes how to [dock :octicons-link-external-16:](https://en.wikipedia.org/wiki/Docking_(molecular)) ligands to a protein  using Deep Origin tools.




## Prerequisites

First, import the necessary classes:

```{.python continuation}
from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Docking,
    Ligand,
    Pocket,
    PocketFinder,
    Protein,
)
```

## Load protein

Load a protein from a PDB file and remove water molecules:

```{.python continuation}
protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
protein.remove_water()
```

We can view the protein to see that waters have been removed:

```{.python notest}
protein.show()
```

<iframe 
    src="../../images/brd-no-water.html" 
    width="100%" 
    height="630" 
    style="border:none;"
    title="Protein visualization"
></iframe>

Sync the protein to the platform so it can be used for docking:

```{.python notest}
protein.sync()
```

## Load ligand

Load a ligand from an SDF file:

```{.python continuation}
ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
```

Sync the ligand to the platform and to your project:

```{.python notest}
ligand.sync()
```

## Find pockets in Protein

Run Pocket Finder on the synced protein to detect binding sites. Create a `PocketFinder` with that protein, then call `run()` to execute the tool and get a list of `Pocket` objects:

```{.python notest}
pf = PocketFinder(protein, pocket_count=1)
pockets = pf.run()
pocket = pockets[0]
```

We can visualize the pocket using:

```{.python notest}
protein.show(pockets=pockets)
```

You should see something along the lines of:

<iframe 
    src="../../images/brd-pocket.html" 
    width="100%" 
    height="650" 
    style="border:none;"
    title="Protein visualization"
></iframe>

We can see that the protein is shown together with the identified pocket in red. 

!!! tip "The Pocket Finder Function"
    For more details on how to use the Pocket Finder, look at [PocketFinder](../tools/pocketfinder.md).

Preview the docking search box (protein plus wireframe box from pocket center and box size) before running:

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligand=ligand)
docking.show_box()
```

You should see something like this:

<iframe 
    src="../../images/brd-docking-box.html" 
    width="100%" 
    height="650" 
    style="border:none;"
    title="Protein visualization"
></iframe>

The `pocket` object can be inspected, too:

```{.python notest}
pocket
```

!!! success "Expected Output"
    ```
    Pocket:
    ╭─────────────────────────┬──────────────╮
    │ Name                    │ pocket_1     │
    ├─────────────────────────┼──────────────┤
    │ Color                   │ red          │
    ├─────────────────────────┼──────────────┤
    │ Volume                  │ 545.0 Å³     │
    ├─────────────────────────┼──────────────┤
    │ Total SASA              │ 1560.474 Å²  │
    ├─────────────────────────┼──────────────┤
    │ Polar SASA              │ 762.11224 Å² │
    ├─────────────────────────┼──────────────┤
    │ Polar/Apolar SASA ratio │ 0.95459515   │
    ├─────────────────────────┼──────────────┤
    │ Hydrophobicity          │ 15.903226    │
    ├─────────────────────────┼──────────────┤
    │ Polarity                │ 17.0         │
    ├─────────────────────────┼──────────────┤
    │ Drugability score       │ 0.83243614   │
    ╰─────────────────────────┴──────────────╯
    ```


## Estimate the cost of a docking run

Create a `Docking` object with the protein, pocket, and ligand, then get a cost estimate:

```{.python notest}
docking = Docking(protein=protein, pocket=pocket, ligand=ligand)
docking.start(quote=True)
docking.estimate
```

The `estimate` property shows the predicted cost in dollars for the docking run.

??? info "Controlling effort"

    By default, the docking effort level is 3 (on a scale of 1–5). Lower effort is faster, higher effort is more thorough.

    ```{.python notest}
    docking.effort = 1
    ```

## Start the docking run

To dock this one ligand to the protein, use:

```{.python notest}
poses = docking.run()
```

The returned `poses` is a `LigandSet` containing the docked poses.

!!! tip "Monitoring jobs"
    For more details about how to monitor jobs, look at this [How To section](../how-to/job.md).

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
protein.show(poses=poses)
```

All poses are loaded and overlaid on the protein. When there is more than one pose, a
navigation bar appears at the bottom of the viewer: use its ◀ / ▶ buttons or the
Left/Right arrow keys to cycle through an "all poses" view and each individual pose one
at a time.

<iframe 
    src="../../images/brd-docked-poses.html" 
    width="100%" 
    height="650" 
    style="border:none;"
    title="Protein visualization"
></iframe>

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


