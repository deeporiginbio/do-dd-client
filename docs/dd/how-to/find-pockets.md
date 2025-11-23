This document describes how to find pockets in a [`Protein`](../ref/protein.md) using the Deep Origin Pocket Finder.

# Pockets

## Creating Pockets

First, we create a Protein, for example, using:

```python
from deeporigin.drug_discovery import  Protein, BRD_DATA_DIR
protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
```

### Using Pocket Finder

We can then find pockets in this protein using the Pocket Finder tool:

```{.python notest}
pockets = protein.find_pockets(pocket_count=1)
```

### Using PDB Files

Create a pocket directly from a PDB file:

```{.python notest}
from deeporigin.drug_discovery import Pocket

pocket = Pocket.from_pdb_file("path/to/pocket.pdb", name="my_pocket")
```

### From a residue number

Create a pocket centered on a specific residue:

```{.python notest}
from deeporigin.drug_discovery import Pocket

pocket = Pocket.from_residue_number(
    protein=protein,
    residue_number=123,
    chain_id="A",
    cutoff=5.0
)
```

### From a Ligand

Create a pocket from a ligand structure:

```python
from deeporigin.drug_discovery import Pocket, Ligand, BRD_DATA_DIR

ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
pocket = Pocket.from_ligand(ligand, name="ligand_pocket")
```

## Visualization

### Inspecting pocket data

View pocket properties by simply inspecting the object:

```{.python notest}
pocket
```

You should see a table similar to:

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


### 3D visualization in a Protein

Pockets can be visualized using:

```{.python notest}
protein.show(pockets=pockets)
```

You should see something like:

<iframe 
    src="../../images/pockets.html" 
    width="100%" 
    height="650" 
    style="border:none;"
    title="Protein visualization"
></iframe>