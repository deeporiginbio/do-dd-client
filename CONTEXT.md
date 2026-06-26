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

**Entity update**:
PATCH an existing ligand or protein record by ID; the platform creates a new immutable version row (stable ID, bumped `version`).
_Avoid_: calling it "edit in place" or conflating with `sync()`

**Entity sync**:
Link-or-create by identity (canonical SMILES for ligands, file path for proteins). Does not modify an existing record's `mol_file` or `file_path`.
_Avoid_: using `sync()` when the intent is to change structure files on a known platform ID — use `update()` instead

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

**Result type**:
Platform catalog base entity from a tool output schema's `x-data-type` (e.g.
`pose`, `pocket`, `preparedsystem`, `abferesult`). Used as a result-explorer
filter directive to narrow which `results__*` tables are searched. Result rows
may echo a top-level `result_type` field in API responses, but that is separate
from the filter directive and not a generic stored entity column like `protein_id`.
_Avoid_: `Binding` for docking poses (use `pose`); conflating with `tool_key`

**Structure viewer**:
Jupyter 3D Mol* embed for macromolecules, ligands, docked poses, pockets, and
trajectories. Rendered via `render_html()` in a notebook cell.
_Avoid_: conflating with RDKit 2D structure images (`render_smiles_in_dataframe`)

**Legacy structure viewer**:
`deeporigin-molstar` Python package plus `balto.biosim.ai/molstar/gallery.js`.
Being replaced by the in-client `deeporigin.viz` HTML builder and hosted
`molstarLib` at `os.dev.deeporigin.io`.
_Avoid_: `biosim_molstar` when referring to the pip package name (`deeporigin-molstar`)
