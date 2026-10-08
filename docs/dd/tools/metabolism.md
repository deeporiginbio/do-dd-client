# Metabolism

## Fetch indexed results without a job

When ligands already have Metabolism scores on the data platform, load them
with class-level helpers (not bound to an execution):

```{.python notest}
from deeporigin.drug_discovery import Metabolism

sites = Metabolism.fetch_results(ligands=ligands)
mols = Metabolism.fetch_molecules(ligands=ligands)
```

These query by each ligand's platform id. Ligands without an id are skipped in
the filter; missing indexed rows are omitted (partial or empty tables are fine).
Indexed workflow rows often omit Caller SMILES; ``fetch_*`` fills ``smiles``
from the ligands you pass, matched by platform id.

Instance ``get_results()`` / ``get_molecules()`` still mean **this job only**.
Do not call ``Metabolism.get_results(ligands)`` — that binds ligands as
``self``; use ``fetch_results`` / ``fetch_molecules`` instead.

## Site row filters (client-side)

``run()``, ``get_results()``, and ``fetch_results()`` accept optional
keyword-only ``top_k`` or ``min_prob`` (mutually exclusive). Omit both to
return every atom-by-enzyme row the tool stored. ``top_k`` ranks within each
``(ligand, enzyme)`` group; ``min_prob`` keeps rows with
``probability >= min_prob``. Legacy top-three views use ``top_k=3``.

``fetch_results()`` is history-preserving across indexed jobs. After a forced
rerun, use ``job.get_results()`` on that execution for the authoritative full
site set.

## Force recompute

``run(force=True)`` and ``start(force=True)`` bypass the client refusal and
workflow skip when ligands already have indexed ``MetabolismMolecule`` rows.
Default behavior is unchanged.

## Already scored ligands

Before ``run()`` or ``start()``, the client checks indexed Metabolism molecule
rows:

- If **every** ligand has a platform id and **every** id is already scored, the
  call raises and no job is created. Use ``fetch_results`` / ``fetch_molecules``
  instead.
- If the job still proceeds and **any** ligand id is already indexed, a
  ``UserWarning`` is emitted. Instance ``get_*`` methods still return only this
  execution's new rows — use ``fetch_*`` for the full set.

Pass ``force=True`` to ``run()`` or ``start()`` to recompute ligands that
already have indexed rows (see **Force recompute** above).

## Working with existing runs

Reconnect to a `Metabolism` run started earlier, in this or a previous session,
instead of re-running the prediction:

```{.python notest}
from deeporigin.drug_discovery import Metabolism

# By execution id:
job = Metabolism.from_id("<executionId>")

# Or the most recently created Metabolism run:
job = Metabolism.from_last_run()

job.sync()               # refresh status from the platform
job.get_results()        # site rows for this execution
job.get_molecules()      # confidence_tier rows for this execution
```

This rehydrates the stored ligands so you can check status or fetch results
without re-specifying anything. ``get_results()`` returns every site row the
job produced.

## Large batches

For 30 or more ligands, use ``start()`` instead of ``run()``:

```{.python notest}
job = Metabolism(ligands=many_ligands)
job.start()
job.wait()               # or await job.watch() in a notebook
sites = job.get_results()
mols = job.get_molecules()
```

Batches larger than 100 ligands still use the same API. The client writes a
Ligand list file, uploads it, and passes that file to the tool automatically —
you do not choose a separate file input.