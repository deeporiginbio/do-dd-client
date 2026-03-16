# Projects API

The Projects API provides access to project-related endpoints in the data platform.

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()

# List projects
projects = client.projects.list()
```


::: src.platform.projects.Projects
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
