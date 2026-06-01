# RBFE workflows

Relative binding free energy (RBFE) in the drug discovery SDK is supported through:

- `SystemPrep` in RBFE mode — pass `ligand1` and `ligand2` instead of a single `ligand`. See the [RBFE tutorial](../tutorial/rbfe.md).
- Platform tool `deeporigin.rbfe-end-to-end` for end-to-end pairwise RBFE runs. Start executions via the [Platform executions API](../../platform/ref/executions.md) using prepared system outputs from `SystemPrep.run()`.

There is no `deeporigin.drug_discovery.rbfe` module in the SDK.
