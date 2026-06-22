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
rbfe = RBFE(
    protein=protein,
    pairs=[(ligand1, ligand2)],
    params=RBFEParams(test_run=1),
)
rbfe.start()
```

For FEP on existing prepared systems, pass `prepared_systems=[prepared, ...]`
(`steps` is inferred as `["rbfe"]`). For single-pair prep without FEP, use
`SystemPrep` instead of `RBFE`.
See [:material-page-previous: Platform executions](../../platform/ref/executions.md).

## Constructing a network

For a congeneric series, submit the full ligand set and let the workflow run
Konnektor to plan pairwise edges, then system-prep and RBFE for each edge:

```{.python notest}
from deeporigin.drug_discovery import LigandSet

ligand_set = LigandSet.from_dir(BRD_DATA_DIR)
for ligand in ligand_set:
    ligand.sync()

rbfe = RBFE(
    protein=protein,
    ligands=ligand_set,
    network_type="mst",
    params=RBFEParams(test_run=1),
)
rbfe.start()
```

See the [RBFE many-ligands workflow notebook](../../notebooks/clean/rbfe-5-many-ligands-workflow.ipynb)
for an end-to-end example on dev. For cycle closure with anchor ABFE values, see
[RBFE cycle-closure workflow](../../notebooks/clean/rbfe-6-cycle-closure-workflow.ipynb).

To preview a network interactively in Jupyter before submitting, use
`Konnektor(ligands=...).run()` and call `.show_network()` on the result — see
[constructing a network](../how-to/ligands.md#constructing-a-network-using-konnektor).
