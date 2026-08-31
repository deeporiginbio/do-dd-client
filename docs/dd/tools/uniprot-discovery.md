# UniProt discovery

Map a [UniProtKB :octicons-link-external-16:](https://www.uniprot.org/)
accession to ranked experimental
[Protein Data Bank (PDB) :octicons-link-external-16:](https://www.rcsb.org/)
structures. Call `run()` to browse candidates (letter grades and scores from the
platform). Call `import_proteins()` to download selected (or recommended) PDBs
and sync them into a project with `uniprot_accession` set.

You must be logged in (`deeporigin login`) before calling `run()` or
`import_proteins()`. Those calls block until the job finishes. Import requires a
project id (pass `project_id=...` or set it on the client).

## Browse candidates

```{.python notest}
from deeporigin.drug_discovery import UniprotDiscovery

job = UniprotDiscovery(uniprot_accession="P00533", client=client)
candidates = job.run()
recommended = next(c for c in candidates if c.recommended)
recommended.pdb_id, recommended.grade, recommended.weighted_score
```

## Import recommended into a project

When `pdb_ids` is omitted, `import_proteins()` syncs the single recommended
candidate:

```{.python notest}
from deeporigin.drug_discovery import UniprotDiscovery

job = UniprotDiscovery(uniprot_accession="P00533", client=client)
proteins = job.import_proteins(project_id=client.project_id)
proteins[0].pdb_id, proteins[0].uniprot_accession, proteins[0].id
```

## Import selected PDB IDs

Selected IDs must appear in this accession's candidate list (otherwise the
client raises):

```{.python notest}
proteins = job.import_proteins(
    ["1M17", "4WR2"],
    project_id=client.project_id,
)
```

## One-liner for the recommended protein

[`Protein.from_uniprot`](../ref/protein.md) is thin sugar for the recommended
path (`import_proteins()[0]`). For browsing or multi-select, use
`UniprotDiscovery` directly:

```{.python notest}
from deeporigin.drug_discovery import Protein

protein = Protein.from_uniprot("P00533", project_id=client.project_id, client=client)
protein.pdb_id, protein.uniprot_accession
```

## Quote cost

```{.python notest}
job = UniprotDiscovery(uniprot_accession="P00533", client=client)
job.run(quote=True)
job.estimate
```

See also the API reference for
[`UniprotDiscovery`](../ref/uniprot_discovery.md) and
[`UniprotDiscoveryCandidate`](../ref/uniprot_discovery_candidate.md).
