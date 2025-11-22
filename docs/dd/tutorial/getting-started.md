# Getting started with the Drug Discovery toolbox

This document describes how to use the Drug Discovery toolbox to perform docking and run ABFE and RBFE runs on Deep Origin. 

## Prerequisites 

Make sure you have [:material-page-previous: installed](../../install.md), [:material-page-previous: configured](../../configure.md), and [:material-page-previous: authenticated](../../how-to/auth.md) with the Deep Origin python client.

!!! tip "Recommended installation method" 
    We recommend using [:material-page-previous: these instructions](../../install.md#recommended-installation) to install the Deep Origin python client.

    Following these instructions will install the deeporigin client in an isolated environment using `uv`, and will start a Jupyter instance that you will need for the rest of this tutorial.


## Input data

Docking, ABFE, and RBFE require a protein to be in a PDB file as input.

Ligands can be imported from SDF files or SMILES strings. To run ABFE and RBFE, the ligand must be in a SDF file.

!!! tip "Example data"
    If you want to explore these tools using some example data, we provide the [BRD4 protein](https://pubs.acs.org/doi/10.1021/acs.jctc.0c00660) and a few ligands. This is built into the `deeporigin` package and can be accessed using:

    ```python
    from deeporigin.drug_discovery import BRD_DATA_DIR
    ```

## Creating a `Complex` object

The core of the Drug Discovery toolbox is the [`Complex`](../ref/complex.md) class, that acts as a container for a [`Protein`](../ref/protein.md) and a set of [`Ligands`](../ref/ligand.md).

The `Complex` object can be created using:

```{.python notest}
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR

# here, we're using the example data directory
sim = Complex.from_dir(BRD_DATA_DIR)
```

## Inspecting the `Complex` object

Inspecting the object shows that it contains a protein and 8 ligands:

```{.python notest}
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR

sim = Complex.from_dir(BRD_DATA_DIR)

sim
```


!!! success "Expected output"
    ```python
    Complex(protein=brd.pdb with 8 ligands)
    ```

### Viewing the Protein

The 3D structure of the protein can be viewed using the built-in `show` method in the `Protein` class:

```{.python notest}
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR

sim = Complex.from_dir(BRD_DATA_DIR)

sim.protein.show()
```

This generates a 3D visualization of the protein, similar to:

<iframe 
    src="../../images/brd-protein.html" 
    width="100%" 
    height="630" 
    style="border:none;"
    title="Protein visualization"
></iframe>

### Listing Ligands

We can further inspect the ligands by inspecting the `ligands` attribute:

```{.python notest}
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR

sim = Complex.from_dir(BRD_DATA_DIR)

sim.ligands
```
and you should see something similar to:
    
<div style='width: 500px; padding: 15px; border: 1px solid #ddd; border-radius: 6px; background-color: #f9f9f9;'><h3 style='margin-top: 0; color: #333;'>LigandSet with 8 ligands</h3><p style='margin: 8px 0;'><strong>8</strong> unique SMILES</p><p style='margin: 8px 0;'>Properties: initial_smiles, r_exp_dg</p><div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid #ddd;'><p style='margin: 4px 0; font-size: 0.9em; color: #666;'><em>Use <code>.to_dataframe()</code> to convert to a dataframe, <code>.show_df()</code> to view dataframewith structures, or <code>.show()</code> for 3D visualization</em></p></div></div>


!!! tip "Jupyter notebooks"
    It is assumed that you are working in a Jupyter notebook (or similar IPython environment). This makes it easier to run the workflow, and some functions assume that you are in a Jupyter notebook.



### Viewing Ligands (3D structures)

We can also 3D structures using:

```{.python notest}
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR

sim = Complex.from_dir(BRD_DATA_DIR)

sim.ligands.show()
```


<iframe 
    src="../../images/brd-ligands.html" 
    width="100%" 
    height="650" 
    style="border:none;"
    title="Ligand visualization"
></iframe>



That's it! We are now ready to perform [:material-page-next: docking](./docking.md), [:material-page-next: ABFE](./abfe.md), and [:material-page-next: RBFE](./rbfe.md).


