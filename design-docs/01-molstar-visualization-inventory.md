# Mol* visualization inventory

Audit of all Jupyter 3D visualizations in `do-dd-client` that use the legacy
`deeporigin-molstar` package (source: `biosim_molstar` repo), and the planned
replacement with the hosted `molstarLib` bundle.

## Architecture

**Today:** Python viewer classes (`ProteinViewer`, `MoleculeViewer`,
`DockingViewer`) build self-contained HTML that loads
`https://balto.biosim.ai/molstar/gallery.js` and calls
`deepOriginMolstar.Viewer` + `Renderer`.

**Target:** In-client HTML builder (`deeporigin.viz.molstar_html`) loads
`https://os.dev.deeporigin.io/molstar/latest/index.js` and calls
`molstarLib.initViewer()` + `viewer.api.*`.

**Display:** Both paths render in notebooks via
`deeporigin.utils.notebook.render_html()` (iframe with base64 `src` and
`sandbox="allow-scripts allow-same-origin"`). Do not use raw `srcdoc` — the HTML
spec sandboxes srcdoc documents without `allow-scripts`, which blocks Mol*.

## Visualization inventory

| # | Visualization | SDK entry point | Legacy viewer / method | New `molstarLib` API | Phase |
|---|---------------|-----------------|------------------------|----------------------|-------|
| 1 | Protein structure | `Protein.show()`, `PreparedSystem.show()` | `ProteinViewer.render_protein()` | `initViewer` + `loadFromRawContent` | **1** |
| 2 | Protein + binding pockets | `Protein.show(pockets=...)` | `ProteinViewer.render_protein_with_pockets()` | `renderStructureAndPockets` | 2 |
| 3 | Single ligand 3D | `Ligand.show()`, `Ligand._repr_html_()` | `MoleculeViewer.render_ligand()` | `loadFromRawContent` (sdf) | 3 |
| 4 | Ligand set 3D | `LigandSet.show()` | `MoleculeViewer.render_ligand()` (combined SDF) | `loadFromRawContent` or `loadAndMerge` | 3 |
| 5 | Protein + docked poses | `Protein.show(poses=...)` | `DockingViewer.render_with_separate_crystal()` | `visualizeDockedLigands` | 4 |
| 6 | Docking search box | `Docking.show_box()`, `ConstrainedDocking.show_box()` | `DockingViewer.render_bounding_box()` | `loadFromRawContent` + `renderBoundingBox` | 5 |
| 7 | MD trajectory | `ABFE.show_trajectory()` | `ProteinViewer.render_trajectory()` | `loadWithTrajectory` | 6 |
| 8 | Notebook HTML wrapper | `@jupyter_visualization`, ABFE direct call | `JupyterViewer.visualize()` | Reuse `render_html()` only | 7 |

**Out of scope:** `render_smiles_in_dataframe()` in
`src/drug_discovery/utils/visualize.py` — RDKit 2D only.

## Source file touch list

| File | What it does today |
|------|-------------------|
| `src/drug_discovery/structures/protein.py` | `Protein.show()` — protein, pockets, docked poses |
| `src/drug_discovery/structures/prepared_system.py` | `PreparedSystem.show()` — protein-only |
| `src/drug_discovery/structures/ligand.py` | `Ligand.show()`, `LigandSet.show()` — ligand 3D |
| `src/drug_discovery/docking.py` | `Docking.show_box()` |
| `src/drug_discovery/constrained_docking.py` | `ConstrainedDocking.show_box()` |
| `src/drug_discovery/abfe.py` | `ABFE.show_trajectory()` |
| `src/drug_discovery/utils/visualize.py` | `@jupyter_visualization` → `JupyterViewer.visualize()` |

## Legacy → new API mapping

| Legacy `Renderer` / viewer method | New `viewer.api` method |
|--------------------------------|-------------------------|
| `renderStructureExplicitly` | `loadFromRawContent` |
| `renderStructureAndPockets` | `renderStructureAndPockets` |
| `renderLigand` | `loadFromRawContent` (sdf/mol2) |
| `renderStructureWithSeperateCrystal` | `visualizeDockedLigands` |
| `renderLigandWidthBoundingBox` / `render_bounding_box` | `loadFromRawContent` then `renderBoundingBox` |
| `renderStructureWithTrajectory` | `loadWithTrajectory` |

## Phase notes

### Phase 1 — protein only

- New module: `src/viz/molstar_html.py`
- Wire: `Protein.show()` when no pockets/ligands; `PreparedSystem.show()`
- Notebook: `docs/notebooks/clean/molstar-protein-view.ipynb`

### Phase 2 — pockets

Map `Pocket.color` to `PocketData` (`{ data, color: { name, value }, label }`).

### Phase 5 — bounding box

New API requires a loaded structure ref before `renderBoundingBox` — generated
JS loads protein first, then draws the box mesh.

### Phase 6 — trajectory

XTC is binary; embed as base64 in HTML (legacy package does this today).
`loadWithTrajectory` is available in `platform-ui/packages/molstar`.

### Phase 7 — cleanup

- Remove `deeporigin-molstar` from `tools` extra in `pyproject.toml`
- Simplify `visualize.py` to use `render_html` only (drop `JupyterViewer`)
- Refresh static embeds in `docs/images/*.html`

## Tests

| File | Coverage |
|------|----------|
| `tests/test_molstar_html.py` | Phase 1 HTML generation |
| `tests/test_docking.py` | Mocks `DockingViewer` for `show_box` (phase 5) |

## Static doc embeds

Pre-rendered HTML in `docs/images/` still reference legacy `gallery.js`.
Update in phase 7 when all renderers are ported.
