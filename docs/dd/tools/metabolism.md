# Metabolism

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
job.get_results()        # site rows
job.get_molecules()      # confidence_tier rows
```

This rehydrates the stored ligands so you can check status or fetch results
without re-specifying anything. ``get_results()`` returns every site row the
job produced.
