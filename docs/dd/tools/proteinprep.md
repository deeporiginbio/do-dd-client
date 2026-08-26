# ProteinPrep

Inventory and prepare a [`Protein`](../ref/protein.md) with one configurable
`ProteinPrep` object. Recommendation identifies chains, ligands, cofactors, and
waters. Preparation applies your keep/skip decisions, protonates the structure,
and optionally models missing loops.

## Recommend and review

Create the object and request recommended settings. `recommend()` blocks,
returns `None`, and updates both `recommendation` and `selection`. It does not
bind the object to the temporary recommendation execution.

```{.python notest}
from deeporigin.drug_discovery import BRD_DATA_DIR, Protein, ProteinPrep

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
prep = ProteinPrep(protein=protein)
prep.recommend()
```

`prep.recommendation` contains the complete analyzer evidence.
`prep.selection` contains the editable decisions. Both properties return
defensive copies.

Recommendations may mark ambiguous components as `review`. Resolve them before
preparation with the component IDs from `prep.recommendation`:

```{.python notest}
prep.keep(["chain:A", "cofactor:HEM:A:200"])
prep.skip(["ligand:LIG:A:100"])
```

`keep()` and `skip()` change only the IDs you name. They reject unknown IDs.
Preparation reports any unresolved `review` IDs instead of silently skipping
them.

You may call `recommend()` again before preparation. A successful refresh
replaces the recommendation and Selection. If refresh fails, the previous
successful settings remain intact.

## Prepare without loop modelling

Disable loop modelling to use blocking preparation:

```{.python notest}
prep.model_missing_loops = False
prepared = prep.run()
```

`run()` returns an in-memory [`Protein`](../ref/protein.md) whose
`remote_path` points to the prepared Protein Data Bank (PDB) file. It has no
platform protein ID until you call `sync()` or `update()`. The original input
protein is unchanged.

Loops-off preparation may also run asynchronously:

```{.python notest}
prep.start()
prep.wait()
prepared = prep.get_results()
```

## Prepare with loop modelling

Loop modelling is enabled by default and may take longer, so use `start()`:

```{.python notest}
prep.pdb_id = "1EBY"
prep.model_missing_loops = True
prep.start()
prep.wait()
prepared = prep.get_results()
```

Loop modelling requires a four-character
[Protein Data Bank (PDB) :octicons-link-external-16:](https://www.rcsb.org/)
ID. `ProteinPrep` initially uses `protein.pdb_id` when available; otherwise set
`prep.pdb_id` before submission.

## Use a saved Selection

Advanced callers can skip recommendation by passing or assigning a saved
Selection:

```{.python notest}
prep = ProteinPrep(
    protein=protein,
    selection=saved_selection,
    model_missing_loops=False,
)
prepared = prep.run()
```

A Selection contains `source_sha256`, `analyzer_version`, and a `decisions`
mapping. Assignment copies and validates it. Local decisions may contain
`review`, but all reviews must become `keep` or `skip` before preparation.

## Object lifecycle

`protein` is constructor-only. Before preparation, you may change `pdb_id`,
`selection`, and `model_missing_loops`.

`run()` or `start()` binds the object to the durable preparation execution and
sets `prep.id`. From that point onward, configuration is permanently frozen.
Displaying the object shows its configuration, a Selection summary,
recommendation availability, and—after submission—execution status and
progress.

This tool does not produce a cost quote, so Protein Prep methods have no
`quote` or `approve_amount` arguments.

## Reconnect to an execution

Reconnect to a durable preparation or historical recommendation execution:

```{.python notest}
prep = ProteinPrep.from_id("<executionId>")
# Or:
prep = ProteinPrep.from_last_run()
```

For preparation executions, call `sync()` and `get_results()`. Historical
recommendation executions expose their evidence through `prep.recommendation`.
The internal platform operation is deliberately not exposed as user-settable
`action`.
