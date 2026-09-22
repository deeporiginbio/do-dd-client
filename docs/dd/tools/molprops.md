# Molprops

Predict physicochemical properties and RDKit descriptors for ligands via
`deeporigin.mol-props-combined` (CLI: `Molprops`).

Requestable keys (default is the full set): `logd`, `logp`, `logs`, `pains`,
`molecular_weight`, `hbond_donor_count`, `hbond_acceptor_count`,
`rotatable_bond_count`, `tpsa`, `rule_of_5_violations`, `sa_score`.

Results land on named `Ligand` attributes (for example `ligand.sa_score`,
`ligand.log_p`), not in `ligand.properties`. Toxicity endpoints belong on
`Admet`, not Molprops.

```{.python notest}
from deeporigin.drug_discovery import Ligand, Molprops

ligand = Ligand.from_smiles("CCO")
Molprops(ligands=[ligand], props=["logp", "sa_score"]).run()
assert ligand.log_p is not None
assert ligand.sa_score is not None
```

## Working with existing runs

Reconnect to a `Molprops` run started earlier, in this or a previous session,
instead of re-running the prediction:

```{.python notest}
from deeporigin.drug_discovery import Molprops

# By execution id:
mp = Molprops.from_id("<executionId>")

# Or the most recently created Molprops run:
mp = Molprops.from_last_run()

mp.sync()               # refresh status from the platform
mp.get_results()
```

This rehydrates the stored inputs so you can check status or fetch results
without re-specifying anything.
