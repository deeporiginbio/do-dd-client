---
status: accepted
---

# ProteinPrep.get_results() returns an in-memory Protein

The platform indexes Protein Prep output as `PreparedProtein`
(`results__preparedproteins`). The CLI still returns an in-memory `Protein`
(`id` unset, `remote_path` = prepared PDB) from `get_results()`, and does not
PATCH or create a proteins-table row.

Exposing a public `PreparedProtein` type would match the catalog but split the
SDK: Docking, PocketFinder, and SystemPrep all take `Protein`. Returning
`Protein` keeps the next step in the same type. Auto-updating the input protein
would be a surprising write inside `get_results()`; auto-creating a second
entity would duplicate identity. Callers persist with `update()` or `sync()`.
