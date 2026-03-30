# Projects

Use the high-level `deeporigin.projects` module to list and select data platform
projects, inspect ligands, proteins, and executions for the current project, and
sync structures with project scope.

Requires the **core** optional dependency (includes `pandas`) for DataFrame helpers.

## Configuration

The active project is whatever
`DeepOriginClient().project_id` holds in memory.

When `DO_AUTH_TOKEN`, `DO_ORG_KEY`, and `DO_BASE_URL` are all set, the no-arg
`DeepOriginClient()` resolves via environment variables and optional `DO_PROJECT_ID`.
Otherwise the client is built from disk (`from_disk`) with `project_id` unset until
you call `projects.load(...)` or `projects.create(...)`, which assign
`client.project_id` for that process (again, no disk write).

## API reference

::: deeporigin.projects
    options:
      heading_level: 2
      docstring_style: google
      show_root_heading: true
      show_category_heading: true
      show_object_full_path: false
      show_root_toc_entry: false
      inherited_members: false
      members_order: alphabetical
      filters:
        - "!^_"
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true

## Platform client

Lower-level access uses `deeporigin.platform.projects.Projects` on
`~deeporigin.platform.client.DeepOriginClient` — see `docs/platform/ref/projects.md`.
