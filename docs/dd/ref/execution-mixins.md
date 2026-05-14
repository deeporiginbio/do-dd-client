# `deeporigin.drug_discovery.execution_mixins`

Mixins composed with :class:`deeporigin.drug_discovery.execution.Execution` to
add quoting, synchronous runs, or async lifecycle control.

After ``quote()``, a tools execution is typically in ``"Quoted"`` status with a
platform id. :meth:`QuoteMixin.confirm` calls the tools ``:confirm`` endpoint
(same long timeout and no-retries policy as
:data:`~deeporigin.utils.constants.TOOL_EXECUTION_POST_TIMEOUT_SECONDS` on
:class:`~deeporigin.platform.executions.Executions.confirm`). Async classes call
this from :meth:`AsyncExecutableMixin.start` when resuming a quoted job.

::: src.drug_discovery.execution_mixins
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
