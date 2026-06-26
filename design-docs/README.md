# Mol* JS migration — design docs

Strangler-fig migration from the legacy `deeporigin-molstar` Python package
(balto.biosim.ai `gallery.js`) to the hosted `molstarLib` bundle at
`https://os.dev.deeporigin.io/molstar/latest/index.js` (built from
`platform-ui/packages/molstar`).

## Documents

| # | Doc | Scope | Status |
|---|-----|-------|--------|
| 1 | [01-molstar-visualization-inventory.md](./01-molstar-visualization-inventory.md) | Full visualization inventory, API mapping, phased rollout | Active |

## Migration status

| Phase | Visualization | SDK entry points | Status |
|-------|---------------|------------------|--------|
| 1 | Protein structure | `Protein.show()`, `PreparedSystem.show()` | **Done** |
| 2 | Protein + binding pockets | `Protein.show(pockets=...)` | Pending |
| 3 | Ligand 3D | `Ligand.show()`, `LigandSet.show()` | Pending |
| 4 | Protein + docked poses | `Protein.show(poses=...)` | Pending |
| 5 | Docking search box | `Docking.show_box()`, `ConstrainedDocking.show_box()` | Pending |
| 6 | MD trajectory | `ABFE.show_trajectory()` | Pending |
| 7 | Remove `deeporigin-molstar` dep | `visualize.py`, static doc embeds | Pending |

## Verification notebooks

Develop in `docs/notebooks/dirty/` (gitignored), then promote to
`docs/notebooks/clean/` via `./scripts/notebooks.sh`. Committed notebooks:

| Phase | Notebook |
|-------|----------|
| 1 | `docs/notebooks/clean/molstar-protein-view.ipynb` |
| 2 | `molstar-pocket-view.ipynb` |
| 3 | `molstar-ligand-view.ipynb` |
| 4 | `molstar-docked-poses.ipynb` |
| 5 | `molstar-docking-box.ipynb` |
| 6 | `molstar-trajectory.ipynb` |
