# RBFE

This document describes how to prepare systems and plan ligand networks for
[RBFE :octicons-link-external-16:](https://en.wikipedia.org/wiki/Free-energy_perturbation)
(relative binding free energy) workflows using Deep Origin tools.

## Prerequisites

We assume a protein and two ligands you want to compare. In this tutorial we
use the BRD4 example dataset.

```{.python notest}
from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Ligand,
    Protein,
    SystemPrep,
)

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
protein.sync()

ligand1 = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
ligand1.sync()

ligand2 = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
ligand2.sync()
```

For more details on how to get started, see
[:material-page-previous: Getting Started](./getting-started.md).

## System preparation

Before RBFE, prepare simulation-ready systems for the protein–ligand pair.
`SystemPrep` accepts two ligands and runs RBFE-oriented preparation (binding and
solvation legs for both ligands).

```{.python notest}
sysprep = SystemPrep(
    protein=protein,
    ligand1=ligand1,
    ligand2=ligand2,
)

prepared = sysprep.run()
prepared.show()
```

The returned `PreparedSystem` includes paths to binding and solvation XML files
and a system PDB. Submit batch RBFE with the `RBFE` class and platform tool
`deeporigin.rbfe`:

```{.python notest}
from deeporigin.drug_discovery import RBFE, RBFEParams

# End-to-end: prep + FEP for one pair (add more pairs to the list for networks)
rbfe = RBFE.from_pairs(
    protein=protein,
    pairs=[(ligand1, ligand2)],
    params=RBFEParams(test_run=1),
)
rbfe.start()
```

For prep only, use `RBFE(mode="sysprep", ...)`. For FEP on existing prepared
systems, use `RBFE.from_prepared_systems(prepared_systems=[prepared, ...])`.
See [:material-page-previous: Platform executions](../../platform/ref/executions.md).

## Constructing a network

!!! tip "Constructing a network"
    View the documentation for `LigandSet` to learn how to
    [construct a network](../how-to/ligands.md#constructing-a-network-using-konnektor).

For a congeneric series, map edges between ligands before scheduling pairwise
RBFE calculations:

```{.python notest}
from deeporigin.drug_discovery import LigandSet

ligands = LigandSet.from_dir(BRD_DATA_DIR)
ligands.map_network().show_network()
```

This stores the network on the ligand set and renders an interactive graph in
Jupyter.
