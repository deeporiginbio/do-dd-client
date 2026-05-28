# `deeporigin.drug_discovery.execution_mixins`

Mixins composed with :class:`deeporigin.drug_discovery.execution.Execution` to
add synchronous ``run()`` or async lifecycle control (``start``, ``cancel``).

Quoting, ``confirm()``, :attr:`~deeporigin.drug_discovery.execution.Execution.runtime`,
:meth:`~deeporigin.drug_discovery.execution.Execution.sync`, and platform ``id`` /
``dto`` live on :class:`deeporigin.drug_discovery.execution.Execution`. After ``quote()``,
a tools execution is typically in ``"Quoted"`` status. :meth:`Execution.confirm`
calls the tools ``:confirm`` endpoint (same long timeout and no-retries policy
as :data:`~deeporigin.utils.constants.TOOL_EXECUTION_POST_TIMEOUT_SECONDS` on
:class:`~deeporigin.platform.executions.Executions.confirm`), then applies the
returned DTO with :meth:`~deeporigin.drug_discovery.execution.Execution.update_from_dto`.
Async classes call this from :meth:`AsyncExecutableMixin.start` when resuming a
quoted job that was quoted with ``mode="async"``; poll with
:meth:`~deeporigin.drug_discovery.execution.Execution.sync` until terminal if the
confirm response is not yet ``Succeeded``.

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
