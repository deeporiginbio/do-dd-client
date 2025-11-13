## `platform.tools_api`

API to interact with the tools API. To list available methods in this module, use:

```{.python notest}
from deeporigin.platform import tools_api
tools_api.__all__
```

::: src.platform.tools_api
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

## `platform.client.Tools`

Tools API wrapper for DeepOriginClient. Provides access to tools-related endpoints.

Example usage:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient(token="my-token", org_key="my-org")

# List all available tool definitions
all_tools = client.tools.list()

# Get all versions of a specific tool
tool_versions = client.tools.get_by_key(tool_key="my-tool-key")
```

::: src.platform.tools
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