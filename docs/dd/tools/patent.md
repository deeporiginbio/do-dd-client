# Patent

Extract chemical structures from a patent or chemistry PDF with the Deep Origin
Patent tool ("DO Patent"). `Patent` is a served tool backed by the platform tool
`deeporigin.draco`: it reads the pages of a PDF, detects drawn molecules, and
predicts a SMILES string for each one, together with a confidence score and the
page it was found on.

`Patent` is an **async** tool: submit the job with `start()`, track it with
`watch()` or `wait()`, then read the extracted structures with `get_results()`.

## Workflow

The lifecycle mirrors the other async tools (see
[Tools on Deep Origin](overview.md)):

1. Create a `Patent` job from a local `.pdf`.
2. Estimate the cost with `start(quote=True)` and inspect `estimate`.
3. `confirm()` the quoted execution to run it.
4. Track progress with `watch()`, or block with `wait()`.
5. Read the extracted structures with `get_results()`.

The PDF is validated on construction (it must exist and end in `.pdf`) and is
uploaded to Deep Origin storage automatically on `start()`.

## Extracting structures

```{.python notest}
from deeporigin.drug_discovery import Patent

# Point at a local PDF; the file is validated immediately.
patent = Patent(pdf="path/to/patent.pdf")

# Upload and quote without running.
patent.start(quote=True)
patent.estimate  # estimated cost

# Confirm to run, then wait for completion.
patent.confirm()
patent.wait()

# One row per extracted molecule.
df = patent.get_results()
df.head()
```

In a notebook, replace `patent.wait()` with `await patent.watch()` to render a
live progress card. When executing a notebook headlessly (for example with
`nbconvert`), set `JOB_WATCH_BLOCK=1` or call `await patent.watch(blocking=True)`
so the cell blocks until the job finishes.

## Results

`get_results()` returns a `pandas.DataFrame` with one row per extracted molecule,
or `None` until the job has succeeded. The main columns are:

| Column | Description |
| --- | --- |
| `smiles` | The predicted chemical structure |
| `name` | IUPAC name, when available |
| `page` | The PDF page the molecule was found on |
| `confidence` | Model confidence for the prediction |
| `type` | Structure type flag |
| `record_id` | Identifier for the extracted structure record |
| `source` | Provenance of the extracted structure |

## Existing executions

Every execution has an ID. Reconstruct a `Patent` object from that ID in a later
session and re-fetch its results without re-running the extraction:

```{.python notest}
patent = Patent.from_id("<executionId>")
df = patent.get_results()
```

If you already have the execution payload from `client.executions.get`, use
`Patent.from_dto(dto)` instead. You can also list previous runs and resume the
most recent one with `Patent.list()` and `Patent.from_last_run()`.

See the [API reference](../ref/patent.md) for the full signature.
