# DDOS-6930: Audit BiosimDock pocket geometry for rotation support

**Ticket:** Audit whether the Deep Origin docking stack supports rotated (non-axis-aligned)
docking boxes, and where protein rotation plus inverse pose transforms would plug in.

**Primary sources:**

- `/Users/srinivas/code/toolbox/tools/docking` — tool schema and Argo workflow
- `/Users/srinivas/code/toolbox/tools/docking-constrained` — constrained-docking schema
- `/Users/srinivas/code/toolbox/images/docking` — served and bulk execution (Julia + Python)
- `/Users/srinivas/code/BiosimDock.jl` — pocket/box handling, coordinate frames
- `/Users/srinivas/code/PocketFinder.jl` — `PocketData` rotation machinery
- `/Users/srinivas/code/do-dd-client/src/drug_discovery/docking_common.py` — SDK box geometry

---

## Executive summary

**Today the platform docking box is always an axis-aligned bounding box (AABB) expressed as
`center` plus `box_size_x/y/z` in the original protein Cartesian frame.** Neither the tool
JSON schemas nor the SDK expose box orientation (rotation matrix, Euler angles, or corner
vertices). BiosimDock's search space, scoring grids, and translation sampling all assume
axis-aligned boxes centered on `pocket_data.center`.

BiosimDock **does** contain a coordinate-frame subsystem (`PocketData.rotation_matrix`,
`transform_protein!`, `to_initial_space!` / `from_initial_space!`) originally built for
PocketFinder PCA alignment (`fit_box`). On the **platform path**, that rotation path is
**inactive**: the workflow constructs `PocketData(center)` with no point cloud, sets
`fit_box => true`, and `assign_box!` skips rotation when `pocket_data.points === nothing`.

**Rotated-box docking is achievable in principle** by rotating the protein (and any
reference pose / harmonic constraint coordinates) into a working frame where the desired
oblique pocket becomes an AABB, running standard docking, then applying the inverse
rotation to output poses. **No workflow step performs this today.** The natural insertion
points are the toolbox docking image (`load_docking_conf` / `server.jl` pre-driver, and
pose export post-dock) plus SDK helpers in `docking_common.py` for visualization alignment.
Constrained docking inherits the same AABB-only pocket contract and would require the same
rotation of reference-pose-derived constraint coordinates.

---

## 1. Is the docking box always axis-aligned in the protein frame today?

**Yes.** At every layer:

### Tool contract (platform API)

Both `deeporigin.docking` and `deeporigin.constrained-docking` define pocket geometry as
a 3-vector center and three scalar half-extents — no orientation fields.

```98:119:toolbox/tools/docking/workflow/tool-definition.json
                    "center": {
                        "description": "XYZ coordinates of the pocket center in angstroms",
                        ...
                    },
                "required": [
                    "center",
                    "box_size_x",
                    "box_size_y",
                    "box_size_z"
                ],
```

The Argo workflow forwards this pocket object unchanged into each chunk's
`input_params.json` (`workflow.yaml` lines 104–116). Validation in
`validate_pocket_geometry.jl` checks center and per-axis box sizes only.

### SDK (do-dd-client)

`resolve_docking_box_geometry` and `build_pocket_tool_params` emit the same AABB shape:

```23:41:do-dd-client/src/drug_discovery/docking_common.py
def resolve_docking_box_geometry(pocket: Pocket) -> tuple[list[float], list[float]]:
    ...
    pocket_center = pocket.get_center().tolist()
    box_size = [float(box_size_x), float(box_size_y), float(box_size_z)]
    return pocket_center, box_size
```

The `Pocket` dataclass stores `center` and `box_size_x/y/z` only — no rotation metadata
(`structures/pocket.py`).

### Toolbox execution (bulk + served)

Bulk docking builds `PocketData` from center + box size and passes `fit_box => true`:

```116:138:toolbox/images/docking/scripts/run.jl
    function load_docking_conf(protein_file_path; pocket_content=nothing, pocket_center=nothing, box_size=nothing)
        ...
            pocket_data = PocketData(Float32.(pocket_center))
            if !isnothing(box_size)
                pocket_data.box_size .= box_size
            end
            driver = Docking4DDriver(protein_file_path;
                options=Dict(
                    "pocket_data" => pocket_data,
                    "fit_box" => true
                )
            )
```

Served `POST /dock` follows the same pattern (`server/server.jl` ~932–955).

### BiosimDock internals

**Translation sampling** places ligands uniformly inside an axis-aligned box:

```118:133:BiosimDock.jl/src/Transformations/structures.jl
function randomize(::Type{Transformation{NTorsions, T}}; 
                   center=nothing, box_size=nothing, ...)
    ...
    if !isnothing(center) && !isnothing(box_size)
        box_origin = center - box_size / 2
        tf.translation = rand(STranslation{T}) .* box_size .+ box_origin
```

**Scoring grids** are axis-aligned parallelepipeds aligned to X/Y/Z:

```31:38:BiosimDock.jl/src/Grids/Grids.jl
        x_range = Pair(center[1] - half_grid_size[1], center[1] + half_grid_size[1])
        y_range = Pair(center[2] - half_grid_size[2], center[2] + half_grid_size[2])
        z_range = Pair(center[3] - half_grid_size[3], center[3] + half_grid_size[3])
```

**`fit_box` rotation is a special case, not used on platform:** `assign_box!` only rotates
when `fit_box === true` **and** `pocket_data.points !== nothing` (PocketFinder point
cloud). Center-only pockets skip rotation:

```55:59:BiosimDock.jl/src/Structure/protein.jl
    if get(options, "fit_box", false) && !isnothing(pocket_data.points)
        if !pocket_data.rotation_applied
            set_rotation_params!(pocket_data)
            transform_protein!(protein)
```

Platform inputs never supply pocket points, so `set_rotation_params!` leaves the identity
matrix (`PocketFinder.jl` lines 308–311).

**Net:** the box is always AABB-aligned to the **input protein's Cartesian axes**. On the
current platform path the protein is **not** re-oriented before docking.

---

## 2. Can rotated-box docking be achieved by rotating protein coords (fixed AABB at pocket center/size)?

**Yes, in principle — and BiosimDock already has the coordinate-frame hooks for it — but
the platform workflow does not implement it.**

### Existing BiosimDock / PocketFinder machinery

`PocketData` carries rotation state:

```53:63:PocketFinder.jl/src/PocketFinder.jl
mutable struct PocketData
    center::Vector{Float_t}
    box_size::Vector{Float_t}
    rotation_matrix::Matrix{Float_t}
    inv_rotation_matrix::Matrix{Float_t}
    post_translation::Vector{Float_t}
    inv_post_translation::Vector{Float_t}
    rotation_applied::Bool
```

Core transforms (`BiosimDock.jl/src/Structure/protein.jl`):

- `transform_protein!` — rotate protein coordinates into the working frame
- `from_initial_space!` / `to_initial_space!` — map coordinates between initial (PDB) and
  working frames via `apply_rotation!(coords, pd; inverse=...)`

When `fit_box` runs with pocket points, PocketFinder PCA sets `rotation_matrix` so the
pocket's principal axes align with Cartesian X/Y/Z, then `transform_protein!` rotates the
receptor. After that, the same `center` + `box_size` describe an AABB in the working frame
that tightly bounds the (formerly oblique) pocket.

### Arbitrary user-specified rotation (not implemented)

To dock into an oblique box defined in the original protein frame:

1. **Pre-dock:** Choose rotation `R` that maps the desired box axes to Cartesian axes.
   Set `pocket_data.rotation_matrix = R`, `inv_rotation_matrix = R'`, compute
   `post_translation` / `inv_post_translation` (see `set_rotation_params!` pattern in
   `PocketFinder.jl`), call `transform_protein!`.
2. **Dock:** Run standard BiosimDock with unchanged `center` + `box_size` (now an AABB in
   the working frame).
3. **Post-dock:** Apply `to_initial_space!(pose_coords, pocket_data)` so poses align with
   the **original** protein frame stored on the platform.

### Important output-frame detail

Final pose SDF coordinates are written from `solution_to_coords` **without**
`initial_space=true`:

```179:188:BiosimDock.jl/src/Systems/system.jl
            for (tf, ligand_coords) in zip(out_container.transformation_list, out_container.coordinates_list)
                ...
                for k in keys(ligand_coords_lists_by_original_data_type)
                    push!(ligand_coords_lists_by_original_data_type[k], solution_to_coords(tf, sys; original_data_type))
```

Progress/debug SDF blocks use `initial_space=true` (`solution.jl` line 173), but shipped
poses stay in the **working** (possibly rotated) frame. If protein rotation were enabled,
**inverse pose transform must be added at export** unless the stored protein file is also
rotated.

### SDK visualization

`show_box()` and `molstar_html.render_docking_box_html` draw an AABB from center ±
half-size in the **unrotated** protein PDB (`molstar_html.py` `_validate_docking_box_geometry`).
Any rotation workflow must keep visualization geometry consistent with pose coordinates.

---

## 3. Where in the toolbox workflow would protein rotation + inverse pose transform happen?

### Current pipeline (no rotation)

```
SDK (docking_common.py)
  → executions.create { pocket: {center, box_size_*}, protein.file_path }
  → Argo workflow.yaml (pass-through)
  → dock_platform_prepare.py / download_files.py (resolve IDs, download protein)
  → run.jl or server.jl
       PocketData(center) + box_size, fit_box=true (no-op)
       Docking4DDriver → dock_smiles / dock
  → SDF upload (poses in working frame == original frame today)
  → SDK load_docking_poses_from_execution
```

### Recommended seams

| Phase | Location | Action |
|-------|----------|--------|
| **Schema / SDK input** | `tools/docking/workflow/tool-definition.json`, `docking_common.py` | Add optional box orientation (e.g. 3×3 rotation matrix or quaternion + validation). SDK resolves and forwards. |
| **Pre-dock (protein)** | `toolbox/images/docking/scripts/run.jl` → `load_docking_conf`; `server/server.jl` ~950; constrained `run_constrained.jl` → `load_constrained_docking_conf` | After protein PDB/PDBQT is local, before `Docking4DDriver`: populate `PocketData` rotation fields, call `transform_protein!`, optionally write rotated receptor to temp file for grid build. |
| **Pre-dock (constraints)** | `server/mcs_constraints.py` → `compute_constraints` | Rotate reference-pose constraint `coordinates` with the same `R` used for the protein (today constraints are absolute coords from reference SDF — lines 241–257). |
| **Post-dock (poses)** | `run.jl` `run_docking` / `server.jl` pose split loop; `shared/sdf_pose_metadata.jl` | After `dock_smiles`, before writing/uploading SDF: call `to_initial_space!` on pose coordinates (or equivalent matrix multiply) so platform poses match the stored protein frame. |
| **Visualization (SDK)** | `docking.py` / `constrained_docking.py` `show_box()`; `molstar_html.py` | Either pass rotated box corners to Mol*, or rotate box metadata client-side to match pose frame. |

The Argo `workflow.yaml` itself needs no change for rotation — it only batches ligands.
All geometry work belongs in the **docking container** (`images/docking`).

---

## 4. Same assumptions for constrained docking?

**Yes.** Constrained docking uses the identical AABB pocket contract and the same
center-only `PocketData` construction path.

### Pocket schema

`tools/docking-constrained/workflow/tool-definition.json` pocket properties mirror standard
docking: `center`, `box_size_x/y/z`, optional `id` — no orientation.

### SDK

`ConstrainedDocking._build_tool_inputs` calls the same `resolve_docking_box_geometry` and
`build_pocket_tool_params` as `Docking` (`constrained_docking.py` lines 541–543).

### Execution

`run_constrained.jl` → `load_constrained_docking_conf` builds `PocketData(center)` +
`fit_box => true` (lines 157–175). Free-docking fallback path (`_build_free_docking_driver`,
lines 137–147) is identical.

### Constraints add a second coordinate dependency

Harmonic constraints are derived server-side from the reference pose in **absolute**
coordinates:

```241:257:toolbox/images/docking/server/mcs_constraints.py
    ref_positions = [list(ref_conf.GetAtomPosition(idx)) for idx in mcs_match_ref]
    ...
            constraints = [
                {
                    "index": atom_idx + 1,
                    "coordinates": ref_positions[j],
                    "energy": energy,
                }
```

If the protein is rotated pre-dock, **constraint anchor coordinates must receive the same
forward rotation** as the receptor. Output poses need the same inverse transform as
standard docking. The constrained self-test fixture hard-codes absolute constraint coords
in the original frame (`dock_platform_prepare.py` `CONSTRAINED_SELF_TEST_CONSTRAINTS`).

---

## Summary table

| Question | Answer |
|----------|--------|
| Box always AABB in protein frame? | **Yes** — API, SDK, grids, and search all axis-aligned; platform never rotates protein |
| Rotated box via protein rotation? | **Feasible** using existing `PocketData` rotation + `transform_protein!` / `to_initial_space!`; **not wired** in platform |
| Workflow insertion points | Pre-dock: `run.jl`/`server.jl` driver setup; constraints: `mcs_constraints.py`; post-dock: SDF export in `run.jl`/`server.jl`; SDK: `docking_common.py` |
| Constrained docking | **Same AABB-only assumption**; reference-pose constraints must rotate with protein |

---

## Open design questions (out of scope for this audit)

1. **Store rotated or original protein?** Platform stores the user's PDB. Poses must land in
   the same frame as that file unless a rotated copy is persisted.
2. **Pocket-finder pockets:** PocketFinder can compute PCA rotation when point clouds exist.
   Should platform pockets expose orientation from PocketFinder props, or only support
   user-specified rotation?
3. **Schema shape:** Rotation matrix vs. quaternion vs. three Euler angles vs. two corner
   points + center — affects UI (PUI molstar docking box controls) and SDK validation.
4. **Backward compatibility:** Omitting orientation must continue to mean identity rotation
   (current behavior).
