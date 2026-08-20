# RBFE

This document describes how to run a [relative binding free energy (RBFE) :octicons-link-external-16:](https://en.wikipedia.org/wiki/Free-energy_perturbation) workflow using Deep Origin tools.

RBFE compares two ligands bound to the same protein and reports the **difference**
in their binding free energies (ΔΔG). Run it across a series of related ligands to
rank them relative to one another before committing to synthesis.

With the `RBFE` class, you choose *what* to run by *what you pass in*; the
workflow `steps` are inferred for you:

| You pass | Inferred `steps` | Use when |
|----------|------------------|----------|
| `ligands=[...]` (+ `protein`) | `["konnektor", "system-prep", "rbfe"]` | You have a congeneric series (each ligand must already have a docked pose in the binding site — see [Docking](./docking.md)) and want the workflow to plan the pairwise network for you |
| `pairs=[(a, b), ...]` (+ `protein`) | `["system-prep", "rbfe"]` | You already know which ligand pairs you want to compare |
| `prepared_systems=[...]` | `["rbfe"]` | You've already prepared systems with [SystemPrep](../tools/systemprep.md) and only want the free energy perturbation (FEP) calculation |

Add `exp_abfe` and/or `fep_abfe` anchors to any of the above to also append a
`cycle-closure` step, which converts pairwise ΔΔG into per-ligand absolute dG.

You may pass exactly one of `ligands`, `pairs`, or `prepared_systems`.

## Prerequisites

We assume you have a protein and two or more ligands you want to compare. In this
tutorial we use a protein and ligands from the BRD4 example dataset.

```{.python notest}
from deeporigin.drug_discovery import (
    BRD_DATA_DIR,
    Ligand,
    Protein,
    RBFE,
)

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
protein.sync()

ligand1 = Ligand.from_sdf(BRD_DATA_DIR / "brd-2.sdf")
ligand1.sync()

ligand2 = Ligand.from_sdf(BRD_DATA_DIR / "brd-3.sdf")
ligand2.sync()
```

`sync()` uploads each structure and registers it on the data platform. This is
required: RBFE references proteins and ligands by their platform IDs and file
paths. For more details, see [:material-page-previous: Getting Started](./getting-started.md).

## Ways of running

There are three ways to run RBFE, one for each input you can pass (see the table
above). Pick the one that matches what you already have.

### Comparing specific pairs

If you already know which ligands to compare, pass them as `pairs`. Each tuple is
one ΔΔG calculation. The workflow prepares each pair and runs FEP:

```{.python notest}
rbfe = RBFE(
    protein=protein,
    pairs=[(ligand1, ligand2)],
)
rbfe.start(quote=True)
rbfe.estimate
```

Add more tuples to compare more pairs in a single execution (up to 20 pairs).

### Building a network automatically

For a congeneric series, pass the whole ligand set and let the workflow plan the
pairwise edges for you with Konnektor, then prep and run FEP on each edge:

```{.python notest}
from deeporigin.drug_discovery import LigandSet

ligands = LigandSet.from_dir(BRD_DATA_DIR)
for ligand in ligands:
    ligand.sync()

rbfe = RBFE(
    protein=protein,
    ligands=ligands,
    network_type="mst",
)
rbfe.start(quote=True)
rbfe.estimate
```

`network_type` controls how pairs are chosen:

- `"mst"` (default) — a minimum spanning tree: the fewest edges needed to connect
  every ligand. Cheapest, but no redundancy.
- `"star"` — every ligand connected to one central reference.
- `"cyclic"` — adds redundant edges so you can check consistency around cycles
  (see [cycle closure](#converting-to-absolute-binding-free-energy)).

To preview the network before submitting, or to run Konnektor on its own, see
[RBFE tools](../tools/rbfe.md#planning-and-visualizing-a-network).

### Reusing prepared systems

If you already prepared systems (for example with `SystemPrep`, or from a prior
run), skip prep and submit FEP only:

```{.python notest}
rbfe = RBFE(
    prepared_systems=[prepared_system_1, prepared_system_2],
)
rbfe.start(quote=True)
rbfe.estimate
```

Prepare a single pair separately with `SystemPrep(protein=..., pose1=...,
pose2=...).run()` — see [SystemPrep](../tools/systemprep.md).

## Converting to absolute binding free energy

RBFE gives you *relative* values (ΔΔG between pairs). To turn these into
*absolute* per-ligand values (dG), anchor the network with at least one known
absolute value and append cycle closure. Provide the anchor as `fep_abfe`
(computed by [absolute binding free energy (ABFE)](./abfe.md)) and/or `exp_abfe`
(measured experimentally):

```{.python notest}
anchor = [{"ligand_id": ligand1.id, "dG": -10.0}]

rbfe = RBFE(
    protein=protein,
    ligands=ligands,
    network_type="mst",
    fep_abfe=anchor,
)
assert rbfe.steps[-1] == "cycle-closure"
```

Passing an anchor appends `cycle-closure` to `steps` automatically. Each anchor
entry needs a string `ligand_id` and a numeric `dG` (in kcal/mol). Read the
per-ligand results back with `get_cycle_closure_results()` (see
[Results](#results)).

## Estimating costs

Before starting, quote the run to see the estimated cost in USD. `start(quote=True)`
works for any of the entry points above:

```{.python notest}
rbfe.start(quote=True)
rbfe.estimate
```

Cost scales with the number of pairs (or network edges) and the simulation length,
so quoting is especially worthwhile for large networks or production runs.

## Starting a run

Confirm the quoted price to start the execution:

```{.python notest}
rbfe.confirm()
```

Then monitor progress. In a notebook:

```{.python notest}
task = await rbfe.watch()
```

You will see a live progress widget similar to this. RBFE runs as a workflow, so
the widget shows a tree of steps rather than a single bar: the network is planned
(`konnektor`), then each pair is prepared and simulated, and finally the results
are combined. As the run progresses, more steps appear and turn green:

<iframe
    src="../../images/rbfe-running.html"
    width="100%"
    height="600"
    style="border:none;"
    title="Running RBFE Job"
></iframe>

To reconnect to a run in a later session, rehydrate it with
`RBFE.from_id("<executionId>")` or `RBFE.from_last_run()`.

## Parameters

RBFE simulation parameters are controlled via the `RBFEParams` dataclass. Defaults
are tuned for production runs; most users only adjust a few fields.

`RBFEParams` shares the same fields as [`ABFEParams`](./abfe.md#parameters), with
lower window defaults suited to relative calculations (`binding_n_windows=24` and
`solvation_n_windows=24`). The field you are most likely to change:

- `repeats` — number of independent repeats; more repeats tighten error estimates.

`RBFEParams` is a frozen dataclass. Use `dataclasses.replace()` to build a
modified copy and pass it to the constructor:

```python
from dataclasses import replace

from deeporigin.drug_discovery import RBFEParams

params = replace(RBFEParams(), repeats=3, temperature=300)
params
```

Fields changed from their defaults are marked with an asterisk (`*`) when printed.

!!! danger "Changing parameters may lead to simulation failures"
    Some parameters, such as `dt`, are constrained to specific ranges. Runs with
    out-of-range values are rejected, and moving parameters away from their
    defaults may cause simulations to fail.

## Results

After a run completes, fetch the pairwise ΔΔG summary:

```{.python notest}
df = rbfe.get_results()
df
```

This returns one row per pair:

| protein_id | ligand1_id | ligand2_id | ddG              |
|------------|------------|------------|------------------|
| prot-...   | lig-...    | lig-...    | -1.23 kcal/mol   |

If you ran cycle closure, also fetch the per-ligand absolute dG:

```{.python notest}
rbfe.get_cycle_closure_results()
```

| ligand_id | dG    | unit     | cluster |
|-----------|-------|----------|---------|
| lig-...   | -9.9  | kcal/mol | 0       |

To inspect a prepared system or plan/visualize a network, see
[RBFE tools](../tools/rbfe.md).

## Additional resources

- [RBFE tools](../tools/rbfe.md) — inspecting networks, prepared systems, and results
- [RBFE reference](../ref/rbfe.md) — generated API docs
- [ABFE tutorial](./abfe.md) — absolute binding free energy, used to anchor cycle closure
