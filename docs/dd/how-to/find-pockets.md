This document describes how to find pockets in a [`Protein`](../ref/protein.md) using the Deep Origin Pocket Finder.

# Pockets

## Creating Pockets

First, we create a Protein, for example, using:

```{.python continuation}
from deeporigin.drug_discovery import  Protein, BRD_DATA_DIR
protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
protein.remove_water()
```

### Using Pocket Finder

Use the ``PocketFinder`` class from ``deeporigin.drug_discovery.pocket_finder`` to find pockets:

```{.python continuation}
from deeporigin.drug_discovery import PocketFinder

pf = PocketFinder(protein, pocket_count=1)
pockets = pf.run()
```

`pf.run()` runs the pocket finder (blocking) and returns a list of `Pocket` objects.

By default, `run(use_cache=True)` reuses existing platform results when the protein
is registered and a matching result exists (same protein and parameters). To always
run the tool, use `pf.run(use_cache=False)`. Note that you may be charged for new
tool runs. 

#### Estimating cost

To get a cost estimate without running the pocket finder, call `quote()` before `run()`:

```{.python notest}
pf = PocketFinder(protein, pocket_count=1)
pf.quote()       # populates pf.estimate
pf.estimate      # estimated cost in dollars
pockets = pf.run()  # run when ready; pf.cost is set after completion
```

### Using PDB Files

Create a pocket directly from a PDB file:

```{.python notest}
from deeporigin.drug_discovery import Pocket

pocket = Pocket.from_pdb_file("path/to/pocket.pdb", name="my_pocket")
```

### From a residue number

Create a pocket centered on a specific residue:

```{.python continuation}
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

### From a result-explorer record ID

Load a single pocket by its result-explorer record ID (for example, an ID from a previous pocket-finder run or from the platform UI):

```{.python notest}
from deeporigin.drug_discovery import Pocket

pocket = Pocket.from_id("your-pocket-record-id")
```

This fetches the record, downloads the pocket PDB file, and returns a `Pocket` with properties populated from the record. Optionally pass a `client` if you do not want to use the default:

```{.python notest}
pocket = Pocket.from_id("your-pocket-record-id", client=my_client)
```

If no record exists for the given ID, `ValueError` is raised.

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