# Results API

The Results API provides access to result-explorer endpoints in the data platform.

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()

# Get docking poses for a protein
poses = client.results.get_poses(protein_id="08BSPN61NYVE3")

# Get binding pockets for a protein
pockets = client.results.get_pockets(protein_id="08BSPN61NYVE3")

# Get results for a specific tool and protein
results = client.results.get(
    tool_id="deeporigin.bulk-docking",
    protein_id="08BSPN61NYVE3",
)

# Search ligands joined with tool results
results = client.results.with_ligands(
    limit=10,
    experiments=[{"toolId": "deeporigin.docking"}],
)
```


::: src.platform.results.Results
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
