# `deeporigin.drug_discovery.Ligand`

::: src.drug_discovery.structures.Ligand
    options:
      docstring_style: google
      show_root_heading: false
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

## ADMET (molprops) attributes

After you run [`Molprops`](../how-to/ligands.md#predicting-admet-properties) on the ligand, scalar and structured predictions from the Deep Origin molprops tools are stored on the ligand as well as in `properties` and RDKit properties:

- `log_s`, `log_d`, `log_p` — map to API keys `logS`, `logD`, `logP`
- `herg`, `cyp`, `ames` — nested structures keyed as `hERG`, `cyp`, `ames` in the API response
- `has_pains`, `pains_fragments` — PAINS screening results

Until molprops has been run successfully (via `Molprops`), these fields remain `None`.

## Preparation

Use `Ligand.prepare()` to perform common preparation steps before docking:

- salt removal, kekulization
- fragment validation (rejects multiple non-identical fragments)
- validation of atom symbols against supported types

Example:

```python
from deeporigin.drug_discovery.structures import Ligand

lig = Ligand.from_smiles("CCO", name="Ethanol")
lig.prepare()  # Preserves hydrogens by default
lig.prepare(remove_hydrogens=True)  # Remove hydrogens from SMILES
```