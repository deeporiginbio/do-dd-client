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

client = DeepOriginClient.get(token="my-token", org_key="my-org")

# List all available tool definitions
all_tools = client.tools.get_all()

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

## `platform.client.Functions`

Functions API wrapper for DeepOriginClient. Provides access to functions-related endpoints.

Example usage:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.get(token="my-token", org_key="my-org")

# Run the latest version of a function
result = client.functions.run_latest(
    key="my-function-key",
    params={"input": "value"},
    cluster_id="cluster-123",
    tag="optional-tag",
)
```

::: src.platform.functions
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

## `platform.client.Clusters`

Clusters API wrapper for DeepOriginClient. Provides access to clusters-related endpoints.

Example usage:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.get(token="my-token", org_key="my-org")

# List all clusters
clusters = client.clusters.list()

# List clusters with pagination and filtering
clusters = client.clusters.list(
    page=0,
    page_size=10,
    order="hostname? asc",
    filter="enabled=true",
)
```

::: src.platform.clusters
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

## `platform.client.Files`

Files API wrapper for DeepOriginClient. Provides access to files-related endpoints.

Example usage:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient.get(token="my-token", org_key="my-org")

# List all files in a directory recursively
files = client.files.list_files_in_dir(file_path="entities/")

# List files with specific parameters
files = client.files.list_files_in_dir(
    file_path="entities/",
    recursive=False,
    max_keys=100,
    prefix="entities/subdir/",
)

# Upload a file
result = client.files.upload_file(
    local_path="/path/to/local/file.txt",
    remote_path="entities/uploaded_file.txt",
)
```

::: src.platform.files
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