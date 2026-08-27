# `deeporigin.drug_discovery.metabolism`

`Metabolism` drives platform tool `deeporigin.metabolism`. It scores ligands
for sites of metabolism on nine cytochrome P450 (CYP) isoforms.
``run()`` blocks and returns a table of sites. ``get_molecules()`` returns
molecule-level reliability tiers. There is no quote and no ``start()``.

::: src.drug_discovery.metabolism
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
