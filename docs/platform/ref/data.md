# Data Platform API.

The DeepOriginClient can be used to access the data platform API using:

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()
```

Then, the following methods can be used, for example:

```{.python notest}
# Check the health status of the data platform
health_status = client.data.health()

# Search ligands joined with tool results
results = client.data.search_ligands_with_results(
    limit=10,
    experiments=[{"toolId": "deeporigin.docking"}],
)

# Search an entity (e.g., ligands)
results = client.data.search("ligands")

# Search ligands using convenience method
results = client.data.search_ligands(limit=10)

# Search proteins using convenience method
results = client.data.search_proteins(limit=10)

# List public models
models = client.data.list_models()
```


::: src.platform.data.Data
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
