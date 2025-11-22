This document describes how to create a `Complex` object, that can be used to run [Docking](./docking.md), [ABFE](../tutorial/abfe.md) and [RBFE](../tutorial/rbfe.md).



## Creating a Complex

### From a directory 

```{.python notest}
# here, we're using the example data directory
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR

sim = Complex.from_dir(BRD_DATA_DIR)
```

The directory should contain:

- exactly one PDB file for the protein
- one or more SDF files for the ligands. Each SDF file can contain one or more molecules.

### From `Protein` and `Ligand` objects

A `Complex` object can be also be constructed using [`Protein`](./proteins.md) and [`Ligand`](./ligands.md) objects. 

```{.python notest}
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR, Protein, Ligand

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")

sim = Complex(protein=protein, ligands=[ligand])
```

### From `LigandSet` objects


A `Complex` object can also be constructed using [`Protein`](./proteins.md) and [`LigandSet`](./ligands.md) objects. 

```{.python notest}
from deeporigin.drug_discovery import Complex, BRD_DATA_DIR, Protein, LigandSet

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
ligands = LigandSet.from_dir(BRD_DATA_DIR)

sim = Complex(protein=protein, ligands=ligands)
```

## Modifying a Complex

You can modify a Complex object by adding or replacing ligands. 

```{.python notest}
from deeporigin.drug_discovery import Complex, Protein, Ligand, BRD_DATA_DIR
protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
ligand3 = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")

# Create a complex with just the protein
sim = Complex(protein=protein)

# Add a single ligand
sim.ligands = ligand3

# Add another ligand
ligand4 = Ligand.from_sdf(BRD_DATA_DIR / "brd-4.sdf")
sim.ligands = sim.ligands + ligand4

# Replace all ligands
ligand5 = Ligand.from_sdf(BRD_DATA_DIR / "brd-5.sdf")
sim.ligands = ligand5  # Replace with a single ligand
```

??? tip "Constructing Ligands"
    To see how to construct Ligands, see [:material-page-previous: Ligands](./ligands.md)

??? tip "Constructing the Protein"
    To see how to construct the Protein, see [:material-page-previous: Proteins](./proteins.md)

## Preparing a Complex

To prepare a protein-ligand complex for simulation or further analysis, use the `Complex.prepare()` method. This method runs system preparation on a given ligand in the context of the complex's protein, handling tasks such as protonation, water retention, and box padding.



Typically, you would call this method using a ligand in the complex:

```{.python notest}
prepared_system = sim.prepare(sim.ligands[0])
prepared_system.show()
```

You should see something like:

<iframe 
    src="../../images/prepared-system.html" 
    width="100%" 
    height="660" 
    style="border:none;"
    title="Visualization of prepared system"
></iframe>

which shows you the prepared system.

!!! info "System preparation parameters"
    Look at the [:material-page-next: reference documentation](../ref/complex.md#src.drug_discovery.complex.Complex.prepare) to understand parameters for system preparation.


## Specifying a Client

A `Complex` can be configured with a [`DeepOriginClient`](../../platform/index.md) explicitly, using:

```{.python notest}
sim = Complex.from_dir(..., client=client)
```

## Reference

-  [:material-page-next: Complex](../ref/complex.md)