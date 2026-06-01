This document describes how to create and work with pockets for docking and other Deep Origin tools.

The [`Pocket` class](../ref/pocket.md) is the primary way to represent binding sites in the Drug Discovery toolbox.

## Constructing a Pocket

Most pocket workflows start from a [`Protein`](../ref/protein.md). For example:

```{.python continuation}
from deeporigin.drug_discovery import Protein, BRD_DATA_DIR

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
protein.remove_water()
```

### Using the PocketFinder tool

To discover novel pockets on a protein structure, use the PocketFinder tool. See the [PocketFinder documentation](../tools/pocketfinder.md) for synchronous and asynchronous execution, cost estimates, loading results by record ID, and visualization.

### From a residue number

Create a pocket centered on a specific residue:

```{.python continuation}
from deeporigin.drug_discovery import Pocket

pocket = Pocket.from_residue_number(
    protein=protein,
    residue_number=123,
    chain_id="A",
    cutoff=5.0,
)
```

`residue_number` is the residue index in the loaded structure. `chain_id` is optional when the number is unique. `cutoff` (Å) sets how far from that residue to include surrounding residues in the pocket.

### From a crystal ligand

When a PDB contains a co-crystallized ligand, extract it from the protein and define the pocket from that ligand geometry:

```python
from deeporigin.drug_discovery import Protein, Pocket

protein = Protein.from_pdb_id("1EBY")
ligand = protein.extract_ligand()
pocket = Pocket.from_ligand(ligand, name="crystal_ligand_pocket")
```

`extract_ligand()` removes the ligand from the protein structure in place. See [Extract crystal ligands](proteins.md#extract-crystal-ligands) for warnings, excluded residue names, and customization.

### From a ligand

Create a pocket from a ligand structure loaded separately (for example from an SDF file):

```python
from deeporigin.drug_discovery import Pocket, Ligand, BRD_DATA_DIR

ligand = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
pocket = Pocket.from_ligand(ligand, name="ligand_pocket")
```

This uses the ligand coordinates as the pocket definition. For loading ligands from other sources, see [Work with Ligands](ligands.md).
