# Organizations API.

The DeepOriginClient can be used to access the organizations API using:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()
```

Then, the following methods can be used, for example:

```{.python notest}
users = client.organizations.users()
```


::: src.platform.organizations.Organizations
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
        - "!^_"  # Exclude private members (names starting with "_")
      show_signature: true
      show_signature_annotations: true
      show_if_no_docstring: true
      group_by_category: true

