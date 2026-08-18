# `deeporigin.drug_discovery.protein_prep`

`ProteinPrep` drives platform tool `deeporigin.protein-prep` to clean a protein
structure. The workflow is async-only: ``start()``, then ``wait()`` /
``watch()``, then ``get_results()`` (an in-memory ``Protein``). There is no
``run()`` and no quote.

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
