# ProteinPrep

Inventory and prepare a [`Protein`](../ref/protein.md) with the Deep Origin
Protein Prep tool. The tool is two steps on one key:

1. **Recommend** inventories chains, ligands, cofactors, and waters.
2. **Prepare** applies a frozen keep/skip map (a Selection), then protonates
   and optionally runs loop modelling.

`start()` is always valid. Track those jobs with `wait()` or `watch()`, then
load results. `run()` is only valid when you skip loop modelling
(`model_missing_loops=False`): it blocks until the prepare job finishes and
returns the prepared protein. This tool does not produce a cost quote.

`get_results()` (after a prepare run) returns an in-memory
[`Protein`](../ref/protein.md) whose `remote_path` points at the prepared PDB.
That object has no platform protein id until you `sync()` or `update()` it. The
input protein on the `ProteinPrep` instance is unchanged.

## Recommending components

Create a protein, then a `ProteinPrep` with no selection. `start()` submits
`action=recommend`. After the job finishes, `get_recommendation()` returns the
component inventory.

```{.python notest}
from deeporigin.drug_discovery import Protein, ProteinPrep, BRD_DATA_DIR

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
rec = ProteinPrep(protein, pdb_id="1EBY")
rec.start()
rec.wait()
recommendation = rec.get_recommendation()
```

`pdb_id` is optional on recommend. If the protein already has `pdb_id` (for
example from `Protein.from_pdb_id`), or you pass it here, `as_prepare()` reuses
it for loop-modelling templates.

In a notebook, watch progress while the execution runs:

```{.python notest}
rec = ProteinPrep(protein, pdb_id="1EBY")
rec.start()
task = await rec.watch()
rec.wait()
recommendation = rec.get_recommendation()
```

## Preparing a protein

Turn the recommendation into a frozen Selection (every `review` becomes `skip`
by default). Skip loop modelling and block until the prepared protein is
ready:

```{.python notest}
prep = rec.as_prepare(model_missing_loops=False)
prepared = prep.run()
```

Loop modelling stays on by default. That path is longer, so submit with
`start()` instead of `run()`:

```{.python notest}
prep = rec.as_prepare()
prep.start()
prep.wait()
prepared = prep.get_results()
```

Or build the prepare run yourself from the recommendation dict:

```{.python notest}
prep = ProteinPrep.from_recommendation(protein, recommendation, pdb_id="1EBY")
```

The tool needs a 4-character
[Protein Data Bank (PDB) :octicons-link-external-16:](https://www.rcsb.org/)
ID for loop-modelling templates unless you skip loop modelling with
`model_missing_loops=False`.

You can edit the Selection before prepare. `selection_from_recommendation`
maps each component to `keep` or `skip`; pass `resolve_review_as="keep"` to
keep items the analyzer marked for review:

```{.python notest}
selection = ProteinPrep.selection_from_recommendation(
    recommendation,
    resolve_review_as="skip",
)
selection["decisions"]["chain:A"] = "keep"
prep = ProteinPrep(
    protein,
    selection=selection,
    model_missing_loops=False,
)
prepared = prep.run()
```

Displaying the object in a notebook or REPL lists every parameter you can
set and its current value (`action`, `pdb_id`, `selection`, and so on):

```{.python notest}
prep
```

## Working with existing runs

Reconnect to a Protein Prep run started earlier, in this or a previous session:

```{.python notest}
from deeporigin.drug_discovery import ProteinPrep

prep = ProteinPrep.from_id("<executionId>")
# Or the most recently created ProteinPrep run:
prep = ProteinPrep.from_last_run()

prep.sync()
if prep.action == "recommend":
    recommendation = prep.get_recommendation()
else:
    prepared = prep.get_results()
```
