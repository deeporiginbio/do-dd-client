# `deeporigin.drug_discovery.execution_helpers`

Helpers shared by tool execution classes (for example `Docking`, `PocketFinder`,
`SystemPrep`):

- `price_total_from_execution_dto(dto)` — reads `priceTotal` from the first
  successful row in `dto["quotationResult"]["successfulQuotations"]`, or
  returns `None`.

::: src.drug_discovery.execution_helpers
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
