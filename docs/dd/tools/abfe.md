# ABFE

Run and analyze Absolute Binding Free Energy (ABFE) workflows in Deep Origin.

!!! warning "Deprecated: `Complex` in examples"
    Older examples referenced a legacy [`Complex`](../ref/complex.md). Prefer the [`ABFE`](../ref/abfe.md) class directly for new code.

## Visualizing trajectories

ABFE simulations generate molecular dynamics trajectories that show how ligands interact with proteins over time. Visualizing these trajectories can provide valuable insights into binding mechanisms, protein-ligand interactions, and conformational changes.

Use :meth:`ABFE.show_trajectory <deeporigin.drug_discovery.abfe.ABFE.show_trajectory>` on a completed execution. Each ABFE job is tied to one prepared system (one primary ligand leg), so you do not pass a separate ligand object: the execution already identifies the run.

### Prerequisites

- A completed ABFE simulation run (`status` is `Completed`)
- Results should include `solute_pdb_file_path` for **binding** trajectories,
  `solvation_xml_ligand_file_path` for **solvation** trajectories (ligand atoms
  only in the XTC; ions and solvent are omitted), and `system_pdb_file_path` for
  the post-prep MD trajectory.
- The Deep Origin Python package properly installed and configured

### `show_trajectory`

The method loads the data-platform result row for this job (the same shape as ``client.results.get(compute_job_id=abfe.id)``), reads remote file paths from that payload, downloads the structure (PDB) and trajectory (XTC), and opens a Mol* viewer in the notebook via :func:`deeporigin.utils.notebook.render_html`.

**Steps**

| `step` value   | What is shown |
|----------------|----------------|
| `md`           | Post-prep MD under `tool-runs/<id>/protein/ligand/simple_md/.../_allatom_trajectory_40ps.xtc` (path derived from binding/solvation trajectory paths in results). |
| `binding`      | `binding_analysis[*].trajectories["window_<n>"]` — e.g. `solute_trajectory_20ps.xtc` per lambda window. |
| `solvation`    | Same layout under `solvation_analysis`. |

**Parameters**

- `step`: `"md"`, `"binding"`, or `"solvation"`.
- `window`: Lambda window index, starting at `1`. Used for `binding` and `solvation` only; ignored for `md`.
- `repeat`: Which repeat block to use inside `binding_analysis` / `solvation_analysis` (matches the `repeat` field when present, otherwise 1-based index in the list).
- `show_progress`: In Jupyter, show a compact progress bar while resolving paths and downloading files (default: on in notebooks). Pass `show_progress=False` to disable.

### Behind the scenes

1. Sync execution status and require `Completed`.
2. Fetch results with `compute_job_id` set to the execution id.
3. Resolve the XTC path from the result `data` (per step/window/repeat as above).
4. Resolve the matching topology: solute PDB for binding, solvation XML (converted
   to PDB) for solvation, full system PDB for MD.
5. Download PDB and XTC (lazy skip if already cached under `~/.deeporigin/`).
   Historical solute PDBs containing retained waters are filtered only when the
   resulting atom count exactly matches the XTC.
6. Build hosted molstarLib HTML via :func:`deeporigin.viz.molstar_html.render_trajectory_html` and display with :func:`deeporigin.utils.notebook.render_html`.

### Examples

Assume `abfe` is an :class:`~deeporigin.drug_discovery.abfe.ABFE` instance that has finished successfully.

To reopen a past run by execution id (no in-memory ``PreparedSystem`` required):

```{.python notest}
from deeporigin.drug_discovery.abfe import ABFE
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()
client.project_id = None  # or match the execution's projectId
abfe = ABFE.from_id("your-execution-uuid", client=client)
abfe.show_trajectory(step="binding", window=1)
```

:meth:`ABFE.from_id` copies ``projectId`` from the execution onto ``client.project_id`` when present, so result-explorer queries use the same project scope as the run.

```{.python notest}
# Post-prep MD trajectory
abfe.show_trajectory(step="md")
```

```{.python notest}
# Binding leg, default window 1
abfe.show_trajectory(step="binding")

# Binding leg, window 5
abfe.show_trajectory(step="binding", window=5)

# Solvation leg, second repeat if present
abfe.show_trajectory(step="solvation", window=3, repeat=2)
```

If `window` is not present in the results `trajectories` map, the error lists the valid window indices.

<iframe
    src="../../images/prepared-system.html"
    width="100%"
    height="600"
    style="border:none;"
    title="Protein visualization"
></iframe>

### Troubleshooting

- Ensure the ABFE run completed successfully (`Completed`).
- Ensure the run recorded a topology whose atom count matches the trajectory.
- For binding/solvation, use a `window` that exists in the results `trajectories` keys (`window_1`, …).
- Ensure you have disk space and network access for downloads into the local Deep Origin cache.

## Working with existing runs

Reconnect to a run started earlier, in this or a previous session:

```{.python notest}
# By execution id:
abfe = ABFE.from_id("<executionId>")

# Or the most recently created ABFE run:
abfe = ABFE.from_last_run()

abfe.sync()            # refresh status from the platform
abfe.get_results()
```

This rehydrates the stored inputs so you can check status, watch progress, fetch
results, or visualize trajectories without re-specifying anything.

## Additional resources

- [ABFE tutorial](../tutorial/abfe.md)
- [ABFE reference](../ref/abfe.md) (generated API docs)
