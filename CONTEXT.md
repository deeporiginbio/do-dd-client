# Deep Origin CLI — Drug Discovery

Python SDK for Deep Origin drug-discovery workflows: proteins, ligands, docking,
system preparation, and free-energy calculations.

## Language

**ABFE Workflow**:
Platform tool `deeporigin.abfe-end-to-end` that runs ordered `steps` of
`system-prep` and/or `abfe`. The CLI uses the same public key as platform-ui and
platform infra; v5 workflow versions (e.g. `1.0.x`) replace the legacy v3 job
implementation under that key.
_Avoid_: `deeporigin.abfe-e2e-workflow`, `mode` discriminator (superseded legacy)

**Combined workflow**:
A single `ABFE(protein, ligand)` execution with `steps=["system-prep", "abfe"]`.
_Avoid_: conflating the workflow *steps* with the platform tool key

**FEP parameters**:
Shared simulation settings (`ABFEParams`) for binding and solvation legs, used by both ABFE and RBFE.
_Avoid_: Duplicating binding/solvation blocks per tool class

**Prepared system**:
Simulation-ready binding and solvation XML files (and metadata) produced by system prep.
_Avoid_: "system" alone when meaning the prepared molecular system artifact

**Workflow step**:
A named stage in a combined workflow execution (`system-prep`, `abfe`, `rbfe`, `konnektor`).
_Avoid_: `mode` for v5 workflow tools

**KonnektorResult**:
CLI return type from `Konnektor.run()` — resolved ligand pairs, connectivity flag, and inline viz HTML.
_Avoid_: conflating with platform ingest entity `LigandNetwork` or legacy `LigandSet.network` dict

**Tool version pin**:
Version specifier passed to `executions.create`, `Tools.get`, or `Tools.exists`. The
platform resolves pins at request time: exact semver (`"3.2.3"`), major-only
(`"1"` → latest `1.x.x`), or `"latest"` (highest enabled version). Stored in
`TOOL_KEYS_AND_VERSIONS`.
_Avoid_: treating pins as exact semver strings when comparing against `tools.list()` rows

**Patent workflow**:
Platform tool `deeporigin.draco` that extracts chemical structures from a PDF.
CLI class `Patent`. Billing item `DO_PATENT` (per page).
_Avoid_: `Draco` as the public API name; `DoPatentMolecule` as a CLI type
