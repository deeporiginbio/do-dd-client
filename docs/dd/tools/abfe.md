# ABFE

Run and analyze Absolute Binding Free Energy (ABFE) workflows in Deep Origin.

!!! warning "Deprecated: `Complex` in examples"
    Older examples referenced a legacy [`Complex`](../ref/complex.md). Prefer the [`ABFE`](../ref/abfe.md) class directly for new code.

## Visualizing trajectories

ABFE simulations generate molecular dynamics trajectories that show how ligands interact with proteins over time. Visualizing these trajectories can provide valuable insights into binding mechanisms, protein-ligand interactions, and conformational changes.

Use :meth:`ABFE.show_trajectory <deeporigin.drug_discovery.abfe.ABFE.show_trajectory>` on a completed execution. Each ABFE job is tied to one prepared system (one primary ligand leg), so you do not pass a separate ligand object: the execution already identifies the run.

### Prerequisites

- A completed ABFE simulation run (`status` is `Succeeded`)
- `PreparedSystem` used for the run should include either `system_pdb_path` or `binding_xml_path` (the latter is used to resolve `system.pdb` next to the binding XML on the file store)
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

### Behind the scenes

1. Sync execution status and require `Succeeded`.
2. Fetch results with `compute_job_id` set to the execution id.
3. Resolve the XTC path from the result `data` (per step/window/repeat as above).
4. Resolve the system PDB from `PreparedSystem` (`system_pdb_path`, or `dirname(binding_xml_path)/system.pdb`).
5. Download PDB and XTC (lazy skip if already cached under `~/.deeporigin/`).
6. Render with `deeporigin_molstar.ProteinViewer.render_trajectory` and display in the notebook.

### Examples

Assume `abfe` is an :class:`~deeporigin.drug_discovery.abfe.ABFE` instance that has finished successfully.

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
    src="../../images/traj.html"
    width="100%"
    height="600"
    style="border:none;"
    title="Protein visualization"
></iframe>

### Troubleshooting

- Ensure the ABFE run completed successfully (`Succeeded`).
- Ensure `PreparedSystem.system_pdb_path` or `binding_xml_path` is set so the viewer can load the topology.
- For binding/solvation, use a `window` that exists in the results `trajectories` keys (`window_1`, …).
- Ensure you have disk space and network access for downloads into the local Deep Origin cache.

## Additional resources

- [ABFE tutorial](../tutorial/abfe.md)
- [ABFE reference](../ref/abfe.md) (generated API docs)
