# Projects

Use the high-level `deeporigin.projects` module to list and select data platform
projects, inspect ligands, proteins, and executions for the current project, and
sync structures with project scope.

Requires the **core** optional dependency (includes `pandas`) for DataFrame helpers.

## Configuration

The current project id is stored in `~/.deeporigin/config.json` under `project_id`.
`DeepOriginClient` exposes it as `client.project_id`: `DO_PROJECT_ID` overrides
the on-disk value, and changing the selection with `set_project_id` clears the
client cache so the next `DeepOriginClient.get()` picks up the new id.

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
