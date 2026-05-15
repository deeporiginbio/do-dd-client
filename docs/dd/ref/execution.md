# `deeporigin.drug_discovery.execution`

Base class for jobs-centric execution objects (`Docking`, `ABFE`, etc.).

Use :meth:`Execution.sync` to refresh any instance that already has an
execution id (including sync-only tools and objects built from ``from_dto``).

## Quote mode (sync vs async)

``quote()`` creates a persisted tools execution with ``approveAmount=0``. The
payload is built by :meth:`Execution._make_payload` and must match the
path you will use after :meth:`Execution.confirm`:

- ``quote(mode="async")`` — same shape as a later async :meth:`~deeporigin.drug_discovery.execution_mixins.AsyncExecutableMixin.start` (after confirm).
- ``quote(mode="sync")`` — same shape as a blocking :meth:`~deeporigin.drug_discovery.execution_mixins.SyncExecutableMixin.run`.

``confirm()`` only sends ``executionId`` to the platform; it cannot change inputs
or switch sync/async. The SDK stores ``_quoted_mode`` so ``start()`` rejects a
sync-mode quote and ``run()`` can reject an async-mode quote (see each tool).

::: src.drug_discovery.execution
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
