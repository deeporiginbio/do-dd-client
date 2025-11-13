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

The core of the Drug Discovery toolbox is the `Complex` class, that acts as a container for a protein and a set of ligand.

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

### Viewing the protein

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
    height="650" 
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

!!! success "Expected output"

    ![](../../images//ligands.png)
    

!!! tip "Jupyter notebooks"
    It is assumed that you are working in a Jupyter notebook (or similar IPython environment). This makes it easier to run the workflow, and some functions assume that you are in a Jupyter notebook.



### Viewing Ligands (3D structures)

We can also view a table of 3D structures as follows:

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


