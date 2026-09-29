# `deeporigin.drug_discovery.protein_prep`

`ProteinPrep` drives `deeporigin.protein-prep` v10. Recommend inventories
components, returns a component table (`pandas.DataFrame`), and updates the same
object with an editable Selection. Prepare applies resolved keep/skip decisions
and cleans the structure. ``run()`` blocks on served prepare (including loop
modelling); ``find_pockets="novel"`` requires ``start()`` (workflow path).
Pocket-bearing runs support ``quote`` / ``approve_amount`` and ``confirm()``.
Structure reports are not part of this tool — use ``StructureReport``.

::: src.drug_discovery.protein_prep
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
