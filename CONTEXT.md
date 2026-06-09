# Deep Origin CLI — Drug Discovery

Python SDK for Deep Origin drug-discovery workflows: proteins, ligands, docking,
system preparation, and free-energy calculations.

## Language

**ABFE Workflow**:
Platform tool `deeporigin.abfe` that runs ordered `steps` of `system-prep` and/or `abfe`.
_Avoid_: `abfe-end-to-end`, `abfe-e2e-workflow`, `mode` discriminator (legacy v3)

**Combined workflow**:
A single `ABFE(protein, ligand)` execution with `steps=["system-prep", "abfe"]`.
_Avoid_: "end-to-end workflow" when referring only to the platform tool key

**FEP parameters**:
Shared simulation settings (`ABFEParams`) for binding and solvation legs, used by both ABFE and RBFE.
_Avoid_: Duplicating binding/solvation blocks per tool class

**Prepared system**:
Simulation-ready binding and solvation XML files (and metadata) produced by system prep.
_Avoid_: "system" alone when meaning the prepared molecular system artifact

**Workflow step**:
A named stage in a combined workflow execution (`system-prep`, `abfe`, `rbfe`, `konnektor`).
_Avoid_: `mode` for v5 workflow tools
