# Molprops

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
