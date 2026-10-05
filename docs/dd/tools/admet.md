# ADMET (Admet)

Predict absorption, distribution, metabolism, excretion, and toxicity endpoints
via `deeporigin.admet-properties` (CLI: `Admet`, tool major version `2`).

ADMET is **billed** (DO_TOGO, per molecule). Inline `ligands` are limited to
**100** structures; larger sets upload a Ligand list file automatically and run
as an async workflow. Project-wide runs use `ligands=[]` with
`client.project_id` set and call `start()` only.

```{.python notest}
from deeporigin.drug_discovery import Admet, Ligand

ligand = Ligand.from_smiles("CCO")
admet = Admet(ligands=[ligand])
admet.properties = ["hERG_classification", "AMES_classification"]
df = admet.run()
```

## Bulk and project runs

```{.python notest}
# 101+ ligands: async workflow (auto ligands_file)
from deeporigin.drug_discovery import LigandSet

ligand_set = LigandSet.from_csv("ligands.csv")  # "smiles" column
large = Admet(ligands=ligand_set, batch_size=100)  # optional; smaller batches run more in parallel (min 50)
large.start()
large.wait()
df = large.get_results()

# All ligands in the current project (client.project_id must be set):
project_admet = Admet(ligands=[])
project_admet.properties = ["hERG_classification"]
project_admet.start()
project_admet.wait()
df = project_admet.get_results()
```

## Quotes and confirmation

Request an estimate with `run(quote=True)` or `start(quote=True)`. When the
platform returns `Quoted` status from a normal `run()` (for example when the
cost exceeds your auto-approve threshold), `run()` returns `None` — call
`confirm()`, then `get_results()`.

Molprops remains free; use `Admet` for toxicity and related ADMET endpoints,
not `Molprops`.

## Working with existing runs

```{.python notest}
from deeporigin.drug_discovery import Admet

job = Admet.from_id("<executionId>")
job.get_results()
```

`from_dto` / `from_id` restore inline ligands, `ligands_file`, or project-only
inputs from Studio or prior SDK sessions.
