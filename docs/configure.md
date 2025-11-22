# Configuration

To configure the client to connect to the DeepOrigin API, set your organization key and environment.


```{.python notest}
from deeporigin import config
config.set_value("org_key", "your-org-key")
config.set_value("env", "prod")  
```


## View configuration

To view the configuration for this package, run:


```{.python notest}
from deeporigin import config
config.get_value()

```
