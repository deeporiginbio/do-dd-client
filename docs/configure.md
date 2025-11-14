# Configuration

## On a Deep Origin workstation

On a Deep Origin workstation, no configuration is needed! Within a workstation, the Deep Origin Python client is automatically configured.

## On your local computer

To run this package outside of a Deep Origin workstation (for example, on your own computer), first you need to configure this package. After installing this package, set your organization key and environment.



```{.python notest}
from deeporigin import config
config.set_value("org_key", "your-org-key")
config.set_value("env", "prod")  # or "staging" / "edge"
```


## View configuration

To view the configuration for this package, run:


```{.python notest}
from deeporigin import config
config.get_value()

```
