# ProteinPrep

Prepare a [`Protein`](../ref/protein.md) for virtual screening or target work
with the Deep Origin Protein Prep tool. Protein Prep cleans the structure using
the chain, cofactor, water, and ligand lists you pass in, then runs loop
modelling and protonation.

`ProteinPrep` is **async only**: submit with `start()`, track with `wait()` or
`watch()`, then load the prepared structure with `get_results()`. There is no
`run()`, and this tool does not produce a cost quote.

`get_results()` returns an in-memory [`Protein`](../ref/protein.md) whose
`remote_path` points at the prepared PDB. That object has no platform protein
id until you `sync()` or `update()` it. The input protein on the `ProteinPrep`
instance is unchanged.

## Preparing a protein

Create a protein, then a `ProteinPrep`. The tool needs a 4-character
[Protein Data Bank (PDB) :octicons-link-external-16:](https://www.rcsb.org/)
ID for loop-modelling templates. If the protein already has `pdb_id` (for
example from `Protein.from_pdb_id`), you can omit it.

```{.python notest}
from deeporigin.drug_discovery import Protein, ProteinPrep, BRD_DATA_DIR

protein = Protein.from_file(BRD_DATA_DIR / "brd.pdb")
prep = ProteinPrep(protein, pdb_id="1EBY")
prep.start()
prep.wait()
prepared = prep.get_results()
```

In a notebook, watch progress while the execution runs:

```{.python notest}
prep = ProteinPrep(protein, pdb_id="1EBY")
prep.start()
task = await prep.watch()
prep.wait()
prepared = prep.get_results()
```

Optional keep and remove lists match the tool inputs. Empty keep-chain means
keep all chains; empty cofactor and water lists keep none of those; empty
remove-ligand means no extra ligand names are stripped.

```{.python notest}
prep = ProteinPrep(
    protein,
    pdb_id="1EBY",
    keep_chain_ids=["A"],
    keep_cofactor_ids=["MG", "ZN"],
    keep_water_residue_names=["HOH"],
    remove_ligand_ids=["LIG"],
)
```

## Working with existing runs

Reconnect to a Protein Prep run started earlier, in this or a previous session:

```{.python notest}
from deeporigin.drug_discovery import ProteinPrep

prep = ProteinPrep.from_id("<executionId>")
# Or the most recently created ProteinPrep run:
prep = ProteinPrep.from_last_run()

prep.sync()
prepared = prep.get_results()
```
