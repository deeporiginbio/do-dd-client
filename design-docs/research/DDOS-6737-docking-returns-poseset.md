# DDOS-6737: CLI Docking returns PoseSet (breaking) — implementation plan

**Status:** research / plan  
**Ticket:** [DDOS-6737](https://deeporigin.atlassian.net/browse/DDOS-6737)  
**Spec:** [Poses vs Ligands](https://deeporigin.atlassian.net/wiki/spaces/PLEN/pages/1045528584/Poses+vs+Ligands) (D5, D7)  
**Depends on:** DDOS-6736 (`Pose` / `PoseSet` — merged as PR #594)  
**Related:** DDOS-6738 (FEP pose kwargs)

---

## Verdict

Phase 2 already loads docking results as `PoseSet` internally
(`load_poses_from_result_explorer` → `PoseSet.from_json`), then **converts back**
to `LigandSet` via `to_ligand_set()` for the public docking API. DDOS-6737 is
mostly: stop converting, flip public return types, give `PoseSet` the LigandSet
ergonomics notebooks need (`download`, `to_dataframe`, `filter_top_poses`), and
delete pose-hydration helpers from `LigandSet`.

**Complexity: M** (core wiring is small; call-site + PoseSet parity + docs/notebooks
push it above S; not L unless `Protein.show` / viz migration balloons).

**WIP:** no `6737` branch or PR. Only `remotes/origin/feat/DDOS-6736-pose-poseset`
(Phase 2).

---

## 1. Current docking hydration (as of main)

### Public APIs (still `LigandSet`)

| Method | File | Returns today |
| --- | --- | --- |
| `Docking.get_results(dto=None, *, all_poses=False)` | `src/drug_discovery/docking.py` | `LigandSet` |
| `Docking.get_poses(*, all_poses=False)` | same | `LigandSet` (calls `get_results` + `download`) |
| `Docking.run(...)` | same | `LigandSet \| None` via `get_results(..., all_poses=True)` |
| `ConstrainedDocking.get_results` / `get_poses` / `run` | `src/drug_discovery/constrained_docking.py` | same pattern |
| `ConstrainedDocking.get_reference_pose` | same | `Ligand` (not yet `Pose`) |

### Shared loader chain

```
Docking.get_results / ConstrainedDocking.get_results
  → load_docking_poses_from_execution()          # docking_common.py → LigandSet
      → load_scored_poses_from_result_explorer() # PoseSet → to_ligand_set()
          → load_poses_from_result_explorer()    # already returns PoseSet
      OR fallback jobOutputs.poses
          → LigandSet.from_json(rows)            # pose-shaped rows → Ligand
```

Key files:

- `src/drug_discovery/docking.py` — `get_results` / `get_poses` / `run`
- `src/drug_discovery/constrained_docking.py` — same + `get_reference_pose`
- `src/drug_discovery/docking_common.py` — loaders, `normalize_pose_ligands`,
  `ligand_payloads_for_viewer`, `show_docking_box_in_notebook`
- `src/drug_discovery/structures/ligand.py` — `LigandSet.from_json` /
  `from_result` / pose path helpers / `filter_top_poses` / bulk `download`
- `src/drug_discovery/structures/pose.py` — `Pose`, `PoseSet` (Phase 2)

`get_poses()` today: metadata hydrate → `LigandSet.download(lazy=True)` for SDFs.
`get_results()`: metadata only (no SDF download). Docstrings still point at
`LigandSet.from_result`; implementation uses
`load_docking_poses_from_execution`.

---

## 2. PoseSet APIs docking should use (already present)

From `structures/pose.py` + `docking_common.py`:

| API | Status |
| --- | --- |
| `PoseSet.from_result(execution_id=..., best_pose=..., scored_only=...)` | Ready — wraps `load_poses_from_result_explorer` |
| `PoseSet.from_json(rows)` | Ready |
| `PoseSet.to_ligand_set()` | Legacy bridge (keep during migration / for viz) |
| `Pose.to_ligand()` | Legacy bridge |
| `Pose.download` (via `Entity`) | Single-pose only |
| `Ligand.get_poses()` → `PoseSet` | Ready (parent→child) |

**Missing on `PoseSet` (blockers for a clean break):**

- Bulk `download(...)` (notebooks: `poses.download()`)
- `to_dataframe()` / `show_df()` (docs/notebooks)
- `to_sdf()` / optional `show()` (export + viz)
- `filter_top_poses(...)` (FEP how-to + LigandSet today)
- Path helpers currently on `LigandSet` (D7)

Suggested shape after 6737:

```python
# metadata (best pose per ligand by default)
poses = docking.get_results()          # → PoseSet
df = poses.to_dataframe()

# with SDF download
poses = docking.get_poses()            # → PoseSet (downloaded)
# or
poses = docking.get_results(); poses.download()
```

---

## 3. Call sites / tests / docs / notebooks

### Tests (must change)

- `tests/test_docking.py` — `isinstance(..., LigandSet)` on `run` / `get_results` /
  `get_poses`
- `tests/test_constrained_docking.py` — same; `LigandSet.from_result`;
  `load_docking_poses_from_execution`
- `tests/test_pose.py` — `test_load_scored_poses_still_returns_ligand_set`
  (Phase 2 legacy guarantee — flip or delete)

### Docs

- `docs/dd/tools/docking.md`
- `docs/dd/tutorial/docking.md`, `docking-legacy.md`
- `docs/dd/ref/pose.md` (still says docking returns LigandSet)
- `docs/dd/ref/docking.md`, `constrained_docking.md` (generated + prose)
- `docs/dd/how-to/use-docking-outputs-for-fep.md` (`filter_top_poses`, assign to
  `sim.ligands`)
- `docs/dd/how-to/ligands.md` (pose download notes if any)
- `docs/dev/mock-server.md` (`LigandSet.from_result` examples)
- `src/drug_discovery/class-design.md` (says Docking → LigandSet)

### Notebooks (`docs/notebooks/clean/` → edit via dirty + `scripts/notebooks.sh`)

- `docking-single-ligand.ipynb` — `to_dataframe` / `download`
- `docking-many-ligands.ipynb` — `get_results` / `get_poses`
- `constrained-docking.ipynb` — `get_results` / `download` / `to_dataframe`
- `interactive-docking-box.ipynb` — `poses.download()`
- `poses-vs-ligands-phase2.ipynb` — explicitly documents LigandSet until 6737;
  promote or add phase-3 notebook

### Viz / secondary APIs (accept PoseSet or keep bridge)

- `Docking.show_box(poses=...)` / `ConstrainedDocking.show_box`
- `docking_common.normalize_pose_ligands` / `ligand_payloads_for_viewer`
- `Protein.show(..., poses=...)` — typed as `LigandSet | list[Ligand]` today

Practical approach: accept `Pose | PoseSet` and convert via `to_ligand()` /
`to_ligand_set()` for molstar payloads in v1 of 6737 (avoids rewriting viz).

---

## 4. LigandSet helpers to move / delete (D7)

Pose-specific surface on `LigandSet` today:

| Symbol | Action |
| --- | --- |
| `_resolve_pose_entry_paths` | Move to `pose.py` (Pose already calls it) |
| `_apply_file_path_to_paths` | Move with above |
| `_path_points_to_existing_local_file` | Move or keep private util |
| `_strip_nonempty_str` | Move or share tiny util |
| `_POSE_JSON_RESERVED` / `_ligand_from_pose_dict` | Delete once `from_json` pose path gone |
| `LigandSet.from_json` (pose-shaped) | Deprecate → `PoseSet.from_json`; remove or thin wrapper |
| `LigandSet.from_result` | Deprecate → `PoseSet.from_result`; remove after call sites updated |
| `filter_top_poses` / `_get_pose_score` / `_get_binding_energy` | Move to `PoseSet` |
| Bulk `LigandSet.download` | Keep for real ligands; add `PoseSet.download` (do not remove ligand download) |

Keep `to_ligand_set()` as an explicit escape hatch for one release if needed;
do not keep silent LigandSet returns from docking.

---

## 5. Breaking public API surface

| API | Before | After |
| --- | --- | --- |
| `Docking.get_results` | `LigandSet` | `PoseSet` |
| `Docking.get_poses` | `LigandSet` | `PoseSet` |
| `Docking.run` | `LigandSet \| None` | `PoseSet \| None` |
| `ConstrainedDocking.get_results` / `get_poses` / `run` | `LigandSet` | `PoseSet` |
| `LigandSet.from_result` | load poses | Remove or hard-deprecate |
| `LigandSet.from_json` (pose rows) | hydrate poses as Ligands | Remove / redirect |
| `LigandSet.filter_top_poses` | on LigandSet | on PoseSet |
| Pose path static helpers | on LigandSet | on Pose / PoseSet module |

Optional same PR (recommended): `get_reference_pose() → Pose` for constrained
docking (aligns with D1; feeds 6738).

Identity change users will notice: `pose.id` is the **pose result id**, not
`ligand_id`. Legacy pose-hydrated ligands stuffed pose id into
`properties["id"]` / `pose_result_id`.

---

## 6. Suggested order of work

1. **PoseSet parity** — `download`, `to_dataframe` (+ `show_df` if cheap),
   `filter_top_poses`, optional `to_sdf`; unit tests in `tests/test_pose.py`.
2. **Move path helpers** from `LigandSet` → `pose.py`; keep thin aliases only if
   needed for one commit.
3. **Flip loaders** — `load_scored_poses_from_result_explorer` and
   `load_docking_poses_from_execution` return `PoseSet`; jobOutputs fallback uses
   `PoseSet.from_json`.
4. **Flip docking public APIs** — `Docking` + `ConstrainedDocking`
   (`get_results` / `get_poses` / `run`); update type hints + docstrings.
5. **Viz adapters** — `normalize_pose_ligands` accept `PoseSet` (bridge via
   `to_ligand_set` OK).
6. **Delete / deprecate LigandSet pose APIs** — `from_result`, pose `from_json`,
   `filter_top_poses`; update remaining call sites.
7. **Tests** — docking, constrained docking, pose; drop Phase-2 “still LigandSet”
   assertion.
8. **Docs + notebooks** — tools/tutorial/how-to/ref; phase-2 notebook → phase-3;
   migration notes in PR body (changelog is auto-generated from releases).
9. **Optional same PR** — `get_reference_pose → Pose`.

---

## 7. Test / docs checklist

- [ ] `uv run pytest tests/test_docking.py tests/test_constrained_docking.py tests/test_pose.py --env local`
- [ ] Assert `isinstance(..., PoseSet)` and `pose.id != pose.ligand_id`
- [ ] `get_poses` leaves local SDF paths set after download
- [ ] Constrained docking still skips unscored `reference_pose` rows in scored loaders
- [ ] Docs: docking tools/tutorial/ref/pose + FEP how-to
- [ ] Notebooks promoted via dirty → `./scripts/notebooks.sh`
- [ ] PR Summary: **Breaking** migration snippet  
  (`LigandSet` → `PoseSet`, `PoseSet.from_result`, `to_ligand_set()` escape hatch)

---

## 8. DDOS-6738 ordering

**Do 6737 before 6738.**

| | 6737 | 6738 |
| --- | --- | --- |
| Goal | Docking **outputs** `PoseSet` | SystemPrep / ABFE / RBFE **inputs** `pose` / `pose1` / `pose2` |
| Shared deps | Phase 2 `Pose`/`PoseSet` (done); toolbox pose schemas (6735 Done) | Same |
| Coupling | FEP notebooks today: `get_poses()` → LigandSet → pass as ligands | Needs real `Pose` objects with pose ids/paths |

6738 can start in parallel against `Pose.from_sdf` / `PoseSet.from_result`, but
end-to-end docking → FEP docs need 6737 first. Shared work: Pose file/id payload
helpers and reference-pose-as-`Pose` for constrained docking.

---

## Sources

- Jira DDOS-6737 / 6738 / epic DDOS-6863
- Confluence: Poses vs Ligands (D5, D7, Phase 3)
- Code: `docking.py`, `constrained_docking.py`, `docking_common.py`, `pose.py`,
  `ligand.py` (LigandSet pose section)
- PR #594 (DDOS-6736)
- Git: no `6737` WIP branch
