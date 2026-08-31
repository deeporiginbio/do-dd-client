# Structure Report

Grade a protein structure for target preparation. Provide a local
[`Protein`](../ref/protein.md) file, a four-character
[Protein Data Bank (PDB) :octicons-link-external-16:](https://www.rcsb.org/)
ID, or both. Call `run()` to get letter grades and component scores from the
platform — the client does not recompute grades.

You must be logged in (`deeporigin login`) before calling `run()`. The call
blocks until the job finishes.

## Local structure

Upload or sync a `Protein`, then grade it. Passing `pdb_id` alongside the
protein tells the tool to use the PDB entry for experimental metadata
(organism, method, resolution, Rfree, ligand) while coverage still comes from
your coordinates:

```{.python notest}
from deeporigin.drug_discovery import Protein, StructureReport

protein = Protein.from_file("my_target.pdb")
protein.sync()

rows = StructureReport(protein=protein, pdb_id="1ABC").run()
row = rows[0]
row.grade, row.weighted_score, row.resolution
```

## Remote PDB ID only

When you only have a PDB ID and do not need to upload coordinates, pass
`pdb_id` alone. The tool scores from RCSB metadata (no structure file):

```{.python notest}
from deeporigin.drug_discovery import StructureReport

rows = StructureReport(pdb_id="1ABC").run()
rows[0].grade, rows[0].metadata_source
```

## Quote cost

Structure Report billing may be skipped on the platform, but the usual quote
pattern still works:

```{.python notest}
job = StructureReport(pdb_id="1ABC")
job.run(quote=True)
job.estimate
```

## Working with a past run

Reconnect by execution id (or use `from_last_run()`), then use the inherited
`get_results()` to load indexed rows from the data platform:

```{.python notest}
from deeporigin.drug_discovery import StructureReport

job = StructureReport.from_id("<executionId>")
job.sync()
job.get_results()
```

See also the API reference for
[`StructureReport`](../ref/structure_report.md) and
[`StructureReportResult`](../ref/structure_report_result.md).
