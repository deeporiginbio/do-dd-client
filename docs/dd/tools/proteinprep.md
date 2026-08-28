# ProteinPrep

Inventory and prepare a [`Protein`](../ref/protein.md) with one configurable
`ProteinPrep` object. Recommendation identifies chains, ligands, cofactors, and
waters. Preparation applies your keep/skip decisions, protonates the structure,
and optionally models missing loops.

## Recommend and review

Create the object and request recommended settings. `recommend()` blocks,
returns a component table, and updates both `recommendation` and `selection`.
It does not bind the object to the temporary recommendation execution.

```{.python notest}
from deeporigin.drug_discovery import BRD_DATA_DIR, Protein, ProteinPrep

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
prep = ProteinPrep(protein=protein)
prep.recommend()
```

`prep.recommendation` is a table of inventoried components. Columns include
the analyzer's frozen `recommendation` tag and your live `decision`. Filter
with keyword arguments; the call returns a
[pandas :octicons-link-external-16:](https://pandas.pydata.org/) DataFrame:

```{.python notest}
prep.recommendation(decision="review")
```

The analyzer payload is `prep.recommendation.raw`. `prep.selection` is the
editable decision map and returns a defensive copy.

Resolve every `review` decision before preparation. `keep()` and `skip()`
accept component IDs, a filtered DataFrame, or keyword matchers (`kind`,
`subtype`, `decision`). Matchers are equivalent to passing the matching IDs:

```{.python notest}
prep.keep(kind="water")
prep.skip(decision="review")
prep.keep(["chain:A", "cofactor:HEM:A:200"])
```

Do not mix IDs with keyword matchers in one call. Unknown IDs are rejected.
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
protein is unchanged. The prepared PDB carries a
[`REMARK  99 DO_PREPARED`](../ref/prepared_protein_stamp.md) stamp; pass that
`Protein` into Pocket Finder or other tools without re-serializing the file so
the stamp stays intact.

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
recommendation component count, and—after submission—execution status and
progress. Display `prep.recommendation` to see the component table.

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
recommendation executions expose their component table through
`prep.recommendation`.
The internal platform operation is deliberately not exposed as user-settable
`action`.
