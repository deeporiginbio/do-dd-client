# Deep Origin CLI — Drug Discovery

Python SDK for Deep Origin drug-discovery workflows: proteins, ligands, docking,
system preparation, and free-energy calculations.

## Language

**Molprops**:
Combined platform tool ``deeporigin.mol-props-combined`` for physicochemical
properties (logP, logD, logS, PAINS). As of tool 0.9.3+, toxicity and metabolism
endpoints (hERG, CYP, AMES) moved to ``deeporigin.admet-properties``. The CLI class
``Molprops`` mutates dedicated :class:`~deeporigin.drug_discovery.structures.ligand.Ligand`
attributes in place.
_Avoid_: conflating with ``Admet``; calling it "ADMET" when you mean the
admet-properties tool

**Admet endpoint**:
A selectable admet-now task folder name (e.g. ``AMES_classification``) listed on
the ``deeporigin.admet-properties`` tool definition. The catalog is owned by the
definition, not by the CLI.
_Avoid_: JSON Schema ``inputs.properties``; molprops keys (``herg``); a fixed count
of endpoints baked into the client

**Admet**:
admet-now served platform tool ``deeporigin.admet-properties``. A new Admet
execution's ``properties`` is the endpoint list from the current tool definition
(the caller may trim it before the run). A past execution restores ``properties``
from recorded inputs. The CLI class ``Admet`` returns a
:class:`pandas.DataFrame`; it does not mutate ligands.
_Avoid_: constructor ``properties=``; ``ADMET_PROPERTY_NAMES`` /
``ADMET_PROPERTY_KEYS``; ``properties is None`` meaning “all” on a
new run; calling definition-fill “hydration” (that word is ``from_dto`` /
structure files); conflating with ``Molprops`` (``herg`` vs
``hERG_classification``); conflating with ``Metabolism`` (site of metabolism)

**Metabolism**:
Dual-mode platform tool ``deeporigin.metabolism`` and CLI class ``Metabolism``.
Constructor ``ligands=`` accepts a ``Ligand``, a list of ligands, or a
``LigandSet``. A blocking ``run()`` (fewer than the Metabolism workflow ligand
threshold) scores Caller SMILES and returns a :class:`pandas.DataFrame` of
Metabolism site rows for every enzyme the tool scored. Larger batches use
``start()`` then ``wait()`` / ``watch()``, then ``get_results()``.
``get_molecules()`` returns molecule-level ``confidence_tier`` rows for **this
execution**. Class-level ``fetch_results`` / ``fetch_molecules`` load indexed
rows for a ligand set from the data platform (any past jobs) by ``ligand_id``.
Before ``run`` / ``start``, if every ligand has a platform id and every id
already has a Metabolism molecule, the client refuses (no execution); if the
job still proceeds and any id is already indexed, it warns. No force/recompute.
Ligands are not mutated. Payload sends ``id`` only when ``Ligand.id`` is
already set. There is no client-side ligand cap and no quote path.
_Avoid_: ``Admet`` CYP substrate/inhibitor endpoints; the April 24-enzyme PRD
panel; ``self_test``; ``METABOLISM_ENZYMES``; ``job.enzymes``; constructor
``enzymes=`` or ``properties=``; sending a synthetic ``id`` (Admet's
``str(idx)`` fallback); ``run(quote=True)``; ``METABOLISM_LIGAND_CAP``;
using instance ``get_*`` for cross-execution ligand-set reads; soft-fetching
inside ``run()``

**Metabolism fetch**:
Class-level ``Metabolism.fetch_results`` / ``fetch_molecules``: read indexed
Metabolism site / molecule rows for the given ligands from the data platform
by platform ``ligand_id``, unbound to any execution. May return partial or
empty tables when some ligands lack an id or have no indexed rows.
_Avoid_: instance ``get_results`` / ``get_molecules`` (one execution);
``force`` / recompute; treating fetch as creating a job

**Metabolism already-scored preflight**:
Client check before ``run`` / ``start``: refuse when every ligand has a
platform id and every id already has an indexed Metabolism molecule; otherwise
create a real execution. When proceeding, warn if any ligand id is already
indexed. Presence matches the platform MetabolismMolecule skip filter; not a
recompute API.
_Avoid_: client-only ``force=True``; merging indexed rows into instance
``get_*``; refusing when any ligand lacks an id

**Metabolism enzyme**:
The ``enzyme`` column on a Metabolism site row. The tool scores every
cytochrome P450 isoform it supports; the client does not select, list, or
filter isoforms. Names come from the tool output, not a client constant.
_Avoid_: ``METABOLISM_ENZYMES``; ``job.enzymes``; constructor ``enzymes=``;
trimming site rows in the client; ``properties``; Admet CYP endpoints;
fetching an enzyme enum from ``tools.get``

**Metabolism workflow ligand threshold**:
Client and platform routing boundary of 30 ligands. ``Metabolism.run()``
raises when ``len(ligands) >= 30``; callers use ``start()`` then ``wait()`` /
``watch()``. Platform preflight routes the same threshold to workflow vs
direct. Constant: ``METABOLISM_WORKFLOW_LIGAND_THRESHOLD``.
_Avoid_: a client hard cap; ADMET workflow ligand threshold (different tool)

**Metabolism site**:
One ``sites[]`` row: optional ``ligand_id``, Caller SMILES, ``atom_index``,
``enzyme``, and site ``confidence``. Grain of ``run()`` / ``get_results()``.
_Avoid_: ``confidence_tier``; metabolite structure; nested per-ligand site arrays

**Metabolism molecule**:
One ``molecules[]`` row: optional ``ligand_id``, Caller SMILES, and
``confidence_tier``. Grain of ``get_molecules()``. One row per scored SMILES.
_Avoid_: copying ``confidence_tier`` onto a Metabolism site; a row for a skipped
invalid ligand

**Caller SMILES**:
The ligand structure string that Metabolism scored. ``atom_index`` is only
valid on this string. Sent as-is (not canonicalized).
_Avoid_: rewriting to canonical SMILES; treating it as a predicted metabolite

**confidence_tier**:
Molecule-level reliability of a Metabolism score: ``high``, ``medium``, or
``low``. Not site ``confidence``.
_Avoid_: max or mean of site confidences; per-enzyme tier

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

**Protein Prep**:
Platform tool `deeporigin.protein-prep` that inventories a caller-supplied
protein, records editable keep/review/skip Decisions, then applies resolved
keep/skip Decisions and protonation. CLI class `ProteinPrep` is one preparation
session: `.recommend()` updates its Selection without binding its execution id
and returns the Recommendation view; `.run()` or `.start()` submits durable
preparation and permanently binds the object. `protein` is constructor-only.
Loop modelling runs unless the caller sets loops-off prepare.
_Avoid_: SystemPrep / FEP assembly; quoting this tool (billing is skipped);
public `action`; a separate recommend object; silently converting `review` to
`skip`; v1 keep/remove lists (`keep_chain_ids`, …); treating loops-off as
skipping Protein Prep; `watch()` on a `.run()` / sync execution; `inputs.sync`
on protein-prep (not in the tool schema); treating `.recommendation` as a raw
dict or a pandas DataFrame type

**Protein Prep Selection**:
Digest-bound component Decision map produced by `ProteinPrep.recommend()` or
provided by the caller. Editable SDK state may contain `keep`, `review`, or
`skip`; durable preparation requires every `review` to be resolved. `keep()` and
`skip()` set Decisions for listed component ids, or for every Component matching
keyword filters (`kind`, `subtype`, `decision`). Filters are equivalent to
passing the matching ids. Positional ids and keyword filters are mutually
exclusive. Both methods return the `ProteinPrep`.
_Avoid_: silently resolving `review`; treating a Selection as analyzer evidence
(that is the Component recommendation); treating matcher kwargs as a different
operation from listing ids; mixing ids with matcher kwargs; `pp.recommend().keep()`
(recommend returns the Recommendation view, not the `ProteinPrep`)

**Component** (Protein Prep):
One inventoried chain, ligand, cofactor, or water from recommend. Identity is
the component `id` (for example `chain:A`, `water:A:HOH:310:`).
_Avoid_: residue when you mean a Component; treating `label` as the id

**Component recommendation**:
The analyzer's frozen keep, review, or skip tag on a Component. It does not
change when the caller edits Decisions.
_Avoid_: Decision; the analyzer payload as a whole

**Decision**:
The caller's current keep, review, or skip value for a Component in the
Selection. Edited by `keep()` / `skip()`. Preparation requires every Decision
to be keep or skip.
_Avoid_: `recommendation` when you mean the live Selection value; Component
recommendation

**Recommendation view**:
Callable notebook table of Components on `ProteinPrep.recommendation` after
recommend (also returned by `.recommend()`). Columns include frozen Component
recommendation and live Decision. Calling it AND-filters (`kind`, `subtype`,
`recommendation`, `decision`) and returns a DataFrame. Unset is `None`. `.raw`
is the analyzer payload. Not mapping-like (`["components"]` is gone).
_Avoid_: returning a DataFrame from the property itself; dict access on the view;
`keep` / `skip` on the view (`pp.recommend().keep()` is not supported)

**Loops-off prepare**:
Protein Prep `action=prepare` with `model_missing_loops=false`: apply the
frozen Selection (keep/skip chains, waters, ligands, cofactors), skip loop
modelling, still protonate. Quoted `method: direct`; `pdb_id` optional.
CLI `.run()` blocks and returns the prepared Protein; `.start()` is also valid.
_Avoid_: skipping Protein Prep; skipping protonation; treating loops-off as
requiring synchronous SDK use

**Prepared protein (CLI)**:
In-memory :class:`~deeporigin.drug_discovery.structures.protein.Protein` returned
by `ProteinPrep.get_results()`, whose structure is the cleaned PDB. Not a
proteins-table row until the caller `sync()` or `update()`.
_Avoid_: public `PreparedProtein` type; PreparedSystem

**Prepared Protein stamp**:
File-borne token that marks a structure as already prepared so downstream tools
skip AUTO protein cleanup. PDB: `REMARK  99 DO_PREPARED`. mmCIF:
`_deeporigin.prepared     DO_PREPARED`. Written by Protein Prep or
`Protein.mark_as_prepared()`; never a public `PreparedProtein` type.
_Avoid_: treating accidental PDB REMARK text inside CIF as prepared; converting
CIF to PDB just to stamp

**Protein**:
A macromolecular target structure. Once synced, a platform proteins-table row.
_Avoid_: PreparedSystem; Prepared protein (CLI) when you mean a catalog protein

**Pocket**:
A binding cavity on a Protein. PocketFinder results are catalog rows of result
type `pocket`. Other constructors can produce a Pocket with no parent (local PDB,
ligand-derived, docking box).
_Avoid_: Docking search box; pocket box when meaning the cavity surface

**Parent protein**:
The Protein a Pocket was found in. Durable identity is `protein_id`. The
in-process parent is `Pocket.protein` when attached. A Pocket can be shown in
the Structure viewer when the parent is resolvable (attached Protein or
`protein_id`). Other constructors may leave both unset.
_Avoid_: `pdb_id` (RCSB code); Docking's protein input when you mean the Pocket's parent

**PocketFinder**:
Platform tool `deeporigin.pocket-finder` and CLI execution that detects pockets
on a Protein and returns them as Pocket objects.
_Avoid_: `PocketFinder.show()` as Structure viewer (that method is the execution card)

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
Test ligands may be SMILES-only (no structure file); the server embeds an
ephemeral 3D structure for MCS. Reference ligand and reference pose still
require 3D structure files on the platform.
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
Wireframe of the docking tool's search extents, derived from pocket center and
box sizes (same geometry submitted with docking). When pocket-finder emitted a
nested `box`, default sizes and orientation come from **Inferred box orientation**
; otherwise from parent lab-frame `box_size_{x,y,z}` (axis-aligned). **Session
rotation** overrides inferred orientation in the notebook and on subsequent
`run()` / `start()` when set. Shown via `Docking.show_box()` /
`ConstrainedDocking.show_box()`.
_Avoid_: pocket box; docking pocket (when meaning pocket surfaces); conflating
with `Protein.show(pockets=...)` gaussian surfaces; treating the box as
always axis-aligned on new pocket-finder runs

**Inferred box orientation**:
PCA-aligned docking box rotation and OBB sizes from pocket-finder's nested
`box` on a `Pocket` (`Pocket.box`). Distinct from **Session rotation**
(ephemeral, gesture-committed on `Docking`). Session rotation overrides inferred
when set. Legacy indexed pockets without `box` have no inferred orientation.
_Avoid_: parent lab-frame `box_size_*` alone when passing orientation to docking;
session rotation (when you mean pocket-finder output)

**Session rotation**:
Ephemeral Euler angles `[rx, ry, rz]` on a `Docking` or `ConstrainedDocking`
instance, written by interactive `show_box` on molstar gesture-end. Not stored
on `Pocket`. Overrides **Inferred box orientation** when set. Free docking
`run()` / `start()` forward it; ConstrainedDocking ignores it in v1. `None`
when unset or identity.
_Avoid_: Apply; pocket rotation; inferred box orientation; treating printed cell
output as live

**Box commit**:
Kernel write of docking search-box geometry from a molstar gesture-end. Commits
updated `center` and `box_size` onto `Pocket`, plus `rotationDeg` as session
rotation on the `Docking` instance. Appearance-only molstar edits (color,
visibility) are not box commits.
_Avoid_: Apply to notebook; treating resize/recenter as visualization-only edits
