# RBFE

Plan, run, and inspect Relative Binding Free Energy (RBFE) workflows in Deep Origin.

This page covers the tools around an RBFE run: planning and visualizing a ligand
network, inspecting prepared systems, and reading results. For an end-to-end walk
through of submitting a run, see the [RBFE tutorial](../tutorial/rbfe.md).

The `RBFE` class follows the [common tool lifecycle](./overview.md): construct it,
`start(quote=True)` to estimate cost, `confirm()`, then `watch()` for progress.
It is submitted asynchronously, so your notebook stays responsive while it runs.

## Planning and visualizing a network

When you pass a `ligands` set to `RBFE`, the workflow plans the pairwise network
for you. To see or tune that network *before* submitting a full run, run
Konnektor on its own:

```{.python notest}
from deeporigin.drug_discovery import Konnektor

kn = Konnektor(ligands=ligands, network_type="mst")
network = kn.run()

network.show_network()   # interactive network view in the notebook
network.pairs            # list of (ligand, ligand) tuples
network.is_connected     # True if every ligand is reachable
```

`show_network()` renders an interactive graph:

<iframe
    src="../../images/network.html"
    width="100%"
    height="600"
    style="border:none;"
    title="Ligand network"
></iframe>

`network.pairs` can be fed straight into `RBFE(protein=..., pairs=network.pairs)`
if you want to review the plan first and submit the FEP step separately. Konnektor
runs synchronously and is inexpensive, so it's a cheap way to sanity-check
connectivity before spending on simulation.

Choose `network_type` based on the trade-off you want:

- `"mst"` — minimum spanning tree; fewest edges, lowest cost, no redundancy.
- `"star"` — all ligands connected to one reference.
- `"cyclic"` — redundant edges that form cycles, enabling consistency checks.

## Inspecting prepared systems

System preparation builds two solvated models per pair — a **binding** system
(protein + ligand) and a **solvation** system (ligand alone). Once the
system-prep step of your run finishes, load and visualize a prepared system:

```{.python notest}
# Any prepared system from this run (first available):
system = rbfe.get_prepared_system()
system.show()

# A specific pair, when the run has many:
system = rbfe.get_prepared_system(
    ligand1_id=ligand1.id,
    ligand2_id=ligand2.id,
)
system.show()
system.show(solute=True)   # solute-only view, when available
```

You will see something like:

<iframe
    src="../../images/prepared-system.html"
    width="100%"
    height="660"
    style="border:none;"
    title="Prepared system"
></iframe>

You do not need to wait for the whole run to finish — prepared systems become
available as soon as the system-prep step completes. If no prepared-system rows
exist yet, `get_prepared_system()` raises an error telling you to wait or to pass
`ligand1_id`/`ligand2_id` to disambiguate.

## Reading results

### Pairwise ΔΔG

After the RBFE step completes, `get_results()` returns one row per pair:

```{.python notest}
rbfe.get_results()
```

| protein_id | ligand1_id | ligand2_id | ddG            |
|------------|------------|------------|----------------|
| prot-...   | lig-...    | lig-...    | -1.23 kcal/mol |

`ddG` is the relative binding free energy difference between `ligand1` and
`ligand2`, formatted with its unit. A more negative `ddG` means `ligand2` binds
more tightly than `ligand1`.

### Per-ligand absolute dG (cycle closure)

If you submitted the run with `exp_abfe` and/or `fep_abfe` anchors, the
`cycle-closure` step converts the pairwise network into absolute per-ligand
values:

```{.python notest}
rbfe.get_cycle_closure_results()
```

| ligand_id | dG   | unit     | cluster |
|-----------|------|----------|---------|
| lig-...   | -9.9 | kcal/mol | 0       |

`cluster` groups ligands that are connected in the network; ligands in separate,
unconnected clusters cannot be placed on the same absolute scale. See the
[RBFE tutorial](../tutorial/rbfe.md#converting-to-absolute-binding-free-energy)
for how to supply anchors.

### Tool logs

To see what the underlying tools reported during the run — useful for
diagnosing a failure or slow step:

```{.python notest}
df = rbfe.get_user_logs()
df
```

## Working with existing runs

Reconnect to a run started earlier, in this or a previous session:

```{.python notest}
# By execution id:
rbfe = RBFE.from_id("<executionId>")

# Or the most recently created RBFE run:
rbfe = RBFE.from_last_run()

rbfe.sync()          # refresh status from the platform
rbfe.get_results()
```

This rehydrates the stored inputs (steps, protein, ligands/pairs, prepared
systems, parameters) so you can check status, watch progress, or fetch results
without re-specifying anything.

## Troubleshooting

- **No results yet** — RBFE runs asynchronously. Call `rbfe.sync()` and confirm
  the status is `Completed` before expecting `get_results()` to return rows.
- **`get_prepared_system()` raises** — the system-prep step hasn't produced rows
  yet, or several pairs match. Wait, or pass `ligand1_id`/`ligand2_id`.
- **Empty cycle-closure results** — cycle closure only runs when you pass
  `exp_abfe` or `fep_abfe`; check that `"cycle-closure"` is in `rbfe.steps`.
- **Konnektor network not connected** — `network.is_connected` is `False` when
  ligands are too dissimilar to map; try `network_type="star"` or curate the set.

## Additional resources

- [RBFE tutorial](../tutorial/rbfe.md)
- [RBFE reference](../ref/rbfe.md) (generated API docs)
- [Work with Ligands](../how-to/ligands.md#constructing-a-network-using-konnektor)
