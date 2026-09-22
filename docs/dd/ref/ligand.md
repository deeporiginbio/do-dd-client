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

## Molprops attributes

After you run [`Molprops`](../how-to/ligands.md#predicting-molecular-properties-molprops) on the ligand, or load the ligand with `Ligand.from_id` / `LigandSet.from_ids` when values already exist on the platform record, scalar predictions are stored on dedicated attributes (tool row keys such as `logS`, `sa_score`):

- `log_s`, `log_d`, `log_p` — map to tool keys `logS`, `logD`, `logP` (platform columns `logs_predicted`, `logd_predicted`, `log_p`)
- `has_pains`, `pains_fragments` — PAINS screening (`pains_flag` on the platform record maps to `has_pains`)
- `molecular_weight`, `hbond_donor_count`, `hbond_acceptor_count`, `rotatable_bond_count`, `tpsa`, `rule_of_5_violations` — RDKit descriptors (platform pin `rule_of5_violations` maps to `rule_of_5_violations`)
- `sa_score` — synthetic accessibility (from a `Molprops` run; platform pin pending)

Until molprops has been run or the platform record has pinned values, these fields remain `None`. `pains_fragments` is only available from a fresh `Molprops` run when the platform pin is absent. Toxicity endpoints (AMES, hERG, CYP) belong on `Admet`, not Molprops.

## Preparation

Use `Ligand.prepare()` to perform common preparation steps before docking:

- organic-parent selection (counterion stripping when unambiguous), kekulization
- fragment validation (rejects multiple non-identical fragments)
- validation of atom symbols against supported types

Example:

```python
from deeporigin.drug_discovery.structures import Ligand

lig = Ligand.from_smiles("CCO", name="Ethanol")
lig.prepare()  # Preserves hydrogens by default
lig.prepare(remove_hydrogens=True)  # Remove hydrogens from SMILES
```