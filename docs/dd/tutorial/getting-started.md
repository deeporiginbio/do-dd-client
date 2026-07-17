# Getting started with the Drug Discovery toolbox

This document describes how to use the Deep Origin Drug Discovery toolbox.


## Prerequisites 

Make sure you have [:material-page-previous: installed](../../install.md), [:material-page-previous: authenticated](../../how-to/auth.md), and [:material-page-previous: configured](../../configure.md) with the Deep Origin python client.

!!! tip "Recommended installation method" 
    We recommend using [:material-page-previous: these instructions](../../install.md#recommended-installation) to install the Deep Origin python client.

    Following these instructions will install the deeporigin client in an isolated environment using `uv`, and will start a Jupyter instance that you will need for the rest of this tutorial.


## Projects

Work in Deep Origin is organized in Projects. You can create a new project using:

```{.python notest}
from deeporigin import projects 
projects.create("my-test-project")
```

## Input data

Docking, ABFE, and RBFE require a protein to be in a PDB file as input.

Ligands can be imported from SDF files or SMILES strings. To run ABFE and RBFE, the ligand must be in a SDF file.

!!! tip "Example data"
    If you want to explore these tools using some example data, we provide the [BRD4 protein :octicons-link-external-16:](https://pubs.acs.org/doi/10.1021/acs.jctc.0c00660) and a few ligands. This is built into the `deeporigin` package and can be accessed using:

    ```{.python notest}
    from deeporigin.drug_discovery import BRD_DATA_DIR
    ```


### Loading a Protein

The 3D structure of the protein can be viewed using the built-in `show` method in the `Protein` class:

```python
from deeporigin.drug_discovery import Protein, BRD_DATA_DIR

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")

protein.show()
```

This generates a 3D visualization of the protein, similar to:

<iframe 
    src="../../images/brd-protein.html" 
    width="100%" 
    height="630" 
    style="border:none;"
    title="Protein visualization"
></iframe>

To upload the protein to our project, we can use:

```{.python notest}
protein.sync()
```

We verify that the protein is now in our project using:

```{.python notest}
projects.proteins()
```

### Loading Ligands

We can load a ligand set using:

```python
from deeporigin.drug_discovery import LigandSet, BRD_DATA_DIR

ligands = LigandSet.from_dir(BRD_DATA_DIR)
ligands
```

and you should see something similar to:
    
<div style='width: 500px; padding: 15px; border: 1px solid #ddd; border-radius: 6px; background-color: #f9f9f9;'><h3 style='margin-top: 0; color: #333;'>LigandSet with 8 ligands</h3><p style='margin: 8px 0;'><strong>8</strong> unique SMILES <span class='badge text-bg-secondary' style='font-variant: small-caps;'>NOT PROTONATED</span> <span class='badge text-bg-info' style='font-variant: small-caps;'>3D</span></p><p style='margin: 8px 0;'>Properties: initial_smiles, r_exp_dg</p><div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #ddd;'><p style='margin: 4px 0; font-size: 0.9em; color: #666;'><em>Use <code>.to_dataframe()</code> to convert to a dataframe, <code>.show_df()</code> to view dataframe with structures, or <code>.show()</code> for 3D visualization, <code>.prepare()</code> to prepare ligands for docking</em></p></div></div>


!!! tip "Jupyter notebooks"
    It is assumed that you are working in a Jupyter notebook (or similar IPython environment). This makes it easier to run the workflow, and some functions assume that you are in a Jupyter notebook.



### Viewing Ligands (3D structures)

We can also 3D structures using:

```python
from deeporigin.drug_discovery import LigandSet, BRD_DATA_DIR

ligands = LigandSet.from_dir(BRD_DATA_DIR)

ligands.show()
```


<iframe 
    src="../../images/brd-ligands.html" 
    width="100%" 
    height="650" 
    style="border:none;"
    title="Ligand visualization"
></iframe>

We can now load these ligands into our project:

```{.python notest}
ligands.sync()
```

And we can verify that our project contains these ligands:

```{.python notest}
projects.ligands()
```


That's it! We are now ready to perform [:material-page-next: docking](./docking.md) and [:material-page-next: ABFE](./abfe.md).


