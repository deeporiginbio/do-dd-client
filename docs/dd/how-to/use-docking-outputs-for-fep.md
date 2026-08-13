This document describes how to use the outputs of Docking as inputs to FEP tools.

!!! warning "Deprecated: `Complex`"
    The steps below assume the legacy [`Complex`](../ref/complex.md) workflow. Prefer [`Docking`](../ref/docking.md), [`ABFE`](../ref/abfe.md), and `SystemPrep` when starting new projects.

!!! warning "Deprecated: `docking_step` / `sim.docking`"
    The `docking_step` module was removed; `Complex.docking` no longer exists. Use [`Docking`](../ref/docking.md) instead of `sim.docking` in the examples below.

## Assumptions

We assume that you have

1. [:material-page-previous: created a `Complex` object](../tutorial/getting-started.md) (deprecated; see warning above)
2. [:material-page-previous: run Docking](../tutorial/docking.md)

## Pick poses to use

If you have used docking on a number of ligands, you can find the best poses for each ligand using:

```{.python notest}
poses = docking.get_poses()
poses = poses.filter_top_poses()
```

Pass poses into SystemPrep / ABFE / RBFE (preferred):

```{.python notest}
from deeporigin.drug_discovery import ABFE, SystemPrep

pose = poses[0]
sysprep = SystemPrep(protein=protein, pose=pose)
prepared = sysprep.run()
abfe = ABFE(prepared_system=prepared)
```

For the full ABFE walkthrough see [:material-page-previous: here](../tutorial/abfe.md).

Legacy Complex workflows can still convert poses to ligands via `poses.to_ligand_set()`.
