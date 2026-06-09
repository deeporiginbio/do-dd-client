# `deeporigin.drug_discovery.abfe`

`ABFE` drives platform tool `deeporigin.abfe-end-to-end`. Constructor inputs infer workflow
`steps` the same way as [`RBFE`](rbfe.md): `protein` + `ligand` runs
`["system-prep", "abfe"]`; `prepared_system` runs `["abfe"]` only. FEP
simulation settings are shared with RBFE via [`ABFEParams`](fep_common.md)
(also exported as `RBFEParams` from `rbfe`).

::: src.drug_discovery.abfe
    options:
      docstring_style: google
      show_root_heading: false
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: true
      members_order: alphabetical
      filters:
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true