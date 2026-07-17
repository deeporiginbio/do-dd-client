# `deeporigin.drug_discovery.structures.prepared_system`

`PreparedSystem` holds the output of system preparation: the binding and
solvation XML files and the system PDB. You get one back from `SystemPrep.run()`
and pass it to [`ABFE`](abfe.md) or [`RBFE`](rbfe.md) to reuse a prepared system
and skip the preparation step.

::: src.drug_discovery.structures.prepared_system
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
