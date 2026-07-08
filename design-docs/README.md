# Mol* JS migration — design docs

Strangler-fig migration from the legacy `deeporigin-molstar` Python package
(balto.biosim.ai `gallery.js`) to the hosted `molstarLib` bundle at
`https://os.dev.deeporigin.io/molstar/latest/index.js` (built from
`platform-ui/packages/molstar`).

## Documents

| # | Doc | Scope | Status |
|---|-----|-------|--------|
| 1 | [01-molstar-visualization-inventory.md](./01-molstar-visualization-inventory.md) | Full visualization inventory, API mapping, phased rollout | Active |
| ADR | [../docs/adr/0001-docking-box-without-exported-box3d.md](../docs/adr/0001-docking-box-without-exported-box3d.md) | Duck-typed Box3D until PUI-2203 | Accepted |

## Migration status

| Phase | Visualization | SDK entry points | Status |
|-------|---------------|------------------|--------|
| 1 | Protein structure | `Protein.show()`, `PreparedSystem.show()` | **Done** |
| 2 | Protein + binding pockets | `Protein.show(pockets=...)` | **Done** |
| 3 | Ligand 3D | `Ligand.show()`, `LigandSet.show()` | **Done** |
| 4 | Protein + docked poses | `Protein.show(poses=...)` | **Done** |
| 5 | Protein + pockets + poses | `Protein.show(pockets=..., poses=...)` | **Done** |
| 6 | Docking search box | `Docking.show_box()`, `ConstrainedDocking.show_box()` | **Done** |
| 7 | MD trajectory | `ABFE.show_trajectory()` | Pending |
| 8 | Remove `deeporigin-molstar` dep | `visualize.py`, static doc embeds | Pending |

## Bundle delivery

The CLI loads the hosted molstarLib IIFE from `os.dev.deeporigin.io/molstar/latest/`.
Icon assets resolve via `<base href="https://os.deeporigin.io/host/">`. The bundle is
not vendored into the CLI package — platform-ui owns releases. Revisit a
`DEEPORIGIN_MOLSTAR_JS_URL` env override only if offline notebooks become a hard
requirement.

## Verification notebook

Develop in `docs/notebooks/dirty/` (gitignored), then promote to
`docs/notebooks/clean/` via `bash scripts/notebooks.sh`.

| Notebook | Purpose |
|----------|---------|
| [`docs/notebooks/clean/molstar-visualization-catalog.ipynb`](../docs/notebooks/clean/molstar-visualization-catalog.ipynb) | Unified progress dashboard — one section per inventory visualization (#1–#8), with ✅/⏳ status badges |

The older phase-1-only notebook (`molstar-protein-view.ipynb`) remains for reference;
new verification work should go in the catalog notebook.
