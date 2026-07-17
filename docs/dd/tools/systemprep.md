# SystemPrep

## Working with existing runs

Reconnect to a `SystemPrep` run started earlier, in this or a previous session,
instead of re-running the preparation:

```{.python notest}
from deeporigin.drug_discovery import SystemPrep

# By execution id:
sp = SystemPrep.from_id("<executionId>")

# Or the most recently created SystemPrep run:
sp = SystemPrep.from_last_run()

sp.sync()               # refresh status from the platform
sp.get_results()
```

This rehydrates the stored inputs so you can check status or fetch the prepared
system without re-specifying anything.
