# Execution display (notebook HTML)

Jupyter helpers such as :class:`~deeporigin.drug_discovery.notebook_watch_mixin.NotebookWatchMixin` render execution state using :class:`~deeporigin.platform.execution_display.ExecutionDisplay` — a small Bootstrap card with progress and metadata, without the legacy ``Job`` widget.

When ``progressReport`` is a v2 execution tree (root node with ``displayName`` and ``status``), the card body renders an indented HTML/SVG tree via :func:`~deeporigin.platform.progress_tree_display.render_progress_tree_html`: status-colored nodes, optional SVG completion rings from ``toolProgress.complete``, and expandable error details on failed steps. Legacy shapes (flat ``{"complete": n}`` or batched workflow keys) keep the Bootstrap horizontal progress bar while ``status`` is ``Running``.

::: src.platform.execution_display.ExecutionDisplay
    options:
      heading_level: 2
      docstring_style: google
      show_root_heading: true
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: true
      members_order: alphabetical
      filters:
        - "!^_"
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true
