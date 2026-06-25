# Results API

The Results API provides access to result-explorer endpoints in the data platform.

When `client.project_id` is set, all `Results` search methods (`get`, `get_poses`,
`get_pockets`, `get_prepared_systems`, `get_abfe_results`, and `with_ligands`)
automatically add `filter.project_id = {"eq": client.project_id}`.

If you also pass `filter_dict["project_id"]`, it must match `client.project_id`.
Conflicting values raise a `ValueError`.

```{.python notest}
from deeporigin.platform.client import DeepOriginClient

client = DeepOriginClient()

# Get docking poses for a protein
poses = client.results.get_poses(protein_id="08BSPN61NYVE3")

# Get results by platform catalog result type (case-insensitive)
typed = client.results.get(
    result_type=["pocket", "pose"],
    filter_dict={"pose_score": {"lt": 1}},
    sort={"measured_at": "desc"},
    limit=50,
)

# Get binding pockets for a protein
pockets = client.results.get_pockets(protein_id="08BSPN61NYVE3")

# Get ABFE (Absolute Binding Free Energy) results
abfe = client.results.get_abfe_results(protein_id="08BSPN61NYVE3")

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

## CLI

With the package installed, the `deeporigin` console script wraps the same APIs. Docking poses match
`DeepOriginClient().results.get_poses(...)`; response JSON is printed to stdout:

```bash
deeporigin results get-poses --limit 1 --effort 1
deeporigin results get-poses --protein 08BSPN61NYVE3 --limit 1 --effort 1
```

Run `deeporigin results get-poses --help` for all options (filters, `--select`, `--ligand-id`, etc.). The protein filter uses `--protein` / `-p`, same as **get-pockets** below.

Binding pockets match `DeepOriginClient().results.get_pockets(...)`:

```bash
deeporigin results get-pockets --protein 08BSPN61NYVE3
deeporigin results get-pockets --limit 1
deeporigin results get-pockets --pocket-count 1
```

For both **get-poses** and **get-pockets**, use `-p` as a short flag for `--protein`. See `deeporigin results get-pockets --help` for `--record-id`, filters, and `--select`.

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
