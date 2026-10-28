# RBFE workflows

Relative binding free energy (RBFE) in the drug discovery SDK is supported through:

- **`RBFE`** — batch workflow on platform tool `deeporigin.rbfe` (`steps`: `["konnektor", "system-prep", "rbfe"]`, `["system-prep", "rbfe"]`, `["system-prep"]`, or `["rbfe"]`). Up to 20 pose pairs per execution. See the [RBFE tutorial](../tutorial/rbfe.md).
- **`SystemPrep`** in RBFE mode — single-pair sync prep via `deeporigin.system-prep` (pass `pose1` and `pose2`). Useful for one-off prep or when you want fine-grained control before submitting `RBFE(prepared_systems=[...])`.

## Steps

Exactly one of `poses`, `pairs`, or `prepared_systems` must be provided.
`steps` are inferred from that input unless you pass `steps=` yourself.

| Steps | Input | Output |
|------|-------|--------|
| `["konnektor", "system-prep", "rbfe"]` | Shared `protein` + `poses[]` (one per ligand) + `network_type` + FEP params | Konnektor edges, then `system` and `result` records |
| `["system-prep", "rbfe"]` | Shared `protein` + `pairs[]` of poses + FEP params | `system` then `result` records |
| `["system-prep"]` | Shared `protein` + `pairs[]` of poses | `system` records |
| `["rbfe"]` | `prepared_systems[]` + FEP params | `result` records |
| Any plan with `rbfe` + `cycle-closure` | Same inputs plus `exp_abfe` and/or `fep_abfe` anchors | Per-pose absolute dG (`cycleclosureresults`) |

Pass `exp_abfe` and/or `fep_abfe` to `RBFE(...)` to append the `cycle-closure`
step automatically. At least one anchor is required: `{"pose_id", "dG", "std"?,
"abfe_result_id"?}`, where `pose_id` is a pose in the network.
`ABFE.to_anchor()` builds one from an ABFE run. See
[RBFE cycle-closure workflow notebook](../../notebooks/clean/rbfe-6-cycle-closure-workflow.ipynb).

For Konnektor mode, each ligand must be synced and registered (platform `id` and
`file_path` required). Use `SystemPrep` for single-pair prep without FEP.

Start executions via `RBFE.start()` or the [Platform executions API](../../platform/ref/executions.md).

Rehydrate a submitted run with `RBFE.from_id(execution_id)`, `RBFE.from_last_run()`, or `RBFE.from_dto(dto)` to refresh status, watch progress in notebooks, or inspect stored inputs.

After an RBFE leg completes, `RBFE.get_results()` returns a summary DataFrame with `protein_id`, `pose1_id`, `pose2_id`, `ligand1_id`, `ligand2_id`, and `ddG` (free-energy difference from `total` with `unit`, e.g. `-3875.483 kcal/mol`).

When the workflow includes cycle closure, `RBFE.get_cycle_closure_results()` returns
per-pose absolute dG values with columns `pose_id`, `ligand_id`, `dG`, `unit`, and
optional `cluster`.

## Prepared systems

`RBFE.get_prepared_system(pose1_id=..., pose2_id=...)` loads a `PreparedSystem` from system-prep result rows scoped to this execution (via `PreparedSystem.from_result`); `RBFE.get_prepared_systems()` returns all of them. Optional pose or ligand IDs filter to a specific pair; when omitted or when multiple rows match, the first result is returned. No execution status check is required — if system-prep rows are not available yet, a `DeepOriginException` is raised.

Visualize the returned object in a notebook:

```{.python notest}
ps = rbfe.get_prepared_system(ligand1_id=ligand1.id, ligand2_id=ligand2.id)
ps.show()
ps.show(solute=True)  # solute-only PDB when available
```

This is separate from `RBFE.get_results()`, which reads `deeporigin.rbfe` ΔΔG summary rows rather than prepared-system outputs.
