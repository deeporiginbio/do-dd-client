# Entities API

The Entities API provides access to ligand and protein records in the data platform.

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()

# Search ligands
results = client.entities.search_ligands(limit=10)

# Search proteins
results = client.entities.search_proteins(limit=10)

# Generic entity search
results = client.entities.search("ligands")

# Create a new ligand
ligand = client.entities.create_ligand(
    smiles="CCOc1ccc2nc(S(=O)(=O)N3CCN(CC3)C)c(N)c2c1",
    name="Compound-12345",
    formal_charge=0,
    hbond_donor_count=1,
    hbond_acceptor_count=6,
    rotatable_bond_count=5,
    tpsa=85.12,
    molecular_weight=447.5,
)

# List public models
models = client.entities.list_models()
```


::: src.platform.entities.Entities
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
