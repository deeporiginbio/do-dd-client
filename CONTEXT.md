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
Simulation settings for binding and solvation legs: `ABFEParams` (absolute defaults) and `RBFEParams` (relative defaults; 24 windows each, per MDSuite). Shared serialization via `_simulation_blocks`.
_Avoid_: Aliasing `RBFEParams` to `ABFEParams`; duplicating binding/solvation blocks per tool class

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

**Execution billing tag**:
Optional string on ``DeepOriginClient`` (``client.tag`` / ``client.billing_tag``)
applied to every tool execution for billing attribution. Configured once on the
client; not overridable per ``run()`` or ``start()``.
_Avoid_: conflating with entity jsonb ``tags`` or UUI source-filter provenance

**Entity provenance tags**:
Flat ``app`` and ``session`` keys on an entity row's jsonb ``tags`` column.
Stamped automatically on entity/project writes from ``client._app`` and
``client._session`` so UUI source-filter queries match CLI-created rows.
_Avoid_: ``legacy_tags`` (migration artifact for old text columns, not a write target)

**Entity user tags**:
Optional caller-defined keys in the same jsonb ``tags`` object (e.g.
``{"campaign": "foo"}``). Dict only; list shorthand is not supported.
_Avoid_: conflating with execution billing tags or dataset catalog tags

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

**Reference ligand**:
Template ligand whose identity anchors MCS harmonic constraints for test ligands
in `deeporigin.constrained-docking`. CLI kwarg `reference_ligand`; platform
input `reference.ligand`.
_Avoid_: conflating with `reference_pose` (3D coordinates only)

**Reference pose**:
Required 3D coordinates of the reference ligand in the binding site.
CLI kwarg `reference_pose`; platform input `reference.pose`. Must be supplied
explicitly by callers (typically a docked pose SDF).
_Avoid_: letting the server resolve best_pose implicitly; conflating `Ligand.id`
(ligands-table id) with the pose result id sent as `reference.pose.id`

**Pose result ID**:
Platform result-explorer id for a docked pose (`result_type=pose`). Distinct from
ligands-table id. On pose-hydrated `Ligand` objects today, stored as
`properties["id"]` (not `Ligand.id`).
_Avoid_: ligand id; `Ligand.id` when you mean the pose row

**Pose**:
3D conformation backed by an SDF registered in the data platform pose result
table (`results__*`, `result_type=pose`). Has platform pose `id` and parent
`ligand_id`. Sources include docking output and external SDFs (e.g. co-crystal
ligands) registered via **Pose registration**.
_Avoid_: using `Ligand` when you mean a pose result with pose-scoped identity;
conflating with docking-only outputs

**Pose-consuming tool input**:
Downstream tools that need 3D coordinates (SystemPrep ABFE/RBFE, ABFE, RBFE)
accept `Pose` via kwargs `pose`, `pose1`, `pose2` — not `ligand`. Standalone
ligand parameterization (SystemPrep without protein) still uses `ligand: Ligand`.
_Avoid_: `ligand=` when passing a docked pose or registered 3D conformer

**PoseSet**:
Collection of :class:`Pose` objects. Owns pose loading from docking results,
result-explorer queries, and filtering (e.g. best pose per ligand). Replaces
pose-hydrated :class:`LigandSet` usage.
_Avoid_: :class:`LigandSet` for docked poses or pose result rows

**Ligand.get_poses()**:
Query result-explorer for poses whose ``ligand_id`` matches the ligand's
platform id; returns a :class:`PoseSet`. Parent→child discovery path.
_Avoid_: storing pose ids on :class:`Ligand` (e.g. ``properties[\"id\"]``)

**Pose registration**:
Pass-through platform tool that uploads an external SDF and publishes a minimal
pose result so the data platform assigns a pose `id` and stores the row in the
pose table. Used when the user has 3D coordinates outside prior docking.
Output schema is **lighter than docking** (no ``pose_score`` / ``effort`` /
``best_pose``); rows use ``x-result-group: poses`` and ``x-data-type: Pose`` so
they ingest into the same pose result family as docked poses.
Resolves parent ``ligand_id`` by auto-syncing canonical SMILES from the SDF
(``Ligand.sync()`` link-or-create); caller may pass an explicit ``Ligand`` to
override (e.g. a specific ``variant_name_tag``). Optional ``protein_id`` when a
target protein is known (e.g. co-crystal); omit when registering a standalone
3D conformer.
_Avoid_: storing external SDF coordinates only on the ligands table; conflating
with ``Ligand.sync()`` alone (identity only — registration also creates the pose row)

**Poses vs Ligands v1 scope**:
Initial release is CLI + platform-toolbox only. Platform UI / UUI changes
follow in a later release.
_Avoid_: blocking CLI/toolbox work on UUI pose-input UX

**Test ligand**:
Ligand to constrain-dock relative to the reference; CLI `ligand` / `ligands`;
platform input `ligands[]`. Constraints are derived server-side via MCS.
_Avoid_: Reference ligand; ligand (when you mean only the test set)

**Free-dock fallback**:
Per-ligand outcome when MCS cannot match a test ligand to the reference scaffold;
that ligand runs as standard docking with `constrained: false` on outputs.
_Avoid_: unconstrained docking (informal); MCS failure (ambiguous with override
errors on the reference)

**Legacy structure viewer**:
`deeporigin-molstar` Python package plus `balto.biosim.ai/molstar/gallery.js`.
Being replaced by the in-client `deeporigin.viz` HTML builder and hosted
`molstarLib` at `os.dev.deeporigin.io`.
_Avoid_: `biosim_molstar` when referring to the pip package name (`deeporigin-molstar`)

**Docking search box**:
Axis-aligned wireframe of the docking tool's search extents, derived from
pocket center and `box_size_{x,y,z}` (same geometry submitted with docking).
Shown via `Docking.show_box()` / `ConstrainedDocking.show_box()`.
_Avoid_: pocket box; docking pocket (when meaning pocket surfaces); conflating
with `Protein.show(pockets=...)` gaussian surfaces
