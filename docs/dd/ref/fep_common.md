# `deeporigin.drug_discovery.fep_common`

Shared FEP parameter types and serialization helpers used by `ABFE` and `RBFE`.

- [`ABFEParams`](#abfeparams) — absolute FEP defaults (`binding_n_windows=48`,
  `solvation_n_windows=32`)
- [`RBFEParams`](#rbfeparams) — relative FEP defaults (`binding_n_windows=24`,
  `solvation_n_windows=24`), matching MDSuite when `n_windows` is unset for a
  two-ligand (relative) run

::: src.drug_discovery.fep_common
    options:
      docstring_style: google
      show_root_heading: false
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: true
      members_order: alphabetical
      filters:
        - "!^_"
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true
