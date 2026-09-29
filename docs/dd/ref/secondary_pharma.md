# `deeporigin.drug_discovery.secondary_pharma`

`SecondaryPharmacology` drives platform tool `deeporigin.secondary-pharma`. It
scores ligands against a baked kinase panel, using either a served ligand-ML
path (`method="ligand-ml"`, use `run()`) or an async docking workflow
(`method="docking"`, use `start()`). See the
[tool guide](../tools/secondary-pharma.md) for the full explanation of why
these are separate execution modes on one class.

::: src.drug_discovery.secondary_pharma
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
