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
| 1 | Protein structure | `Protein.show()`, `PreparedSystem.show()` | `ProteinViewer.render_protein()` | `initViewer` + `loadFromRawContent` | **1 Done** |
| 2 | Protein + binding pockets | `Protein.show(pockets=...)` | `ProteinViewer.render_protein_with_pockets()` | `renderStructureAndPockets` | **2 Done** |
| 3 | Single ligand 3D | `Ligand.show()`, `Ligand._repr_html_()` | `MoleculeViewer.render_ligand()` | `loadFromRawContent` (sdf) | **3 Done** |
| 4 | Ligand set 3D | `LigandSet.show()` | `MoleculeViewer.render_ligand()` (combined SDF) | `loadFromRawContent` (combined sdf) | **Rolled back** — multi-mol SDF not yet supported in molstarLib; keep legacy viewer |
| 5 | Protein + docked poses | `Protein.show(poses=...)` | `DockingViewer.render_with_separate_crystal()` | `visualizeDockedLigands` | **4 Done** |
| 6 | Protein + pockets + poses | `Protein.show(pockets=..., poses=...)` | *(not supported)* | `renderStructureWithPocketsAndLigands` | **5 Done** |
| 7 | Docking search box | `Docking.show_box()`, `ConstrainedDocking.show_box()` | `DockingViewer.render_bounding_box()` | `loadFromRawContent` + `renderBoundingBox` | **6 Done** |
| 8 | Protein + box + poses | `Docking.show_box(poses=...)`, `ConstrainedDocking.show_box(poses=...)` | *(not supported)* | `visualizeDockedLigands` + `renderBoundingBox` | **6b Done** |
| 9 | MD trajectory | `ABFE.show_trajectory()` | `ProteinViewer.render_trajectory()` | `loadWithTrajectory` | 7 |
| 10 | Notebook HTML wrapper | `@jupyter_visualization`, ABFE direct call | `JupyterViewer.visualize()` | Reuse `render_html()` only | 8 |

**Out of scope:** `render_smiles_in_dataframe()` in
`src/drug_discovery/utils/visualize.py` — RDKit 2D only.

## Source file touch list

| File | What it does today |
|------|-------------------|
| `src/drug_discovery/structures/protein.py` | `Protein.show()` — protein, pockets, docked poses, pockets+poses |
| `src/drug_discovery/structures/prepared_system.py` | `PreparedSystem.show()` — protein-only |
| `src/drug_discovery/structures/ligand.py` | `Ligand.show()`, `LigandSet.show()` — ligand 3D |
| `src/drug_discovery/docking.py` | `Docking.show_box()` |
| `src/drug_discovery/constrained_docking.py` | `ConstrainedDocking.show_box()` |
| `src/drug_discovery/abfe.py` | `ABFE.show_trajectory()` |
| `src/drug_discovery/utils/visualize.py` | `@jupyter_visualization` → `JupyterViewer.visualize()` |
| `src/viz/molstar_html.py` | Hosted molstarLib HTML builders |

## Legacy → new API mapping

| Legacy `Renderer` / viewer method | New `viewer.api` method |
|--------------------------------|-------------------------|
| `renderStructureExplicitly` | `loadFromRawContent` |
| `renderStructureAndPockets` | `renderStructureAndPockets` |
| `renderLigand` | `loadFromRawContent` (sdf/mol2) |
| `renderStructureWithSeperateCrystal` | `visualizeDockedLigands` |
| *(pockets + poses)* | `renderStructureWithPocketsAndLigands` |
| `renderLigandWidthBoundingBox` / `render_bounding_box` | `loadFromRawContent` then `renderBoundingBox` |
| *(box + poses)* | `visualizeDockedLigands` then `renderBoundingBox` |
| `renderStructureWithTrajectory` | `loadWithTrajectory` |

## Phase notes

### Phase 1 — protein only

- New module: `src/viz/molstar_html.py`
- Wire: `Protein.show()` when no pockets/ligands; `PreparedSystem.show()`
- Notebook: `docs/notebooks/clean/molstar-protein-view.ipynb`

### Phase 2 — pockets

- `render_protein_with_pockets_html()` in `src/viz/molstar_html.py`
- Wire: `Protein.show(pockets=...)`
- Map `Pocket.color` CSS strings → `PocketData.color.value` hex at render time
- Catalog notebook section #2 in `docs/notebooks/clean/molstar-visualization-catalog.ipynb`

### Phase 3 — ligand / ligand set

- `render_ligand_html()` → `loadFromRawContent` (sdf)
- Wire: `Ligand.show()` (single-mol SDF)
- `LigandSet.show()` remains on legacy `MoleculeViewer` until molstarLib
  correctly splits multi-molecule SDF files

### Phase 4 — protein + docked poses

- `render_protein_with_poses_html()` → `visualizeDockedLigands`
- Per-ligand SDF payloads; labels `name` → SMILES → `ligand-{i}`
- `sdf_file=` removed from `Protein.show` (Ligand / LigandSet only)

### Phase 5 — protein + pockets + poses

- `render_protein_with_pockets_and_poses_html()` →
  `renderStructureWithPocketsAndLigands`
- Catalog inventory row #6

### Phase 6 — bounding box

- `render_docking_box_html()` loads protein first, then `renderBoundingBox`
- Geometry from `resolve_docking_box_geometry` (center ± half-size)
- Duck-typed `{min,max}` until [PUI-2203](https://deeporigin.atlassian.net/browse/PUI-2203);
  see [ADR 0001](../docs/adr/0001-docking-box-without-exported-box3d.md)

### Phase 6b — protein + box + poses

- `render_protein_with_box_and_poses_html()` composes `visualizeDockedLigands`
  (returns structure ref) then `renderBoundingBox` on that ref
- Wire: `Docking.show_box(poses=...)`, `ConstrainedDocking.show_box(poses=...)`
- No dedicated molstarLib convenience method; CLI composes existing APIs
- Catalog inventory row #8

### Phase 7 — trajectory

XTC is binary; embed as base64 in HTML (legacy package does this today).
`loadWithTrajectory` is available in `platform-ui/packages/molstar`.

### Phase 8 — cleanup

- Remove `deeporigin-molstar` from `tools` extra in `pyproject.toml`
- Simplify `visualize.py` to use `render_html` only (drop `JupyterViewer`)
- Refresh static embeds in `docs/images/*.html`

## Tests

| File | Coverage |
|------|----------|
| `tests/test_molstar_html.py` | Phase 1–6 / 6b HTML generation |
| `tests/test_docking.py` | Mocks HTML builders for `show_box` / `show_box(poses=...)` |

## Static doc embeds

Pre-rendered HTML in `docs/images/` still reference legacy `gallery.js`.
Update in phase 8 when all renderers are ported.
