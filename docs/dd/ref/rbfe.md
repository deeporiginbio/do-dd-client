# RBFE workflows

Relative binding free energy (RBFE) in the drug discovery SDK is supported through:

- **`RBFE`** — batch workflow on platform tool `deeporigin.rbfe` (`mode`: `full`, `sysprep`, or `rbfe`). Up to 20 ligand pairs per execution. See the [RBFE tutorial](../tutorial/rbfe.md).
- **`SystemPrep`** in RBFE mode — single-pair sync prep via `deeporigin.system-prep` (pass `ligand1` and `ligand2`). Useful for one-off prep or when you want fine-grained control before submitting `RBFE(mode="rbfe", ...)`.

## Modes

| Mode | Input | Output |
|------|-------|--------|
| `full` | Shared `protein` + `pairs[]` + FEP params | `systems[]` and `results[]` |
| `sysprep` | Shared `protein` + `pairs[]` | `systems[]` |
| `rbfe` | `prepared_systems[]` + FEP params | `results[]` |

Start executions via `RBFE.start()` or the [Platform executions API](../../platform/ref/executions.md).
