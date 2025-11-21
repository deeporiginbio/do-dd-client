# Docking

This document describes how to [dock :octicons-link-external-16:](https://en.wikipedia.org/wiki/Docking_(molecular)) a large set of ligands to a protein  using Deep Origin tools. 


!!! tip "Looking to dock a few ligands?"
    This document describes how to dock more than a handful of ligands (>10) using a batch job. To dock a single (or a few ligands), you might prefer to use the `.dock()` function of the `Protein` class, as [described here](../how-to/docking.md). 

## Prerequisites

We assume that we have an initialized and configured a `Complex` object:

```{.python notest}
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR

sim = Complex.from_dir(BRD_DATA_DIR) 
```


## Find pockets

We find pockets in the protein using:

```{.python notest}
pockets = sim.protein.find_pockets(pocket_count=1)
```

We can visualize the pocket using:

```{.python notest}
sim.protein.show(pockets=pockets)
```

You should see something along the lines of:

<iframe 
    src="../../images/pockets.html" 
    width="100%" 
    height="650" 
    style="border:none;"
    title="Protein visualization"
></iframe>

We can see that the protein is shown together with the identified pocket in red. 

!!! tip "The Pocket Finder Function"
    For more details on how to use the Pocket Finder, look at the [How To section for the Pocket Finder](../how-to/find-pockets.md).

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

To estimate the cost of docking all the Ligands in the Complex to the Protein, using the pocket we found, we can do:


```{.python notest}
pocket = pockets[0] # or choose as needed
jobs = sim.docking.run(pocket=pocket)
```

We get back a widget representing the Jobs that will run. These Jobs are in the `Quoted` state, and provide an estimate of how much this will cost. 

<iframe 
    src="./docking-quote.html" 
    width="100%" 
    height="400" 
    style="border:none;"
    title="Quoted Docking Job"
></iframe>

!!! warning "Example widget"
    Prices shown here are for demonstrative purposes only. Actual prices can vary. 

## Start the docking run

To approve this Job and start all executions, use:

```{.python notest}
jobs.confirm()
jobs
```

The `jobs` object now reflects the `Running` state of all executions. 

To monitor the progress of this Docking Job, use:

```{.python notest}
jobs.watch()
jobs
```

The widget will update as ligands are docked, as shown below:

<iframe 
    src="./docking-running.html" 
    width="100%" 
    height="300" 
    style="border:none;"
    title="Running Docking Job"
></iframe>


??? info "Controlling batch size"

    By default, all ligands are docked in batches of 32 ligands. 

    This can be controlled in two ways. First, you can control the batch size using the `batch_size` parameter.

    ```{.python notest}
    sim.dock(
        batch_size=32,
        ... 
    )
    ```

    You can also specify the number of workers using:

    ```{.python notest}
    sim.dock(
        n_workers=2,
        ...
    )
    ```

    You can specify either the number of workers or the batch size, but not both. 



!!! tip "Monitoring jobs"
    For more details about how to monitor jobs, look at this [How To section](../how-to/job.md).

## Results

### Viewing results

After completion of docking, we can retrieve docked poses using:

```{.python notest}
poses = sim.docking.get_poses()
```  

Each docked pose is assigned a Pose Score and a Binding Energy. 


- The `pose_score` is a score that evaluates the quality of each ligand's pose, where higher scores indicate better predicted binding poses. This score can be more informative than binding energy for identifying the optimal conformation.
- The `binding_energy` is the predicted binding energy typically used to estimate the strength of interaction between the ligand and the protein. The units are in kcal/mol and generally the lower energy scores (more negative values) mean higher chances that the ligand would bind to the protein strongly.


We can view the pose scores and binding energies of all ligands using:

```{.python notest}
poses.plot()
```  

This generates an interactive scatter plot similar to:

<iframe 
    src="./docking-scatter.html" 
    width="100%" 
    height="600" 
    style="border:none;"
    title="Scatter plot of poses"
></iframe>

### Viewing docked poses

To view the docked poses of all ligands in the complex, use:

```{.python notest}
sim.docking.show_poses()
```

<iframe 
    src="../../images/docked-poses.html" 
    width="100%" 
    height="650" 
    style="border:none;"
    title="Protein visualization"
></iframe>


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


