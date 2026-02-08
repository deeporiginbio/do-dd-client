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

# Create a new ligand
ligand = client.data.create_ligand(
    project_id="\\x0011223344556677",
    canonical_smiles="CCOc1ccc2nc(S(=O)(=O)N3CCN(CC3)C)c(N)c2c1",
    inchi_key="BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
    inchi="InChI=1S/C20H24N4O4S/.../h1-4,6-9H,5,10-14H2,(H,22,23)",
    smiles="CCOc1ccc2nc(S(=O)(=O)N3CCN(CC3)C)c(N)c2c1",
    name="Compound-12345",
    formal_charge=0,
    hbond_donor_count=1,
    hbond_acceptor_count=6,
    rotatable_bond_count=5,
    tpsa=85.12,
    molecular_weight=447.5,
)

# List projects
projects = client.data.list_projects()

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
