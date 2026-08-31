# PocketFinder

Find pockets in a [`Protein`](../ref/protein.md) using the Deep Origin Pocket Finder.

## Creating pockets

First, create a protein, for example:

```{.python continuation}
from deeporigin.drug_discovery import Protein, BRD_DATA_DIR

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
protein.remove_water()
```

### Using Pocket Finder

Use the `PocketFinder` class from `deeporigin.drug_discovery.pocket_finder` to
find pockets. `PocketFinder` supports synchronous and asynchronous execution.

#### Estimating cost

To estimate cost without starting the run, pass `quote=True` to `run()` or
`start()`. This populates `pf.estimate` and leaves the execution in a quoted
state.

```{.python notest}
from deeporigin.drug_discovery import PocketFinder

pf = PocketFinder(protein, pocket_count=1)
pf.run(quote=True)
pf.estimate
```

When you are ready to proceed, confirm the quoted execution:

```{.python notest}
pf.confirm()
pockets = pf.get_results()
```

#### Synchronous

Use `run()` when you want to submit the execution and wait for the result in the
same cell or script.

```{.python continuation}
from deeporigin.drug_discovery import PocketFinder

pf = PocketFinder(protein, pocket_count=1)
pockets = pf.run()
```

`pf.run()` returns a list of `Pocket` objects. You will be charged for each run
unless you request a quote first.

#### Define by selection

Use `mode="define-by-selection"` to build one pocket from residue, ligand, or
cofactor selectors plus a radius, instead of running the auto-find classifier.
Each selection is a dict with `kind` (`residue`, `ligand`, or `cofactor`) and
`author` fields that match the protein structure (`chain_id` is required;
`resseq`, `resname`, and `icode` as needed).

```{.python notest}
from deeporigin.drug_discovery import PocketFinder

pf = PocketFinder(
    protein,
    mode="define-by-selection",
    selections=[
        {
            "kind": "ligand",
            "author": {"chain_id": "A", "resname": "LIG"},
        }
    ],
    pocket_radius=10.0,
    align_to_pocket=True,
)
pockets = pf.run()
```

- `pocket_radius` is the half-edge of the docking cube in angstroms (default
  `10`). Lab and box sizes are `2 * pocket_radius`.
- `align_to_pocket=True` orients the box from a principal component analysis
  (PCA) of the selected atoms.
- Do not pass `pocket_count` or `pocket_min_size` in this mode.
- Exact matching of selections happens on the platform; the client only checks
  structural shape and mode/kwargs consistency.

Result handling is the same as auto-find: `run()` / `get_results()` return a
list of `Pocket` objects (typically one). Classifier score fields on that
pocket may be null.

#### Asynchronous

For longer runs, or when you want to keep the notebook responsive, submit the
execution asynchronously with `start()`:

```{.python notest}
pf = PocketFinder(protein, pocket_count=5)
pf.start()

pf.wait()
pockets = pf.get_results()
```

In a notebook, you can use `watch()` to display progress while the execution is
running:

```{.python notest}
pf = PocketFinder(protein, pocket_count=5)
pf.start()
task = await pf.watch()
pf.wait()
pockets = pf.get_results()
```

To cancel an asynchronous execution that is queued or running, call `cancel()`:

```{.python notest}
pf.cancel()
```

#### Existing executions

You can reconstruct a `PocketFinder` object from an existing tools execution ID.
This is useful when reconnecting to an in-progress run, inspecting `estimate` or
`cost`, or fetching results in a later session.

```{.python notest}
pf = PocketFinder.from_id("<executionId>")
pf.sync()
pockets = pf.get_results()
```

To reconnect to the most recently created PocketFinder run without looking up its
ID, use `from_last_run()`:

```{.python notest}
pf = PocketFinder.from_last_run()
pf.sync()
pockets = pf.get_results()
```

If you already have the execution payload from `client.executions.get`, use
`PocketFinder.from_dto(dto)` instead.

You can also list previous PocketFinder executions:

```{.python notest}
executions = PocketFinder.list()
completed = PocketFinder.list(status=["Completed"])
```

### Using PDB files

Create a pocket directly from a PDB file:

```{.python notest}
from deeporigin.drug_discovery import Pocket

pocket = Pocket.from_pdb_file("path/to/pocket.pdb", name="my_pocket")
```

### Other ways to define a pocket

To define pockets from a residue number, a crystal ligand, or a standalone
ligand file without running PocketFinder, see
[Work with Pockets](../how-to/pockets.md). To build a docking box from
residue/ligand/cofactor selectors via the platform tool, use
[Define by selection](#define-by-selection) above.

### From a result-explorer record ID

Load a single pocket by its result-explorer record ID, such as an ID from a
previous pocket-finder run or from the platform UI:

```{.python notest}
from deeporigin.drug_discovery import Pocket

pocket = Pocket.from_id("your-pocket-record-id")
```

This fetches the record, downloads the pocket PDB file, and returns a `Pocket` with properties populated from the record. Optionally pass a `client` if you do not want to use the default:

```{.python notest}
pocket = Pocket.from_id("your-pocket-record-id", client=my_client)
```

If no record exists for the given ID, `ValueError` is raised.

## Visualization

### Inspecting pocket data

View pocket properties by simply inspecting the object:

```{.python notest}
pocket
```

You should see a table similar to:

```
    Pocket:
    ╭─────────────────────────┬──────────────╮
    │ Name                    │ pocket_1     │
    ├─────────────────────────┼──────────────┤
    │ Color                   │ red          │
    ├─────────────────────────┼──────────────┤
    │ Volume                  │ 545.0 Å³     │
    ├─────────────────────────┼──────────────┤
    │ Total SASA              │ 1560.474 Å²  │
    ├─────────────────────────┼──────────────┤
    │ Polar SASA              │ 762.11224 Å² │
    ├─────────────────────────┼──────────────┤
    │ Polar/Apolar SASA ratio │ 0.95459515   │
    ├─────────────────────────┼──────────────┤
    │ Hydrophobicity          │ 15.903226    │
    ├─────────────────────────┼──────────────┤
    │ Polarity                │ 17.0         │
    ├─────────────────────────┼──────────────┤
    │ Drugability score       │ 0.83243614   │
    ╰─────────────────────────┴──────────────╯
```


### 3D visualization in a protein

Each pocket from PocketFinder can show itself on its parent protein:

```{.python notest}
pockets[0].show()
```

That is sugar for `protein.show(pockets=[pockets[0]])`. To overlay every pocket from the run:

```{.python notest}
protein.show(pockets=pockets)
```

You should see something like:

<iframe
    src="../../images/pockets.html"
    width="100%"
    height="650"
    style="border:none;"
    title="Protein visualization"
></iframe>
