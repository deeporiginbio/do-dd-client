# `deeporigin.drug_discovery.Complex` (removed)

> **Removed:** The `Complex` type and its legacy workflow helpers are no longer part of the SDK. That included `Complex.prepare`, the former `Complex.abfe` path (`complex_abfe` module), and `Complex.rbfe` (`rbfe` module). Use [`Docking`](docking.md), [`ABFE`](abfe.md), [`PocketFinder`](../how-to/find-pockets.md), and `SystemPrep` from `deeporigin.drug_discovery.system_prep` (or `deeporigin.functions.sysprep`) instead. The former [`RBFE`](rbfe.md) helper documentation applies to removed RBFE-on-Complex code as well.

Historical tutorials under `dd/tutorial/` and how-tos that referenced `Complex` are retained only as context for old notebooks.
