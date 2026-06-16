# `deeporigin.drug_discovery.patent`

`Patent` drives platform tool `deeporigin.draco` to extract chemical structures from
a PDF document. The workflow is async-only: quote with ``start(quote=True)``,
``confirm()``, then ``wait()`` and ``get_results()``.

::: src.drug_discovery.patent
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
