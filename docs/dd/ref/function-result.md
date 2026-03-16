# `FunctionResult`

All functions (and class methods that wrap them, like `protein.dock()`) return a `FunctionResult`. This object wraps the raw API response and provides convenient access to cost, estimate, and function outputs.

For batch operations (e.g. docking multiple ligands), a single `FunctionResult` aggregates responses from all individual calls, summing costs and estimates automatically.

## Quick reference

```{.python notest}
# Run a function
result = protein.dock(pocket=pocket, ligand=ligand)
result.cost       # actual cost in dollars
result.poses      # domain-specific output (LigandSet for docking)

# Estimate cost without running
result = protein.dock(pocket=pocket, ligand=ligand, quote=True)
result.estimate   # estimated cost in dollars
result.cost       # None
```

## API Reference

::: src.functions.result.FunctionResult
    options:
      docstring_style: google
      show_root_heading: true
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      members_order: source
      filters:
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: false
      group_by_category: true
