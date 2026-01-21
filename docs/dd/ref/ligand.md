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

## Preparation

Use `Ligand.prepare()` to perform common preparation steps before docking:

- salt removal, kekulization
- validation of atom symbols against supported types

Example:

```python
from deeporigin.drug_discovery.structures import Ligand

lig = Ligand.from_smiles("C/C=C/Cn1cc(-c2cccc(C(=O)N(C)C)c2)c2cc[nH]c2c1=O")
lig.prepare()  # Preserves hydrogens by default
lig.prepare(remove_hydrogens=True)  # Remove hydrogens from SMILES
```