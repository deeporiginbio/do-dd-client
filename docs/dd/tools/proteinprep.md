# ProteinPrep

Inventory and prepare a [`Protein`](../ref/protein.md) with one configurable
`ProteinPrep` object. Recommendation identifies chains, ligands, cofactors, and
waters. Preparation applies your keep/skip decisions, protonates the structure,
and optionally models missing loops. Optional
[`find_pockets`](../ref/protein_prep.md) finds pockets on the prepared
structure via `find_pockets` (`"no"`, `"novel"`, or `"from-crystal-ligand"`).
Selection-defined pockets require the standalone Pocket Finder tool.

Use standalone [`StructureReport`](structure-report.md) for structure assessment
(source or prepared). Protein Prep v10 does not bundle Structure Reports in tool
outputs.

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

`prep.recommendation` is a
[pandas :octicons-link-external-16:](https://pandas.pydata.org/) DataFrame of
inventoried components. Columns include the analyzer's frozen `recommendation`
tag and your live `decision`. Each read reflects the current Selection:

```{.python notest}
prep.recommendation[prep.recommendation["decision"] == "review"]
```

The analyzer JSON is `prep.recommendation_payload`. `prep.selection` is the
editable decision map and returns a defensive copy.

Resolve every `review` decision before preparation. `keep()`, `skip()`, and
`extract()` accept component IDs, a filtered DataFrame, or keyword matchers
(`kind`, `subtype`, `decision`). Matchers are equivalent to passing the
matching IDs. Ligands use `keep` or `extract` (not `skip`); calling `skip()`
on a ligand id stores `extract`:

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

## Blocking prepare (`run()`)

`run()` blocks until served prepare completes (loops on or off). Disable loop
modelling when you want a faster loops-off path:

```{.python notest}
prep.model_missing_loops = False
prepared = prep.run()
```

`run()` returns a registered [`Protein`](../ref/protein.md) for the prepared
structure: a new platform row whose `remote_path` points to the prepared
Protein Data Bank (PDB) file under `entities/proteins/prepared/`. The original
input protein is unchanged. The prepared PDB carries a
[`REMARK  99 DO_PREPARED`](../ref/prepared_protein_stamp.md) stamp; pass that
`Protein` into Pocket Finder or other tools without re-serializing the file so
the stamp stays intact. To stamp a structure you prepared outside Deep Origin
(PDB or mmCIF), use [`Protein.mark_as_prepared()`](../ref/prepared_protein_stamp.md).

Blocking or asynchronous preparation may also use `start()`:

```{.python notest}
prep.start()
prep.wait()
prepared = prep.get_results()
```

## Prepare with loop modelling or pockets

Loop modelling is enabled by default. All prepare paths use
`deeporigin.protein-prep` v10. Blocking `run()` supports served prepare
(including loops on). `find_pockets="novel"` uses the platform workflow path —
use `start()` (not `run()`):

```{.python notest}
from deeporigin.drug_discovery import ProteinPrep

prep = ProteinPrep(protein=protein)
prep.find_pockets = "novel"
prep.pocket_count = 3
prep.pocket_min_size = 80
prep.recommend()
prep.skip(decision="review")
prep.start(quote=True)
# inspect prep.estimate, then:
prep.confirm()
prep.wait()
prepared = prep.get_results()
pockets = prep.get_pockets()
extracted = prep.get_crystal_poses()
```

Register the input protein before prepare (`protein.sync()` or an existing
`protein.id`). Loop modelling requires a four-character PDB ID.

With loops off, `from-crystal-ligand` stays on standalone Protein Prep and can
use either `run()` or `start()`:

```{.python notest}
prep = ProteinPrep(
    protein=protein,
    selection=saved_selection,
    model_missing_loops=False,
    find_pockets="from-crystal-ligand",
    component_id="ligand:LIG:A:100",
)
prepared = prep.run()
pockets = prep.get_pockets()
```

Loop modelling requires a four-character
[Protein Data Bank (PDB) :octicons-link-external-16:](https://www.rcsb.org/)
ID. `ProteinPrep` initially uses `protein.pdb_id` when available; otherwise set
`prep.pdb_id` before submission.

`get_pockets()` raises when pockets were not part of the run, returns `None`
while still pending, and returns `[]` for a valid zero-pocket result. After prepare, ligands marked ``extract`` in the
Selection are available from ``get_crystal_poses()`` as a
:class:`~deeporigin.drug_discovery.structures.pose.PoseSet` (each
:class:`~deeporigin.drug_discovery.structures.pose.Pose` carries prepared
``protein_id``, ``ligand_id``, ``origin: cocrystal``, and
``component_id``). Crystal pockets from the same run expose
``Pocket.origin`` (``from-crystal-ligand``), ``component_id``, ``ligand_id``,
and ``ligand_name`` on :class:`~deeporigin.drug_discovery.Pocket`. That method
returns an empty set when prepare
finished with no extractions and ``None`` while outputs are still pending.

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
`selection`, `model_missing_loops`, and `pocket`.

`run()` or `start()` binds the object to the durable preparation execution and
sets `prep.id`. From that point onward, configuration is permanently frozen.
When you omit `name`, those methods label the execution from the current
settings—for example `Preparing 1EBY`, `Preparing and loop modelling 1EBY`, or
`Preparing, loop modelling, and finding pockets 1EBY` (PDB ID when set,
otherwise the protein name). Displaying the object shows its configuration, a
Selection summary, recommendation component count, and—after
submission—execution `id` and `status`. Jupyter HTML omits `progress` (platform
reports are large nested trees); inspect `prep.progress` when needed. Display
`prep.recommendation` to see the component table.

Direct loops-off preparation does not require a cost quote. Novel pocket
composite runs are billable: use `start(quote=True)` then `confirm()`, or pass
`approve_amount`.

## Reconnect to an execution

Reconnect to a durable preparation or historical recommendation execution from
either routed tool:

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
