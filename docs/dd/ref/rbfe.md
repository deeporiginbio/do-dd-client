# RBFE workflows

Relative binding free energy (RBFE) in the drug discovery SDK is supported through:

- **`RBFE`** — batch workflow on platform tool `deeporigin.rbfe` (`steps`: `["system-prep"]`, `["system-prep", "rbfe"]`, or `["rbfe"]`). Up to 20 ligand pairs per execution. See the [RBFE tutorial](../tutorial/rbfe.md).
- **`SystemPrep`** in RBFE mode — single-pair sync prep via `deeporigin.system-prep` (pass `ligand1` and `ligand2`). Useful for one-off prep or when you want fine-grained control before submitting `RBFE(prepared_systems=[...])`.

## Steps

| Steps | Input | Output |
|------|-------|--------|
| `["system-prep", "rbfe"]` | Shared `protein` + `pairs[]` + FEP params | `system` then `result` records |
| `["system-prep"]` | Shared `protein` + `pairs[]` | `system` records |
| `["rbfe"]` | `prepared_systems[]` + FEP params | `result` records |

Start executions via `RBFE.start()` or the [Platform executions API](../../platform/ref/executions.md).

Rehydrate a submitted run with `RBFE.from_id(execution_id)`, `RBFE.from_last_run()`, or `RBFE.from_dto(dto)` to refresh status, watch progress in notebooks, or inspect stored inputs.

After an RBFE leg completes, `RBFE.get_results()` returns a summary DataFrame with `protein_id`, `ligand1_id`, `ligand2_id`, and `ddG` (free-energy difference from `total` with `unit`, e.g. `-3875.483 kcal/mol`).

## Prepared systems

`RBFE.get_prepared_system(ligand1_id=..., ligand2_id=...)` loads a `PreparedSystem` from system-prep result rows scoped to this execution (via `PreparedSystem.from_result`). Optional ligand IDs filter to a specific pair; when omitted or when multiple rows match, the first result is returned. No execution status check is required — if system-prep rows are not available yet, a `DeepOriginException` is raised.

Visualize the returned object in a notebook:

```python
ps = rbfe.get_prepared_system(ligand1_id=ligand1.id, ligand2_id=ligand2.id)
ps.show()
ps.show(solute=True)  # solute-only PDB when available
```

This is separate from `RBFE.get_results()`, which reads `deeporigin.rbfe` ΔΔG summary rows rather than prepared-system outputs.
